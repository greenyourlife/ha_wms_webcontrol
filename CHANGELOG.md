# Changelog

## 0.5.0 – 2026-10-09

- **Zeitschaltuhr lesen:** Neuer Sensor „Nächste Schaltzeit“ je Behang
  (Zeitstempel, Zielposition, kompletter Wochenplan und Ein/Aus als Attribute).
  Die Schaltzeiten liegen im Motor; gelesen wird per Funk beim Start und über
  den Button „Zeitschaltuhr lesen“. Ein Lesefehler wird einmal wiederholt.
- **Box-Uhr:** Diagnose-Sensor „Box-Uhr Abweichung“. Optional (Standard: an)
  stellt HA die Uhr beim Start und täglich um 03:30, wenn sie mehr als 60 s
  abweicht, damit greift auch die Sommer-/Winterzeit. Button „Box-Uhr stellen“.
  Der Schalter „Systemzeit senden“ der Box bleibt unverändert.
- **Reparaturhinweis**, wenn die Box länger als 15 Minuten nicht erreichbar ist
  (verschwindet automatisch, sobald sie wieder antwortet).
- **Diagnose-Download** (Einstellungen → Geräte & Dienste → Integration →
  Diagnose herunterladen), URL geschwärzt.
- Allowlist erweitert um Uhr lesen/stellen (nur plausible Werte) und die
  lesenden Timer-Telegramme. Timer schreiben, Box-Automatik und Grenzwerte
  setzen bleiben gesperrt.

## 0.4.0 – 2026-10-09

- **Eigene Protokoll-Implementierung statt `warema-wms-controller`.** Grundlage
  ist das JavaScript der Weboberfläche der Box (`docs/PROTOCOL.md`). Keine
  externe Abhängigkeit mehr, vollständig async über die HA-HTTP-Session.
- **Befehlszähler wie die offizielle Oberfläche** (0–254, nie 255). Die alte
  Library sendete auch 255.
- **Quittung und Ausführung über die Box selbst:** Nach einem Befehl wird das
  Ergebnis wie in der offiziellen Oberfläche abgefragt (Polling auf die
  Kanalbedienung). „Busy“ → erneut senden. Fallback auf die Bewegungsprüfung,
  wenn die Box keine Bestätigung liefert.
- **Szenen werden automatisch erkannt** und als Buttons angelegt. Bestehende
  Preset-Buttons mit passendem Payload behalten Entity-ID und Namen.
- **Typ-Erkennung** aus dem Produkttyp der Box (Markise, Rollladen, Raffstore,
  Rollo …) statt Namens-Heuristik; Volant-Covers für Markisen mit Volant.
- **Neu:** `STOP` am Cover, Winken-Button je Behang.
- **Sicherheits-Allowlist:** Nur Abfragen, Fahren, Stopp, Szene ausführen und
  Winken werden gesendet. Löschen/Umbenennen/Projekt laden/Szene lernen sind im
  Client gesperrt, auch für manuelle Presets.
- Tests: Protokoll-Client gegen simulierte Box, Integrationstests in einer
  HA-Testinstanz (`tests/ha`).
- An der Box getestet (2026-10-09, Markise): Szenen, Fahren auf Position,
  Stopp während der Fahrt, Gegenbefehl, Doppelklick und Schnellfolge. Alle
  Szenen wurden von der Box beim ersten Versuch quittiert.

## 0.3.2 – 2026-10-09

- **Preset-Buttons prüfen jetzt, ob der Befehl ankommt.** Die Quittung der Box
  auf das Szenen-Kommando (`feedback`) wird ausgewertet; bei Ablehnung wird
  erneut gesendet (bis zu 5 Versuche im Abstand von 1 s). Bleibt die Box nach
  den Ready-Abfragen „busy", wird das Kommando nicht mehr trotzdem gesendet
  (Lücke in 0.3.1). Hintergrund (Log 2026-10-09): Die Box meldete „bereit",
  lehnte das folgende Szenen-Kommando aber mit `feedback=0` ab – 0.3.1 hat das
  ignoriert, die Markise fuhr nicht.
- **Bewegungskontrolle nach Presets:** Nach dem Senden wird geprüft, ob ein
  Behang fährt oder seine Position geändert hat. Wenn nicht, wird die Szene
  einmal erneut gesendet. Erneut gesendet wird nur, wenn sich nachweislich
  nichts bewegt hat, ein laufender Motor wird also nicht unterbrochen. Keine
  Bewegung nach allen Versuchen wird als Warnung geloggt (Behang kann bereits
  in Zielposition sein).
- **Fehlgeschlagene Presets sind sichtbar:** Nimmt die Box den Befehl nicht an
  oder ist sie nicht erreichbar, wirft der Button einen `HomeAssistantError`
  statt still „erfolgreich" zu sein.
- **Kein veralteter Zustand mehr als „Erfolg":** Das Polling wartet auf „bereit"
  und wiederholt Abfragen, die die Box mit `errorcode` (z. B. 32 = busy)
  beantwortet. Vorher übernahm die Library den alten Wert und das Update galt
  als erfolgreich. Schlägt eine Abfrage komplett fehl, bleibt der letzte
  gültige Zustand bis zu 2 Polls lang stehen (Neuabfrage nach 5 s, Hinweis im
  Log); erst der 3. Fehlschlag in Folge macht die Entities `unavailable`. Die Box
  meldet während einer Fahrt mehrere Sekunden „busy" (Log 2026-10-09 08:38),
  das soll nicht als Ausfall erscheinen.
- **Robusteres Setup:** Ungültiges XML und `errorcode`-Antworten während der
  Discovery führen zu einem erneuten Verbindungsversuch statt zu einem
  dauerhaften Setup-Fehler.
- **Debug-Logging umfasst die Library:** `loggers: ["warema_wms"]` im Manifest,
  damit „Debug-Logging aktivieren" auch Requests/Responses an die Box zeigt.
- Fahrbefehle über das Cover melden eine nicht bestätigte Fahrt als Warnung im
  Log (bewusst kein Fehler, damit Wind-/Regen-Skripte nicht abbrechen).

## 0.3.1 – 2026-07-26

- **Preset-Buttons müssen nicht mehr doppelt gedrückt werden.** `send_raw`
  wertete die „check ready"-Antwort der Box nicht aus und sendete das
  Szenen-Kommando auch dann, wenn die Box gerade „nicht bereit" (`feedback=0`)
  meldete – die Box verwarf es dann still. Jetzt wird wie beim Fahren gewartet,
  bis die Box bereit ist, bevor das Kommando rausgeht.

## 0.3.0 – 2026-07-19

- **Neue Option „Kanäle ausschließen":** Kanalnamen (eine Zeile je Name) werden
  nach der Discovery herausgefiltert – so werden in der WMS gespeicherte Szenen,
  die die Box als eigene „Kanäle" mitliefert, nicht mehr als Cover/Sensor angelegt
  und auch nicht mehr gepollt (entrümpelt die Entitätenliste, beschleunigt das
  Polling).

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
