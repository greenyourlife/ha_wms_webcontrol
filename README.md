# WAREMA WMS WebControl – Home Assistant Integration

Steuert WAREMA-Behänge (Markisen, Rollläden, Raffstores, Rollos …) über die
**lokale WMS WebControl-Box (Basic, nicht „pro“)**. Szenen werden aus der Box
gelesen und als Buttons angelegt.

- Domain: `wms_webcontrol`
- IoT-Class: `local_polling`
- Home Assistant: **2026.6.0+**
- Keine externen Abhängigkeiten. Das Protokoll ist in
  [`docs/PROTOCOL.md`](docs/PROTOCOL.md) beschrieben (aus der Weboberfläche der
  Box ausgelesen, keine offizielle WAREMA-Doku).

> Für die **WMS WebControl pro** gibt es die offizielle HA-Integration `wmspro`.
> Diese Integration hier ist nur für die ältere Box.

## Funktionsumfang

- **Automatische Erkennung** aller Räume, Behänge und Szenen der Box.
- **Cover je Behang** mit `OPEN`, `CLOSE`, `SET_POSITION`, `STOP`.
  - Geräteklasse aus dem Produkttyp der Box (Markise → `awning`, Rollladen →
    `shutter`, Raffstore → `blind`, …), per Option überschreibbar.
  - Markisen: HA `0 %` = eingefahren = „Geschlossen“, `100 %` = ausgefahren.
    Andere Behänge werden invertiert. Pro Kanal überschreibbar.
  - Markisen mit Volant: zusätzliches Cover je Volant.
- **Szenen-Buttons** für jede in der Box gespeicherte Szene.
- **Winken-Button** je Behang (Motor bewegt sich kurz zur Identifikation).
- **Status-Sensor je Markise** („Eingefahren / Ausgefahren / Fährt ein / …“).
- **Zuverlässigkeit:**
  - Jeder Befehl wird von der Box quittiert. „Busy“ → automatisch erneut senden
    (wie die offizielle Oberfläche). Szenen werden zusätzlich auf Ausführung
    geprüft. Eine nicht ausgeführte Szene erzeugt eine Fehlermeldung in HA.
  - Kurze Busy-Phasen beim Polling werden toleriert; erst 3 Fehlschläge in Folge
    machen die Entities `unavailable` (z. B. wenn die Box hängt).
  - Fahrbefehle des Covers werfen keinen Fehler, damit Wind-/Regen-Skripte nicht
    abbrechen. Sie prüfen den Endzustand selbst.

## Sicherheit

Die Integration sendet nur eine fest definierte Liste von Telegrammen
(`ALLOWED_TELEGRAMS` in `client.py`): Abfragen, Fahren, Stopp, Szene ausführen,
Winken. **Löschen, Umbenennen, Projekt laden und „Szene lernen“ sind gesperrt**
und verlassen HA nie, auch nicht über manuell eingetragene Presets.

## Installation

### HACS (Custom Repository)

1. HACS → drei Punkte oben rechts → **Benutzerdefinierte Repositories**.
2. Repository: `https://github.com/greenyourlife/ha_wms_webcontrol`,
   Kategorie **Integration**.
3. „WAREMA WMS WebControl“ herunterladen.
4. Home Assistant neu starten.

### Manuell

Ordner `custom_components/wms_webcontrol/` nach
`config/custom_components/wms_webcontrol/` kopieren und Home Assistant neu starten.

## Einrichtung

**Einstellungen → Geräte & Dienste → Integration hinzufügen → „WAREMA WMS WebControl“**

- **WebControl-URL**, z. B. `http://webcontrol.local` oder `http://<IP der Box>`.
- **Aktualisierungsintervall**: Standard `600` s. Nach jedem Befehl wird für
  ~15 s häufiger gepollt.

### Optionen

Über **Konfigurieren** an der Integrationskachel:

- **Aktualisierungsintervall**
- **Zusätzliche Presets** (optional) – `Name | payload_hex` je Zeile. Szenen
  werden automatisch erkannt; ein Preset mit dem Payload einer erkannten Szene
  ändert nur deren Anzeigenamen. Format eines Szenen-Payloads:
  `0821 <raum> <kanal> 08ffffffff` (Hex).
- **Geräteklassen-Überschreibung** (optional) – `Kanalname = awning` je Zeile.
- **Position invertieren** (optional) – `Kanalname = true/false` je Zeile.
- **Kanäle ausschließen** (optional) – ein Behang-Name je Zeile. Gilt nur für
  Behänge; Szenen werden immer als Buttons angelegt.

## Upgrade von 0.3.x

- Entity-IDs bleiben erhalten (gleiche `unique_id`s). Preset-Buttons, deren
  Payload zu einer Szene der Box passt, werden zu Szenen-Buttons und behalten
  ihren Namen.
- Die bisherige Ausschlussliste für Szenen-„Kanäle“ wird nicht mehr gebraucht,
  stört aber nicht.
- Neu: `STOP` am Cover, Winken-Buttons.

## Bekannte Limitierungen

- Licht-, Last- und Steckdosen-Aktoren werden erkannt, aber noch nicht als
  Entities angelegt.
- Die gespeicherten **Positionen** einer Szene liegen im Motor und lassen sich
  nicht auslesen, nur Name und Nummer.
- Wird ein Behang per Handsender bewegt, ist die Fahrtrichtung nicht ableitbar.

## Entwicklung / Tests

```
python -m pytest -q                       # Unit-Tests (ohne Home Assistant)
pip install pytest-homeassistant-custom-component
python -m pytest -q                       # zusätzlich tests/ha (HA-Testinstanz)
```

`tests/ha/fakebox.py` simuliert die Box für die Integrationstests.

## Lizenz

MIT (siehe `LICENSE`).
