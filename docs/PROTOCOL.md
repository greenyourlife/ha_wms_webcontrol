# WMS WebControl (Basic) – Protokoll

Quelle: JavaScript der Weboberfläche der Box (`script/WebControl.js`,
`WebControlKonfigurieren.js`, `WebControlBedienen.js`), ausgelesen am
2026-10-09, plus eigene Log-Mitschnitte. Keine offizielle WAREMA-Dokumentation.

## Transport

`GET http://<box>/protocol.xml?protocol=<HEX>&_=<timestamp>` → XML-Antwort.

`<HEX>` = Header (3 Byte) + Payload:

| Byte | Inhalt |
|---|---|
| 0 | `0x90` (BEFEHLSCODE 144) |
| 1 | Befehlszähler. Offizielle UI: startet bei 0, zählt bis 254, danach 1. **255 wird nie gesendet.** |
| 2 | Payload-Länge (max. 32) |
| 3+ | Payload, Byte 0 = Telegramm-ID |

Texte (Raum-/Kanal-/Szenennamen) werden als Zeichencodes byteweise an die
Payload angehängt, max. 20 Zeichen.

## Telegramme (Request-ID → Response-ID = Request + 1)

| ID | Name | Payload nach ID | Schreibt? |
|---|---|---|---|
| 0x01 | RAUM_ANLEGEN | raum, name… | ja |
| 0x03 | RAUM_ABFRAGEN | raum | nein |
| 0x05 | RAUMNAMEN_AENDERN | raum, name… | ja |
| 0x07 | RAUMREIHENFOLGE_AENDERN | src, dest | ja |
| 0x09 | RAUM_LOESCHEN | raum | **ja, destruktiv** |
| 0x0B | KANAL_ANLEGEN | raum, kanal, szene, name… | ja |
| 0x0D | KANAL_ABFRAGEN | raum, kanal | nein |
| 0x0F | KANALNAMEN_AENDERN | raum, kanal, name… | ja |
| 0x11 | KANALREIHENFOLGE_AENDERN | … | ja |
| 0x13 | KANAL_LOESCHEN | raum, kanal | **ja, destruktiv** |
| 0x15 / 0x17 | RAUM_KOPIEREN / KANAL_IN_RAUM_KOPIEREN | … | ja |
| 0x19 | AKTOREN_ZUWEISEN | raum_dest, kanal_dest, aktiv, raum_src, kanal_src | ja |
| 0x1B | INFRASTRUKTUR_SPEICHERN (SD) | … | SD-Karte |
| 0x1D | INFRASTRUKTUR_LADEN (SD) | … | **ja, überschreibt Projekt** |
| 0x1F | DEF_INFRASTRUKTUR_SPEICHERN | … | ja |
| 0x21 | KANALBEDIENUNG | raum, kanal, fc, arg1..arg4 | Bedienung |
| 0x23 | POS_RUECKMELDUNG (Motor aufwecken / Position anfordern) | raum, kanal | nein |
| 0x25 | WINKEN | raum, kanal | Bedienung |
| 0x27 / 0x29 | PASSWORT_ABFRAGE / _AENDERN | … | ja |
| 0x2B | AUTOMATIK | on_off (global) | Einstellung |
| 0x2D | GRENZWERTE lesen | raum, kanal | nein |
| 0x2F | RTC | read_write, senden, tag, monat, jahr%100, h, m, s | Uhrzeit |
| 0x31 | POLLING | raum, kanal, befehl (s. u.) | nein |
| 0x3D | SPRACHE | … | Einstellung |
| 0x3F | SET_GRENZWERTE | raum, kanal, wind, regen, sonne, dämmerung (0–9) | Einstellung |
| 0x45 | SZENE_ANLEGEN | raum, kanal(frei), szene_idx(0–31), name… | ja |
| 0x47 | KANAL_SZENE_ABFRAGEN | raum, kanal | nein |
| 0x49 / 0x4B | Menütabellen lesen | … | nein |
| 0x4D / 0x4F | WMS-Parameter lesen / schreiben | … | 0x4F ja |
| 0x51–0x65 | WMS-Index/Parameter, Schaltzeitpunkte | … | teils ja |
| 0x67 | KOMFORT (Komfortposition) | raum, kanal, befehl | Bedienung |

Sonder-Responses: `51` = WMS_STACK_BUSY (`feedback` 1 = angenommen,
0 = Stack belegt → Befehl verworfen), `52` = ERROR_MESSAGE (`errorcode`).

## Funktionscodes für KANALBEDIENUNG (0x21)

| FC | Bedeutung | Argumente |
|---|---|---|
| 1 | Stopp | FF FF FF FF |
| 2 | Sollwert direkt | pos·2, winkel, volant1, volant2 |
| 3 | Sollwert sicher (von UI für Fahrten genutzt) | pos·2 (0–200), winkel, volant1, volant2, FF = ignorieren |
| 4 / 5 | Impuls Wenden hoch/tief | |
| 6 / 7 | Hoch / Tief | |
| 8 | **Szene ausführen** (auf Szenen-Kanal) | FF FF FF FF |
| 9 | **Szene lernen** – Aktoren speichern ihre aktuelle Position | FF FF FF FF |
| 10–22 | Licht/Last, Volant-Einzelfahrten | |
| 23–34 | Tastenemulation (kurz/lang/doppelt) | |
| 41–43 | Winken (gesamt / Volant L / R) | |

## POLLING (0x31) – Befehlstypen

0 Kanalbedienung · 1 Position · 2 Grenzwerte · 3 Aktoren zuweisen ·
4 Automatik · 5 Winken · 6 Set Grenzwerte · 7/8 Menütabellen ·
9/10 WMS-Parameter · 11 Komfort

Antwort `responseID 50` mit `feedback 0` = Ergebnis liegt noch nicht vor,
weiter pollen. Sonst kommt die eigentliche Response (z. B. 36 mit
`fahrt`/`position`, 34 für Kanalbedienung, 26 für Aktoren zuweisen).

## Fehlercodes (responseID 52)

8 max. Szenen · 10 max. Kanäle · 13 SD-Karte · **32 Polling-Befehl ungültig**
(Poll ohne passenden offenen Auftrag) · 33 Polling-Kanal · 35 Projektdatei ·
41 Bereichsindex · 42 Inhalt ungültig · 43 PAN-ID ungültig

## Grenzen

20 Räume × 10 Kanäle (200), 32 Szenen, Namen max. 20 Zeichen,
Position 0–100 % (Protokoll 0–200), Winkel −80…80.

## Kanal-/Produkttypen (`produkttyp` aus 0x47)

0 Raffstore · 1 Jalousie innen · 2 Rollladen · 3 Markise · 4 Markise 1 Volant ·
5 Markise int. Wind · 6 Markise 1 Volant int. Wind · 7 Wintergarten-Markise ·
8 Fassadenmarkise · 9 Fallarmmarkise · 10 Senkrechtmarkise · 11 Markisolette ·
12 Faltstore innen · 13 Rollo innen · 14 Vertikal-Jalousie innen · 15 Fenster ·
16 Licht schalten · 17 Last schalten · 18 Licht dimmen · 19 Last dimmen ·
20 Steckdose · 21 Volant · 22 Markise 2 Volant · 23 Markise 2 Volant int. Wind ·
24 Sonnensegel · 25 Pergolamarkise · 26 LED-Dimmer

`szeneindex` 255 = Produkt (Aktor), 0–31 = Szenen-Kanal.

## Ablauf „Szene anlegen“ in der offiziellen UI

1. Freien Kanal im Raum suchen (max. 10).
2. `SZENE_ANLEGEN(raum, freier_kanal, szene_idx, name)`.
3. Für jeden ausgewählten Aktor `AKTOREN_ZUWEISEN(raum, szenenkanal, 0, raum_src, kanal_src)`, Ergebnis per `POLLING(…, 3)`.
4. Positionen anfahren, dann auf dem Szenen-Kanal `KANALBEDIENUNG(raum, szenenkanal, 9, FF, FF, FF, FF)` („Szene lernen“).

## Zeitschaltuhr (Schaltzeitpunkte, SZP)

Die Schaltzeiten liegen **im Aktor (Motor-Empfänger)**, nicht in der Box. Die
Box liest/schreibt sie per Funk als WMS-Parameter. Sie laufen daher auch, wenn
Box oder HA ausfallen.

### Datenblock pro Kanal (199 Werte)

| Index | Inhalt |
|---|---|
| 0 | unbekannt (beobachtet: 54) – beim Schreiben unverändert übernehmen |
| 1 | Zeitschaltuhr ein/aus (1 = ein) |
| 2 | unbekannt (beobachtet: 1) – unverändert übernehmen |
| 3 + Tag·28 + Zp·7 + n | Tag 0–6 = Mo–So, Zp 0–3 (4 Schaltzeiten pro Tag), n: 0 Stunde, 1 Minute, 2 Position, 3 Winkel, 4 Volant 1, 5 Volant 2, 6 Freigabe |

255 = ungenutzt. Freigabe: beobachtet 1 bei aktiver Schaltzeit, 2 bei leerem
Platz. Position in Library-Semantik (Markise: 0 = eingefahren).

Übertragen wird in 10 Bereichen à 22 Werte (`bereichindex` 0–9).

### Lesen

1. `0x4D LESE_WMS_PARAMETER(raum, kanal)` → `51 feedback 1`
2. `0x31 POLLING(raum, kanal, 9)` bis Ergebnis: `50 feedback 0` = läuft noch,
   `50 feedback 2` = Fehler (Aktor antwortet nicht – beim ersten Versuch am
   2026-10-09 passiert, zweiter Versuch ok), `78` = fertig
3. `0x63 GET_WMS_PARAMETER_ZSP(raum, kanal, bereich)` für Bereich 0–9 →
   Response `100` mit `parameter` = kommagetrennte Werte

### Schreiben (offizielle UI)

1. `0x65 SET_WMS_PARAMETER_ZSP(raum, kanal, bereich, 22 Werte)` für Bereich 0–9
   (immer der **komplette** Block)
2. `0x4F SCHREIBE_WMS_PARAMETER(raum, kanal)`
3. `0x31 POLLING(raum, kanal, 10)` bis Ergebnis

### Beobachteter Stand 2026-10-09 (Balkon/Markise)

Zeitschaltuhr ein; Mo–So jeweils 18:30 → Position 0 (einfahren); übrige
Schaltzeiten leer.
