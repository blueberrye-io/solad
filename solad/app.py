"""Webseite + Regelschleife.  Start:  .venv/bin/uvicorn solad.app:app --host 0.0.0.0 --port 8000"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .geraete import NRGkick, Sonnen, lade_env
from .regler import Befehl, Messung, Regler, ist_winter, ueberschuss_w

lade_env(str(Path(__file__).parent.parent / ".env"))
log = logging.getLogger("solad")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # nicht jede Abfrage loggen
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)  # nicht jeden Seitenaufruf

INTERVALL_S = 10
SONNEN_MANUELL, SONNEN_EIGENVERBRAUCH = 1, 2
# Der Schreib-Token darf auch lesen; der alte Lese-Token ist seit 2026-11-05 ungültig.
sonnen = Sonnen(os.environ["SONNEN_HOST"],
                os.environ.get("SONNEN_WRITE_TOKEN") or os.environ["SONNEN_TOKEN"])
nrgkick = NRGkick(os.environ["NRGKICK_HOST"])
MODUS_DATEI = Path(__file__).parent.parent / "modus.json"   # überlebt Neustarts
regler = Regler(os.environ.get("SOLAD_START_MODUS", "beobachten"))
try:
    _gespeichert = json.loads(MODUS_DATEI.read_text())
    regler.setze_modus(_gespeichert["modus"], _gespeichert.get("kwh", 0.0))
except (OSError, ValueError, KeyError):
    pass  # keine/kaputte Datei -> Startmodus
zustand: dict = {"fehler": "Noch keine Daten"}


async def jahreszeit_einstellen(client: httpx.AsyncClient):
    """Winter: alles für den Eigenverbrauch (Prognose-Laden aus).
    Rest des Jahres: netzdienlich – sonnen lädt den Speicher prognosebasiert erst mittags."""
    soll = "0" if ist_winter(date.today()) else "1"
    ist = await sonnen.config_lesen(client, "EM_Prognosis_Charging")
    if ist != soll:
        log.info("Prognose-Laden %s -> %s", ist, soll)
        await sonnen.config_setzen(client, "EM_Prognosis_Charging", soll)


async def regelschleife():
    async with httpx.AsyncClient(timeout=5) as client:
        naechste_jahreszeit_pruefung = 0.0
        while True:
            try:
                if time.monotonic() >= naechste_jahreszeit_pruefung:
                    await jahreszeit_einstellen(client)
                    naechste_jahreszeit_pruefung = time.monotonic() + 3600
                await ein_durchlauf(client)
            except Exception as e:  # Geräte kurz weg o. ä. – weitermachen
                log.warning("Durchlauf fehlgeschlagen: %s", e)
                zustand["fehler"] = str(e)
            await asyncio.sleep(INTERVALL_S)


async def ein_durchlauf(client: httpx.AsyncClient):
    s, w, c, sonnen_modus = await asyncio.gather(
        sonnen.lesen(client), nrgkick.werte(client), nrgkick.steuerung(client),
        sonnen.modus_lesen(client),
    )
    m = Messung(
        produktion_w=s["Production_W"],
        verbrauch_w=s["Consumption_W"],
        auto_w=w["powerflow"]["total_active_power"],
        speicher_soc=s["USOC"],
        auto_energie_wh=w["energy"]["charged_energy"],
    )
    ist = Befehl(pause=bool(c["charge_pause"]), phasen=int(c["phase_count"]),
                 strom_a=int(float(c["current_set"])))
    regler.letzter = ist  # vom echten Wallbox-Zustand ausgehen (z. B. nach Neustart)
    befehl = regler.schritt(m, time.monotonic(), date.today())
    if befehl and befehl != ist and not (befehl.pause and ist.pause):
        log.info("Sende %s (vorher %s)", befehl, ist)
        await nrgkick.senden(client, befehl)

    # Vollgas: Speicher stilllegen (manuell, Sollwert 0) -> Auto lädt aus PV + Netz.
    # Danach zurück auf Eigenverbrauch. Getestet 2026-11-05: Speicher sofort 0 W.
    if regler.modus in ("voll", "kwh"):
        if sonnen_modus != SONNEN_MANUELL:
            log.info("Speicher stilllegen (manueller Modus, Sollwert 0)")
            await sonnen.modus_setzen(client, SONNEN_MANUELL)
            sonnen_modus = SONNEN_MANUELL
        await sonnen.speicher_stilllegen(client)
    elif sonnen_modus == SONNEN_MANUELL:
        log.info("Speicher wieder auf Eigenverbrauch")
        await sonnen.modus_setzen(client, SONNEN_EIGENVERBRAUCH)
        sonnen_modus = SONNEN_EIGENVERBRAUCH

    zustand.clear()
    zustand.update(
        zeit=datetime.now().strftime("%H:%M:%S"),
        modus=regler.modus,
        kwh_ziel=regler.kwh_ziel,
        info=regler.info,
        winter=ist_winter(date.today()),
        pv_w=m.produktion_w,
        haus_w=m.verbrauch_w - m.auto_w,
        ueberschuss_w=ueberschuss_w(m),
        speicher_soc=m.speicher_soc,
        speicher_gesperrt=sonnen_modus == SONNEN_MANUELL,
        speicher_w=s["Pac_total_W"],      # + entlädt, − lädt
        netz_w=-s["GridFeedIn_W"],         # + Bezug, − Einspeisung
        auto_w=m.auto_w,
        auto_status=w["general"]["status"],
        auto_geladen_kwh=m.auto_energie_wh / 1000,
        wallbox=ist.__dict__,
        fehler=None,
    )


@asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(regelschleife())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)


class ModusWunsch(BaseModel):
    modus: str
    kwh: float = 0.0


@app.get("/")
def startseite():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/api/status")
def status():
    return zustand


@app.post("/api/modus")
def modus(w: ModusWunsch):
    if w.modus == "kwh" and not 0 < w.kwh <= 100:
        raise HTTPException(400, "kWh zwischen 0 und 100 angeben")
    try:
        regler.setze_modus(w.modus, w.kwh)
    except ValueError as e:
        raise HTTPException(400, str(e))
    MODUS_DATEI.write_text(json.dumps({"modus": w.modus, "kwh": w.kwh}))
    log.info("Modus -> %s %s", w.modus, w.kwh if w.modus == "kwh" else "")
    return {"ok": True}
