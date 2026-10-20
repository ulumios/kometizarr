# Kometizarr – Konzept 2.0

Stand: Oktober 2026. Dieses Dokument beschreibt den Umbau, der Kometizarr einheitlicher,
nachvollziehbarer und wartbarer macht. Jeder Baustein wird als eigener Patch umgesetzt und
vor dem Commit getestet (`pytest tests`, `vite build`).

## Leitlinien

- **Ein Zustand pro Titel, an einer Stelle.** Kein Wissen mehr in Dateinamen, JSON-Dateien und
  mehreren Tabellen gleichzeitig.
- **Entscheiden und Ausführen trennen.** Was mit einem Titel passiert, ist eine reine Funktion
  ohne Plex-Zugriff; erst danach wird ausgeführt. Dadurch sind Vorschau, Tests und
  „nur bei Änderung rendern“ dieselbe Logik.
- **Alles läuft als Aufgabe in der Queue.** Manuelle Aktionen, Cron, Webhooks, Wartung –
  ein Worker, ein Fortschrittsmodell, eine Aufgabenliste im UI.
- **Kometa ist Nachbar, nicht Gegner.** Kometizarr erkennt Kometa-Overlays (`Overlay`-Label),
  übernimmt Titel sauber und nutzt Kometas gespeicherte Originale. Sammlungen und Metadaten
  bleiben in Kometizarr.
- **Nur intern betrieben.** Kein Login. Webhooks können optional per Token abgesichert werden,
  das funktioniert auch mit Sonarr/Radarr (Token als URL-Parameter).

## 1. Datenmodell: `item_state`

Neue Tabelle in der bestehenden SQLite-Datei `/backups/media_index.sqlite3`.

| Spalte | Bedeutung |
|---|---|
| `library`, `rating_key` | Primärschlüssel (Plex) |
| `type`, `title`, `year`, `series`, `season`, `episode` | Anzeige |
| `backup_id` | Ordnername des Backups (siehe 2.) |
| `original_source` | `agent`, `current`, `current_with_label`, `kometa`, `existing_backup`, `manual` |
| `original_hash` | SHA-256 des gesicherten Originals |
| `render_hash` | Hash aller Eingaben des letzten Renderns (siehe 4.) |
| `uploaded_thumb`, `uploaded_poster` | Plex-Thumb und Poster-Key direkt nach dem Upload (siehe 5.) |
| `status` | `rendered`, `original`, `failed`, `skipped` |
| `kometa_state` | `none`, `conflict`, `manual_pending` |
| `manual_identity` | Poster-Identität beim Entfernen des Labels (ersetzt `kometa_manual_pending.json`) |
| `reason`, `attempts`, `rendered_at`, `updated_at` | Diagnose, Wiederholung |

Ersetzt: Marker-Datei `poster_overlay.jpg` als „schon bearbeitet“, `kometa_manual_pending.json`,
Tabelle `origins`, Tabelle `conflicts`, Tabelle `applied` im IMDb-Cache.
Die alten Quellen werden einmalig übernommen (Migration beim Start, idempotent).

## 2. Backups nach ID

Neues Layout:

```
/backups/<Bibliothek>/<backup_id>/original.jpg
/backups/<Bibliothek>/<backup_id>/overlay.jpg
/backups/<Bibliothek>/<backup_id>/metadata.json
/backups/<Bibliothek>/<show_backup_id>/S01E02/original.jpg   (Episoden)
```

`backup_id` = IMDb-ID (`tt0133093`), sonst `tmdb-603`, sonst `tvdb-…`, sonst `plex-<ratingKey>`.
Episoden liegen im Ordner ihrer Serie, damit eine Serie ein Ordner bleibt.

Migration: eine Aufgabe „Backups migrieren“ liest jede Bibliothek aus Plex, berechnet alten und
neuen Pfad und verschiebt die Dateien (nie löschen, bei Konflikt überspringen und melden).
Bis zur Migration lesen alle Funktionen zusätzlich das alte Layout.

## 3. Einheitliches Fortschrittsmodell

Ein `RunProgress` pro aktiver Aufgabe:

```json
{"task_id": 12, "kind": "process", "library": "Filme", "phase": "Poster rendern",
 "done": 40, "total": 120, "success": 35, "failed": 2, "skipped": 3,
 "current": "Matrix (1999)", "results": {"<ratingKey>": {"status": "failed", "reason": "…"}}}
```

- Wird in der Task-Tabelle gespeichert (überlebt Neustart) und per WebSocket gesendet.
- `processing_state`, `restore_state`, `imdb_sync_state`, `conflict_state` entfallen.
- Bibliotheks-Scans lesen Plex nur und laufen neben dem Worker; sie erscheinen trotzdem in der Aufgabenliste.
- Die bisherigen Status-Endpunkte (`/api/status`, `/api/imdb-sync/status`, …) bleiben als Ansichten dieses Modells erhalten; neu ist `/api/progress`.
- Das Frontend liest nur noch `/api/tasks` bzw. den WebSocket.

## 4. Entscheidung, Änderungserkennung, Vorschau

```
sammle_eingaben(item)  -> RenderInputs   (Wertungen, Stil, Positionen, Badges, Original-Hash)
entscheide(state, inputs, optionen) -> Aktion
    render | skip_unchanged | skip_kometa_conflict | wait_manual | reset_then_render
    | reapply_lost | fail(grund)
fuehre_aus(aktion)
```

- `render_hash = sha256(RenderInputs + Renderer-Version)`.
- Normaler Lauf rendert nur, wenn sich der Hash geändert hat oder das Overlay verloren ging.
  Der „Force“-Lauf bleibt als Notfall erhalten.
- **Vorschau großer Läufe**: dieselbe Entscheidung ohne Ausführung → Zusammenfassung
  („120 neu, 34 Wertung geändert, 5 Kometa-Konflikte, 2 ohne ID“) und Start-Knopf.
- **Fehlgeschlagene wiederholen**: aus den Ergebnissen einer Aufgabe eine neue Aufgabe
  mit genau den fehlgeschlagenen Titeln.

## 5. Verlorene Overlays erkennen

Nach dem Upload werden `thumb` und Key des ausgewählten Posters gespeichert. Weicht beim
nächsten Lauf das Thumb ab, wird über `posters()` geprüft, ob noch unser Upload ausgewählt ist.

- Kometa-Label vorhanden → Kometa-Konflikt (bestehender Ablauf).
- Sonst (Plex hat Metadaten aufgefrischt oder Poster wurde manuell gewechselt) → Einstellung
  `lost_overlay`: `adopt` (neues Poster wird neues Original, dann rendern – Standard),
  `restore` (altes Original behalten, Overlay erneut hochladen) oder `report` (nur melden).

## 6. Kometa-Originale nutzen

Optionaler Mount des Kometa-Konfigordners, z. B. `/kometa`. Kometa legt Originale unter
`overlays/<Bibliothek> Original Posters/<ratingKey>.(jpg|png|webp)` ab.

- Bei einem Kometa-Konflikt wird zuerst dieses Original verwendet (`original_source=kometa`),
  erst danach das Plex-Agent-Poster.
- Bibliotheksnamen in Kometa können abweichen → Zuordnung in den Einstellungen.

## 7. Design pro Bibliothek

`settings.library_profiles[<Bibliothek>] = {badge_style, badge_positions, rating_sources, media_overlay}`.
Fehlende Werte fallen auf das globale Design zurück. Das Dashboard speichert das Design wahlweise
global oder für die ausgewählte Bibliothek. Der Profil-Inhalt geht in den `render_hash` ein, eine
Designänderung rendert also genau die betroffene Bibliothek neu.

## 8. Wartung

- **Backups**: Größe und Anzahl je Bibliothek, verwaiste Backups (Titel nicht mehr in Plex),
  Löschen verwaister Backups als Aufgabe mit Vorschau.
- **Alte Uploads in Plex**: Plex behält jedes hochgeladene Poster im Metadaten-Bundle.
  - Ohne Dateizugriff: „Bundles bereinigen“ und „Datenbank optimieren“ in Plex auslösen.
  - Mit optionalem Mount des Plex-Metadatenordners: nicht ausgewählte `upload://`-Poster eines
    Titels auflisten und nach Bestätigung löschen (immer zuerst Trockenlauf).

## 9. Statusseite

`/api/health` und eigener Reiter:
Plex (erreichbar, Version, Antwortzeit), TMDB/OMDb/MDBList (Key gültig), IMDb-Datensatz (Alter),
Speicherplatz `/backups`, Kometa-Mount, Plex-Metadaten-Mount, Queue (wartend/laufend/fehlgeschlagen),
nächste Cron-Läufe, letzte Webhook-Ereignisse.

## 10. Webhooks

- `/webhook/plex` (bestehend) und neu `/webhook/arr` für Sonarr/Radarr (JSON, Ereignis
  `Download`/`Import`). Titel wird über `library.getGuid('imdb://…')` gefunden. Ist er in Plex
  noch nicht da, wird die Aufgabe mit Verzögerung erneut versucht.
- Optionales Token `?token=…`, nur geprüft, wenn in den Einstellungen gesetzt.

## 11. Code-Struktur

```
src/services/   Geschäftslogik (settings, plex, progress, worker, overlay_run, restore, imdb, conflicts, maintenance, health)
src/rating_overlay/item_state.py   Zustandstabelle
web/backend/main.py                nur App, Router, Start
web/backend/routes/*.py            HTTP-Endpunkte
web/frontend/src/components/dashboard/*   Dashboard aufgeteilt
```

## Reihenfolge der Patches

| # | Patch | Abhängig von |
|---|---|---|
| 1 | Konzept (dieses Dokument) | – |
| 2 | `item_state` + Backups nach ID + Migration | 1 |
| 3 | Entscheidung/Ausführung trennen, Änderungs-Hash | 2 |
| 4 | Verlorene Overlays | 3 |
| 5 | Kometa-Originale | 2 |
| 6 | Einheitliches Fortschrittsmodell + Backend aufteilen | 3 |
| 7 | Vorschau großer Läufe, Fehlgeschlagene wiederholen | 3, 6 |
| 8 | Design pro Bibliothek | 3 |
| 9 | Wartung: Backups, verwaiste Backups, Plex-Uploads | 2 |
| 10 | Statusseite | 6 |
| 11 | Webhook-Token, Sonarr/Radarr | 6 |
| 12 | Dashboard aufteilen | 8 |

Backend aufteilen und Fortschrittsmodell laufen zusammen, weil beim Aufteilen ohnehin die
vier Status-Objekte angefasst werden müssten.

## Umsetzungsstand

Alle Patches 1–12 sind umgesetzt und mit `pytest tests` (66 Tests) sowie `vite build` geprüft.
Abweichungen vom Plan:

- Die Tabelle `conflicts` bleibt als Anzeige-Cache mit Serien-/Staffelzuordnung bestehen;
  `origins` und `kometa_manual_pending.json` sind in `item_state` aufgegangen.
- Der IMDb-Abgleich nutzt weiterhin seine Tabelle `applied`; der `render_hash` enthält die
  IMDb-Wertung zusätzlich.
- Nicht gegen einen echten Plex-Server getestet: Erkennung verlorener Overlays, Löschen alter
  Uploads im Metadatenordner, Sonarr/Radarr-Zuordnung. Diese Wege sind mit Tests und
  Sicherungen (Trockenlauf, Doppelprüfung, Plausibilitätsgrenzen) abgedeckt.

## Nachträge

- **Verbindungen im Webinterface**: Plex-URL, Plex-Token und die API-Keys (TMDB, OMDb, MDBList)
  lassen sich unter Settings → Verbindungen eintragen und testen. Gespeicherte Werte stehen in
  `settings.json` (`connections`) und gelten vor den Umgebungsvariablen. Schlüssel werden nie an
  das UI zurückgegeben (nur „gesetzt …1234“), Fehlermeldungen blenden sie aus.
- **Ein Speichern-Knopf**: Alle Einstellungen werden über die Leiste am Seitenende gespeichert;
  Aktionen (Scans, Zurücksetzen) haben weiter eigene Knöpfe.
- **Kometa-Nachfrage**: Läufe merken sich, welche Titel wegen Kometa übersprungen wurden
  (`kometa_keys`). Fortschrittsansicht, Aufgabenliste und Bibliotheksansicht bieten an, diese mit
  `reset_kometa` erneut zu starten; der IMDb-Lauf aus der Bibliotheksansicht fragt vorher.
- **Geplante Läufe** können Episoden mit bearbeiten (`include_episodes`).
- **Jeder Lauf ist ein Prüflauf**: Poster ohne Fingerabdruck werden einmal gerendert statt
  übernommen (`RENDERER_VERSION` 2 rendert einmal alles neu). Danach entsteht ein neues Overlay,
  sobald sich Wertung, Quelle, Serienstatus, Layout, Position oder Original ändern. Force lädt
  zusätzlich unveränderte Poster hoch und übernimmt Kometa-Poster ohne Nachfrage.
- **Ergebnisse je Titel**: Läufe speichern das Ergebnis jedes Titels (außer „unverändert“).
  Die Aufgabenliste zeigt die Einträge; ein Klick öffnet sie in der Bibliotheksansicht
  (gefiltert auf die Aufgabe, Serie → Staffel → Episode). Läufe aus der Bibliotheksansicht
  zeigen danach automatisch nur die betroffenen Titel.
