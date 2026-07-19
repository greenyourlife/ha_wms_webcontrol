# Changelog

## 0.2.3 – 2026-07-19

- **Markisen-Prozente korrigiert:** Die Box meldet die eingefahrene Markise als
  Library-Position 0. Markisen werden daher wieder **nicht** invertiert, sodass
  eingefahren = HA `0 %` (= „Geschlossen") und ausgefahren = HA `100 %`. Der
  Flip in 0.2.1 auf „invertiert" war falsch (er zeigte eingefahren als `100 %`);
  Ursache der damaligen Fehldiagnose war der zeitgleiche Fahr-Bug, nicht die
  Anzeige-Richtung.

## 0.2.2 – 2026-07-19

- **Regression behoben: Behänge fuhren nicht mehr.** Der in „Fahrbefehle
  beschleunigen" eingeführte, schlanke Fahrweg übersprang die „check ready"-
  Prüfung der Box – dadurch verwarf die Box den Fahrbefehl. Es wird wieder die
  bewährte Library-Methode `set_shade_position` verwendet, jetzt mit dem
  Coordinator-Lock (keine Poll-Kollision) und reduzierten Retries
  (`SHADE_NUM_RETRIES = 2`), was die ursprüngliche ~30 s-Verzögerung kürzt.

## 0.2.1 – 2026-07-19

- **Markisen-Invertierung korrigiert:** Markisen werden jetzt wie alle anderen
  Behänge invertiert (HA `100 % = ausgefahren` = Library-Position 0, HA `0 %` =
  eingefahren → „Geschlossen"). Die in 0.2.0 eingeführte Ausnahme drehte den
  Positions-Schieber und die Positions-Buttons falschherum.
- Status-Sensor wieder im HA-Raum – bleibt konsistent mit dem Cover-Zustand.
- Weiterhin pro Kanal über die Option „Position invertieren" umstellbar.

## 0.2.0 – 2026-07-18

- **Markisen-Semantik korrigiert:** Position wird für `awning`-Kanäle nicht mehr
  invertiert (HA-Konvention: `open` = ausgefahren, `closed` = eingefahren). Eine
  eingefahrene Markise zeigt damit „Geschlossen" statt „Offen". Pro Kanal über die
  neue Options-Zeile `Kanalname = true/false` überschreibbar.
- **Neuer Status-Sensor je Markise** mit übersetzten Zuständen
  „Eingefahren / Ausgefahren / Fährt ein / Fährt aus / Teilweise ausgefahren".
- Bewegungs-Zielposition wird jetzt im Coordinator gehalten und von Cover und
  Sensor gemeinsam genutzt.

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
