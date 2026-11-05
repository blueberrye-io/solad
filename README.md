# Solad – PV-Überschussladen mit sonnenBatterie und NRGkick

Solad lädt das Elektroauto mit dem Solarstrom, den das Haus gerade nicht braucht. Es liest
die **sonnenBatterie** (PV-Leistung, Hausverbrauch, Speicherstand) und stellt an der
Wallbox **NRGkick Gen2** Strom und Phasenzahl ein. Alles läuft lokal im Heimnetz, ohne Cloud.

Projektseite mit Erklärung: <https://electronobotics.de/projekte/solad/solad.html>

**Für wen:** Solad ist für genau diese Kombination geschrieben: sonnenBatterie mit JSON-API v2
und NRGkick Gen2 mit lokaler API. Andere Geräte planen wir nicht. Der Code ist aber klein und
offen, damit jeder ihn für seine Anlage anpassen kann.

## Was der Regler tut

- **Überschuss** = PV-Leistung − Hausverbrauch ohne Auto. Der Verbrauchswert der sonnenBatterie
  enthält das Auto, deshalb wird die Ladeleistung abgezogen.
- **Laden ab 6 A:** einphasig ab 6 A × 230 V ≈ 1,4 kW, dreiphasig ab 3 × 6 A × 230 V ≈ 4,1 kW,
  höchstens 16 A.
- **Keine Schaltorgie bei Wolken:** Start erst nach 2 min genug Überschuss, Stopp erst nach
  5 min zu wenig, zwischen zwei Phasenwechseln mindestens 5 min.
- **Winterregel (15.10. bis Ende Februar):** Das Auto lädt erst, wenn der Hausspeicher zu
  mindestens 95 % voll ist. Im Sommer lädt die sonnenBatterie netzdienlich (Prognose-Laden),
  im Winter wird das abgeschaltet.
- **Vollgas-Modi** legen den Hausspeicher still (manueller Modus, Sollwert 0), damit er nicht
  ins Auto entladen wird. Danach geht er zurück auf Eigenverbrauch.

| Modus | Bedeutung |
|---|---|
| `beobachten` | nur anzeigen, keine Befehle an die Wallbox (Startmodus zum Ausprobieren) |
| `pv` | nur mit Überschuss laden |
| `voll` | mit 3 × 16 A laden, bis das Auto voll ist |
| `kwh` | eine feste Menge mit Vollgas laden, danach weiter mit `pv` |
| `aus` | Laden pausiert |

Die Regel-Logik (`solad/regler.py`) enthält keinen Netzwerk-Code und ist mit Unit-Tests abgedeckt.

## Installation

Voraussetzungen: Python 3.11 oder neuer, ein Rechner im Heimnetz, der dauernd läuft.

```bash
git clone https://github.com/blueberrye-io/solad.git Solad
cd Solad
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # IPs und Token eintragen
.venv/bin/python -m pytest  # Tests
.venv/bin/uvicorn solad.app:app --host 0.0.0.0 --port 8000
```

Dann im Browser `http://<IP-des-Rechners>:8000` öffnen. `deploy/` enthält einen
LaunchDaemon für macOS, der Solad beim Hochfahren als eigener Benutzer `solad` startet.

Vorher an den Geräten einschalten:

- **sonnenBatterie:** Webinterface → Software-Integration → JSON-API (Read) und JSON Write API.
  Der Schreib-Token wird für den Betriebsmodus und das Stilllegen gebraucht.
- **NRGkick Gen2:** in der NRGkick-App die lokale API aktivieren.

## Sicherheit

- Die Weboberfläche hat **keine Anmeldung**. Solad nur im Heimnetz betreiben und **nie per
  Portfreigabe ins Internet** stellen.
- Die `.env` enthält die Token der sonnenBatterie. Nicht weitergeben und nicht einchecken.
- Solad steuert nur über die offiziellen lokalen Schnittstellen der Geräte. Die Schutzfunktionen
  von Wallbox und Fahrzeug bleiben unberührt. Nutzung auf eigene Verantwortung.

## Hinweis

Kein offizielles Projekt von sonnen oder NRGkick. Die Namen sind Marken ihrer Inhaber.

Lizenz: MIT, siehe `LICENSE`.
