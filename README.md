# WAREMA WMS WebControl – Home Assistant Integration

Steuert WAREMA-Behänge (Rollos, Raffstores und – experimentell – Markisen) über
die **lokale WebControl-Box (non-Pro)**. Neben freier Positionssteuerung werden
mitgeschnittene **Szenen** als Preset-Buttons abgebildet.

Die Integration nutzt die PyPI-Library
[`warema-wms-controller`](https://github.com/cornim/wms_webcontrol) als Transport.

- Domain: `wms_webcontrol`
- IoT-Class: `local_polling`
- Home Assistant: **2026.6.0+**

> **Hinweis zum Paketnamen:** Der Import-Namespace lautet `warema_wms`, das
> PyPI-Paket heißt jedoch **`warema-wms-controller`** (aktuell `0.2.4`). Das ist
> in `manifest.json` so hinterlegt; Home Assistant installiert die Abhängigkeit
> automatisch.

## Funktionsumfang

- **Cover-Entity je entdecktem Kanal** mit `OPEN`, `CLOSE`, `SET_POSITION`.
  - Rollos/Raffstores: Position wird gegenüber der Box invertiert
    (HA `100 % = offen`, Library `0 = offen`).
  - Markisen (`awning`): Position wird **nicht** invertiert. Die Box meldet die
    eingefahrene Markise als Library-Position 0 → HA `0 %` = eingefahren →
    Zustand „Geschlossen"; HA `100 %` = voll ausgefahren. Pro Kanal überschreibbar
    (siehe Optionen), falls ein Behang andersherum meldet.
  - `is_opening` / `is_closing` werden aus dem Bewegungsstatus und der zuletzt
    kommandierten Zielposition abgeleitet.
  - Geräteklasse: Markisen → `awning`, sonst `shutter` (per Name-Heuristik,
    überschreibbar, siehe unten).
- **Status-Sensor je Markise** mit Klartext-Zuständen
  „Eingefahren / Ausgefahren / Fährt ein / Fährt aus / Teilweise ausgefahren"
  (übersetzt) – gedacht fürs Dashboard, da die HA-Cover-Grundzustände
  („Offen/Geschlossen") sich nicht pro Entity umbenennen lassen.
- **Preset-Buttons** für gespeicherte Szenen. Ein Tastendruck spielt die
  mitgeschnittene Protokoll-Payload 1:1 ab (kein Positions-Parsing).
- **DataUpdateCoordinator** mit konfigurierbarem Intervall; nach einem Fahrbefehl
  wird für ~15 s häufiger gepollt, weil die Box „nicht bewegend" verzögert meldet.
- Blocking I/O der Library läuft ausschließlich im Executor; Netzwerk-Timeouts
  setzen die Entities auf `unavailable`.

## Installation

### HACS (Custom Repository)

1. HACS → drei Punkte oben rechts → **Custom repositories**.
2. Repository: `https://github.com/greenyourlife/ha_wms_webcontrol`,
   Kategorie **Integration**.
3. „WAREMA WMS WebControl" installieren.
4. Home Assistant neu starten.

### Manuell

Ordner `custom_components/wms_webcontrol/` in das HA-Config-Verzeichnis kopieren
(`config/custom_components/wms_webcontrol/`) und Home Assistant neu starten.

## Einrichtung

**Einstellungen → Geräte & Dienste → Integration hinzufügen → „WAREMA WMS WebControl"**

- **WebControl-URL**: Adresse der lokalen Box, z. B. `http://webcontrol.local`
  oder die IP der Box im eigenen Netz (z. B. `http://192.0.2.17`). Die Verbindung
  (inkl. Auto-Discovery) wird im Dialog getestet.
- **Aktualisierungsintervall**: Standard `600` s.

### Optionen (nachträglich änderbar)

Über **Konfigurieren** an der Integrationskachel:

- **Aktualisierungsintervall**
- **Presets** – eine Zeile je Preset im Format `Name | payload_hex`. Vorbelegt mit:

  | Preset            | payload_hex          |
  |-------------------|----------------------|
  | Markise einfahren | `0821000308ffffffff` |
  | Markise 60 %      | `0821000108ffffffff` |
  | Markise 100 %     | `0821000208ffffffff` |

  Weitere mitgeschnittene Szenen einfach als zusätzliche Zeile ergänzen. Die
  Payload ist der reine Protokoll-String **ohne** den variablen `90<counter>`-Prefix
  (den setzt die Library automatisch). Format der Szenen: `0821 + 00 + <idx> + 08ffffffff`.
- **Geräteklassen-Überschreibung** (optional) – eine Zeile je Kanal im Format
  `Kanalname = awning` (oder `shutter`, `blind`, `curtain`, `shade`, …).
- **Position invertieren** (optional) – eine Zeile je Kanal im Format
  `Kanalname = true` oder `= false`. Standard: Markisen `false` (nicht invertiert,
  HA `0 % = eingefahren`), alles andere `true`. Nur nötig, falls ein Behang die
  Positionen andersherum meldet als erwartet.
- **Kanäle ausschließen** (optional) – ein Kanalname je Zeile. Nützlich, wenn die
  WMS gespeicherte Szenen als eigene „Kanäle" mitliefert (z. B. `60% raus`,
  `100 % raus`): Diese werden dann nicht als Cover/Sensor angelegt und nicht
  gepollt. Die Szenen selbst bleiben als Preset-Buttons verfügbar.

## Eigene Presets mitschneiden

Die Payload einer gespeicherten Szene lässt sich aus dem Netzwerkverkehr der
WebControl-Weboberfläche ablesen: Beim Szenen-Recall sendet die App einen
`GET /protocol.xml?protocol=90XX0821...&_=...`. Aus dem `protocol`-Wert die
ersten vier Zeichen (`90` + zweistelliger Counter) entfernen – der Rest ist die
`payload_hex` für ein neues Preset.

## Verifikation am Gerät

1. **Lokale Erreichbarkeit prüfen** (falls die Box bisher nur über die
   WAREMA-Cloud angesprochen wurde):
   ```
   curl "http://<box-ip>/protocol.xml?protocol=900323&_=1"
   ```
   Es muss XML zurückkommen (kein Timeout / kein Cloud-Redirect).
2. Integration einrichten und prüfen, dass Kanäle als Cover-Entities erscheinen.
3. Eine Cover-Position setzen und beobachten, ob der Behang fährt und die Position
   nach ~15 s korrekt gemeldet wird.
4. Preset-Buttons drücken und die Reaktion der Markise prüfen.

## Bekannte Limitierungen

- **Markise experimentell:** Die zugrunde liegende Library wurde nur mit
  vertikalen Raffstores getestet. Ob die Markise als Kanal erscheint und
  Position/Fahrt zuverlässig meldet, ist offen. Falls die Markise keine Position
  liefert, funktionieren die **Preset-Buttons** trotzdem (reiner Szenen-Replay).
- **Keine STOP-Funktion:** Die Library kennt kein Stopp-Kommando; entsprechend
  wird `CoverEntityFeature.STOP` nicht angeboten.
- **Richtungsanzeige bei Fremdsteuerung:** Wird ein Behang per Handsender bewegt,
  ist die Fahrtrichtung ohne bekanntes Ziel nicht ableitbar; die Entity zeigt dann
  nur den Positionswechsel, nicht `opening`/`closing`.
- **Verzögerte Statusmeldung:** Die Box meldet das Ende einer Fahrt verzögert –
  daher das kurzzeitig schnellere Polling nach jedem Kommando.

## Entwicklung / Tests

Framework-freie Kernlogik (Positions-Invertierung, Zustands-Ableitung,
Preset-Send) liegt in `helpers.py` und ist ohne Home-Assistant-Installation
testbar:

```
python -m pytest tests/test_helpers.py -q
```

Für die vollständige Validierung im HA-Dev-Container:

```
python -m script.hassfest --integration-path custom_components/wms_webcontrol
ruff check custom_components/wms_webcontrol
```

## Lizenz

MIT (siehe `LICENSE`). Die Transport-Library `warema-wms-controller` steht unter
LGPLv3.
