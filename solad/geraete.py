"""Zugriff auf sonnenBatterie und NRGkick über das lokale Netz."""
from __future__ import annotations

import os

import httpx

from .regler import Befehl


class Sonnen:
    def __init__(self, host: str, token: str, schreib_token: str | None = None):
        self.url = f"http://{host}/api/v2/latestdata"
        self.headers = {"Auth-Token": token}
        self.schreib_headers = {"Auth-Token": schreib_token or token}

    async def lesen(self, client: httpx.AsyncClient) -> dict:
        r = await client.get(self.url, headers=self.headers)
        r.raise_for_status()
        return r.json()

    async def modus_lesen(self, client: httpx.AsyncClient) -> int:
        """EM_OperatingMode: 1 = manuell, 2 = Eigenverbrauch (normal)."""
        r = await client.get(self.url.replace("latestdata", "configurations/EM_OperatingMode"),
                             headers=self.headers)
        r.raise_for_status()
        return int(r.json()["EM_OperatingMode"])

    async def modus_setzen(self, client: httpx.AsyncClient, modus: int) -> None:
        r = await client.put(self.url.replace("latestdata", "configurations"),
                             headers=self.headers, data={"EM_OperatingMode": str(modus)})
        r.raise_for_status()

    async def config_lesen(self, client: httpx.AsyncClient, schluessel: str) -> str:
        r = await client.get(self.url.replace("latestdata", f"configurations/{schluessel}"),
                             headers=self.headers)
        r.raise_for_status()
        return r.json()[schluessel]

    async def config_setzen(self, client: httpx.AsyncClient, schluessel: str, wert: str) -> None:
        r = await client.put(self.url.replace("latestdata", "configurations"),
                             headers=self.headers, data={schluessel: wert})
        r.raise_for_status()

    async def speicher_stilllegen(self, client: httpx.AsyncClient) -> None:
        """Im manuellen Modus: weder laden noch entladen."""
        r = await client.post(self.url.replace("latestdata", "setpoint/discharge/0"),
                              headers=self.headers)
        r.raise_for_status()


class NRGkick:
    def __init__(self, host: str):
        self.basis = f"http://{host}"

    async def werte(self, client: httpx.AsyncClient) -> dict:
        r = await client.get(f"{self.basis}/values")
        r.raise_for_status()
        return r.json()

    async def steuerung(self, client: httpx.AsyncClient) -> dict:
        r = await client.get(f"{self.basis}/control")
        r.raise_for_status()
        return r.json()

    async def senden(self, client: httpx.AsyncClient, b: Befehl) -> None:
        if b.pause:
            params = {"charge_pause": 1}
        else:
            params = {"charge_pause": 0, "phase_count": b.phasen, "current_set": b.strom_a}
        r = await client.get(f"{self.basis}/control", params=params)
        r.raise_for_status()


def lade_env(pfad: str = ".env") -> None:
    """Minimaler .env-Leser (KEY=WERT), ohne Zusatzpaket."""
    if not os.path.exists(pfad):
        return
    with open(pfad) as f:
        for zeile in f:
            zeile = zeile.strip()
            if zeile and not zeile.startswith("#") and "=" in zeile:
                k, v = zeile.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))
