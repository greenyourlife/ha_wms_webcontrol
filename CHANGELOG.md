# Changelog

## 0.1.0 – 2026-07-18

Initial release.

- Config-Flow-Einrichtung (kein YAML) mit Verbindungstest über Auto-Discovery.
- Options-Flow: Aktualisierungsintervall, Presets (Name | payload_hex) und
  optionale Geräteklassen-Überschreibung.
- Cover-Entity je Kanal mit `OPEN` / `CLOSE` / `SET_POSITION`; invertierte
  Position (HA `100 % = offen`), `is_opening` / `is_closing` aus Bewegung + Ziel.
- Preset-Buttons als 1:1-Replay mitgeschnittener Szenen-Payloads via `send_raw`.
- `DataUpdateCoordinator` mit konfigurierbarem Intervall und schnellerem Polling
  (~15 s) nach jedem Kommando; Blocking I/O im Executor.
- Transport über `warema-wms-controller==0.2.4`.
- Übersetzungen: Englisch, Deutsch.
- Unit-Tests für Positions-Invertierung, Zustands-Ableitung und Preset-Send.
