from datetime import date

from solad.regler import PAUSE, VOLLGAS, Befehl, Messung, Regler

SOMMER = date(2026, 6, 15)
WINTER = date(2026, 12, 15)


def messung(pv=0, haus=500, auto=0, soc=50, energie=0):
    return Messung(produktion_w=pv, verbrauch_w=haus + auto, auto_w=auto,
                   speicher_soc=soc, auto_energie_wh=energie)


def test_beobachten_sendet_nichts():
    assert Regler().schritt(messung(pv=8000), 0, SOMMER) is None


def test_voll_und_aus():
    r = Regler("voll")
    assert r.schritt(messung(), 0, WINTER) == VOLLGAS
    r.setze_modus("aus")
    assert r.schritt(messung(pv=9000), 0, SOMMER) == PAUSE


def test_pv_startet_erst_nach_verzoegerung():
    r = Regler("pv")
    m = messung(pv=3000, haus=500)            # 2,5 kW Überschuss
    assert r.schritt(m, 0, SOMMER) == PAUSE
    assert r.schritt(m, 60, SOMMER) == PAUSE
    assert r.schritt(m, 130, SOMMER) == Befehl(False, 1, 10)


def test_pv_dreiphasig_bei_viel_sonne():
    r = Regler("pv")
    r.letzter = Befehl(False, 3, 6)
    # Auto lädt schon mit 4 kW, PV 9 kW, Haus 500 W -> 8,5 kW frei
    assert r.schritt(messung(pv=9000, haus=500, auto=4000), 0, SOMMER) == Befehl(False, 3, 12)


def test_pv_stoppt_erst_nach_verzoegerung():
    r = Regler("pv")
    r.letzter = Befehl(False, 1, 6)
    m = messung(pv=600, haus=500, auto=1400)
    assert r.schritt(m, 0, SOMMER) == Befehl(False, 1, 6)
    assert r.schritt(m, 310, SOMMER) == PAUSE


def test_winter_speicher_hat_vorrang():
    r = Regler("pv")
    assert r.schritt(messung(pv=8000, soc=60), 0, WINTER) == PAUSE
    assert r.schritt(messung(pv=8000, soc=60), 500, WINTER) == PAUSE
    assert "Winter" in r.info


def test_kwh_modus_schaltet_auf_pv_zurueck():
    r = Regler()
    r.setze_modus("kwh", 5)
    assert r.schritt(messung(energie=1000), 0, SOMMER) == VOLLGAS
    assert r.schritt(messung(energie=4000), 10, SOMMER) == VOLLGAS
    r.schritt(messung(energie=6100), 20, SOMMER)
    assert r.modus == "pv"
