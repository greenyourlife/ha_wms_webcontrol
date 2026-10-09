# Roadmap bis 1.0

| Version | Inhalt | Status |
|---|---|---|
| 0.4.0 | Eigener async Protokoll-Client (Zähler 0–254, Busy-Resend, Ergebnis-Polling, Allowlist), Typ-Erkennung, Szenen automatisch als Buttons, Stopp, Winken, Volant | in Arbeit |
| 0.5.0 | Aktion `create_scene` (nur neu anlegen, nie löschen/überschreiben), Schalter Box-Automatik (Sonne/Dämmerung), Anzeige Sensor-Verfügbarkeit/Grenzwerte, Uhrzeit der Box stellen, Timer **lesen** (Sensor „nächste Schaltzeit“), Diagnose-Download, Repair-Hinweis bei unerreichbarer Box | geplant |
| 0.6.0 | Timer **schreiben** (`set_timer`, Read-Modify-Write mit Rücklese-Prüfung, kein Löschen), Schalter Zeitschaltuhr ein/aus | geplant |
| 1.0.0 | CI (hassfest, HACS-Validierung, Tests), README/Icon, optional HACS-Default-Store | geplant |

## Grundregeln

- Nie löschen: Räume, Kanäle, Szenen, Schaltzeiten nur über die Weboberfläche der Box.
- Nie überschreiben, was nicht in derselben Aktion neu angelegt wurde.
- Schreibende Telegramme werden einzeln in die Allowlist aufgenommen, jeweils mit Test gegen die echte Box und vorheriger SD-Sicherung.
