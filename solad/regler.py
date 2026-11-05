"""Regel-Logik: entscheidet aus einer Messung, wie die Wallbox laden soll.

Bewusst ohne Netzwerk-Code, damit sie sich einfach testen lässt.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

SPANNUNG_V = 230
MIN_A, MAX_A = 6, 16
MIN_1P_W = MIN_A * SPANNUNG_V          # ~1,4 kW
MIN_3P_W = 3 * MIN_A * SPANNUNG_V      # ~4,1 kW

WINTER_SOC_MIN = 95       # Winter: Auto erst, wenn Hausspeicher mind. so voll ist
START_VERZOEGERUNG_S = 120
STOPP_VERZOEGERUNG_S = 300
PHASENWECHSEL_PAUSE_S = 300

MODI = ("beobachten", "pv", "voll", "kwh", "aus")


@dataclass
class Messung:
    produktion_w: float
    verbrauch_w: float        # sonnen Consumption_W – enthält das Auto!
    auto_w: float
    speicher_soc: float
    auto_energie_wh: float    # NRGkick charged_energy (seit Anstecken)


@dataclass(frozen=True)
class Befehl:
    pause: bool
    phasen: int = 3
    strom_a: int = MIN_A


VOLLGAS = Befehl(pause=False, phasen=3, strom_a=MAX_A)
PAUSE = Befehl(pause=True)


def ist_winter(tag: date) -> bool:
    """15.10. bis 28./29.02.: Hausspeicher hat Vorrang."""
    return tag.month in (11, 12, 1, 2) or (tag.month == 10 and tag.day >= 15)


def ueberschuss_w(m: Messung) -> float:
    """PV-Leistung minus Hausverbrauch (ohne Auto)."""
    return m.produktion_w - (m.verbrauch_w - m.auto_w)


class Regler:
    def __init__(self, modus: str = "beobachten"):
        self.modus = modus
        self.kwh_ziel = 0.0
        self.kwh_start_wh: float | None = None
        self.letzter: Befehl = PAUSE
        self.letzter_phasenwechsel = -1e9
        self.genug_seit: float | None = None
        self.zu_wenig_seit: float | None = None
        self.info = ""

    def setze_modus(self, modus: str, kwh: float = 0.0) -> None:
        if modus not in MODI:
            raise ValueError(f"Unbekannter Modus: {modus}")
        self.modus = modus
        self.kwh_ziel = kwh
        self.kwh_start_wh = None
        self.genug_seit = self.zu_wenig_seit = None

    def schritt(self, m: Messung, jetzt: float, heute: date) -> Befehl | None:
        """Liefert den gewünschten Befehl, oder None = nichts an die Wallbox senden."""
        if self.modus == "beobachten":
            self.info = "Nur beobachten – keine Befehle an die Wallbox"
            return None
        if self.modus == "aus":
            self.info = "Laden pausiert"
            return self._merke(PAUSE, jetzt)
        if self.modus == "voll":
            self.info = "Vollgas bis das Auto voll ist"
            return self._merke(VOLLGAS, jetzt)
        if self.modus == "kwh":
            return self._kwh(m, jetzt, heute)
        return self._pv(m, jetzt, heute)

    # --- Modi ---------------------------------------------------------------

    def _kwh(self, m: Messung, jetzt: float, heute: date) -> Befehl | None:
        if self.kwh_start_wh is None or m.auto_energie_wh < self.kwh_start_wh:
            # Start, oder Auto wurde zwischendurch neu angesteckt (Zähler bei 0)
            self.kwh_start_wh = m.auto_energie_wh
        geladen_kwh = (m.auto_energie_wh - self.kwh_start_wh) / 1000
        if geladen_kwh >= self.kwh_ziel:
            self.setze_modus("pv")
            return self._pv(m, jetzt, heute)
        self.info = f"Vollgas: {geladen_kwh:.1f} von {self.kwh_ziel:.1f} kWh"
        return self._merke(VOLLGAS, jetzt)

    def _pv(self, m: Messung, jetzt: float, heute: date) -> Befehl:
        verfuegbar = ueberschuss_w(m)
        if ist_winter(heute) and m.speicher_soc < WINTER_SOC_MIN:
            self.info = f"Winter: Hausspeicher zuerst ({m.speicher_soc:.0f} % < {WINTER_SOC_MIN} %)"
            verfuegbar = 0
        else:
            self.info = f"PV-Überschuss {verfuegbar / 1000:.1f} kW"

        genug = verfuegbar >= MIN_1P_W

        # Start/Stopp mit Verzögerung, damit Wolken nicht ständig schalten
        if self.letzter.pause:
            self.zu_wenig_seit = None
            if not genug:
                self.genug_seit = None
                return self._merke(PAUSE, jetzt)
            if self.genug_seit is None:
                self.genug_seit = jetzt
            if jetzt - self.genug_seit < START_VERZOEGERUNG_S:
                self.info += " – starte gleich"
                return PAUSE
        else:
            self.genug_seit = None
            if not genug:
                if self.zu_wenig_seit is None:
                    self.zu_wenig_seit = jetzt
                if jetzt - self.zu_wenig_seit >= STOPP_VERZOEGERUNG_S:
                    return self._merke(PAUSE, jetzt)
                self.info += " – zu wenig, warte noch"
                return self._merke(self._befehl_fuer(MIN_1P_W, jetzt), jetzt)
            self.zu_wenig_seit = None

        return self._merke(self._befehl_fuer(verfuegbar, jetzt), jetzt)

    # --- Hilfen -------------------------------------------------------------

    def _befehl_fuer(self, watt: float, jetzt: float) -> Befehl:
        phasen = 3 if watt >= MIN_3P_W else 1
        wechsel_erlaubt = jetzt - self.letzter_phasenwechsel >= PHASENWECHSEL_PAUSE_S
        if not self.letzter.pause and phasen != self.letzter.phasen and not wechsel_erlaubt:
            phasen = self.letzter.phasen
        strom = int(watt // (phasen * SPANNUNG_V))
        return Befehl(pause=False, phasen=phasen, strom_a=max(MIN_A, min(MAX_A, strom)))

    def _merke(self, b: Befehl, jetzt: float) -> Befehl:
        if not b.pause and not self.letzter.pause and b.phasen != self.letzter.phasen:
            self.letzter_phasenwechsel = jetzt
        self.letzter = b
        return b
