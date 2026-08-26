# MP3 Library Web App — Design

Date: 2026-08-22
Status: Approved design (brainstorming output)

## Goal

Augment the existing `update-mp3-metadata.py` CLI into a local web app with a UI that supports two workflows:

1. **Duplicate detection and cleanup** — detect duplicates by filename or metadata, review clusters, choose a keeper, send the rest to Trash.
2. **Metadata/filename correction** — review automatically generated suggestions (filename parse → AcoustID → iTunes) and apply approved ones.

The web app becomes the primary interface; the CLI remains functional as a thin wrapper over the same shared core.

## Decisions made during brainstorming

| Question | Decision |
|---|---|
| CLI future | Web app replaces it as primary; CLI kept working via refactor into shared core |
| Stack | FastAPI + single-page vanilla JS/CSS UI, no Node build step |
| Safety | Deletes go to Trash; all mutations logged to JSON change log |
| Suggestion flow | Review queue first — nothing applied without explicit approval |
| Duplicate matching | Filename + metadata + checksum only; no fingerprint pass |
| Library size | Large (10k+ files) → SQLite index, background jobs, pagination |
| Suggestion sources | Reuse AcoustID fingerprinting + iTunes API from existing code |

## Architecture

```
┌─────────────────────────────────────────────┐
│  Web UI (single page, vanilla JS + CSS)     │
│  • Library browser  • Duplicate picker      │
│  • Suggestion review queue                  │
└──────────────┬──────────────────────────────┘
               │ JSON over HTTP
┌──────────────▼──────────────────────────────┐
│  FastAPI app (one process, port 8000)       │
│  • /api/scan  /api/library  /api/duplicates │
│  • /api/suggestions  /api/apply  /api/trash │
├─────────────────────────────────────────────┤
│  Core library (refactored from the CLI)     │
│  • scanner.py   • suggester.py              │
│  • duplicates.py  • library_db.py           │
│  • safety.py (trash + change log)           │
├─────────────────────────────────────────────┤
│  SQLite index (library.db)                  │
└─────────────────────────────────────────────┘
```

- One process: `python app.py` starts FastAPI serving both API and static UI.
- SQLite caches path/tags/checksum per file; scans are incremental (only new/changed files re-read and re-suggested).
- Scan/suggest runs as a background job; UI polls `/api/jobs/{id}` for progress. No websockets.
- Core logic refactored out of `update-mp3-metadata.py` (`scan_mp3_files`, `parse_filename`, `sanitize_filename`, `query_acoustid`, `query_itunes_api`, `ChangeLogger`, `compute_checksum`) into importable modules under `core/`. The CLI becomes a thin wrapper; existing tests keep passing with minimal import-path changes.

## Duplicate detection

Three passes over the SQLite index; groups merge into duplicate **clusters**:

1. **Metadata match**: normalized `(artist, title)` and `(albumartist, album, tracknumber)`. Normalization = lowercase, strip accents/punctuation, drop suffixes like "(radio edit)" / "feat. …".
2. **Filename match**: normalized filename stem within same parent folder.
3. **Checksum match**: identical SHA256 content regardless of name/tags.

A file may appear in multiple groups; merged so each cluster holds all copies of one song.

**UI:** Duplicates page lists clusters with per-copy bitrate/filesize/duration/path and an audio `<audio>` preview. User picks a keeper and deletes the rest → Trash via `send2trash`. Every cluster also has an explicit **Keep all / dismiss** action; dismissed clusters remain visible (grayed, filterable). No auto-delete ever.

Deletions append to the change log in the existing JSON format, extended with `"operation": "delete"` entries recording the trash destination.

## Suggestion review queue

**Generation** ("Scan & suggest" from Library page): background job walks the incremental index; for files whose tags are missing/invalid (empty, `Unknown`, `-`, `not found`, digit-only artist/title — same rules as the CLI), runs filename parse → AcoustID → iTunes fallback. Results stored as suggestion rows `{file, field → proposed value, source (acoustid/itunes/filename), confidence}`. Nothing is written to files at generation time. Files that cannot be identified simply get no suggestions (the CLI's "not found" stamping behavior is dropped).

**Review:** queue page shows one card per file: current vs proposed tags side by side, confidence, audio preview. Per-card actions: Approve, Edit fields inline then approve, Reject. Bulk: approve-all-filtered, reject-all.

**Apply:** approved suggestions applied in one batch: mutagen writes tags, then file renamed/moved into `Artist/Album/NN - Title.mp3` with existing sanitize/rename logic, logged to change log (old/new metadata + old/new path) so CLI `--rollback` works on web-app batches too.

## Safety

- Deletes → macOS Trash (`send2trash`); log entry records trash location.
- Single `core/safety.py` funnels every mutation (tag write, rename/move, delete) into the existing `changes_*.json` format.
- Renames refuse to overwrite: target exists → file left in place, conflict surfaced in UI.
- Server binds `127.0.0.1` only.

## Error handling

- Corrupt MP3s: error state on index row, shown in UI, scan continues.
- API failures/rate limits: job continues; no suggestion generated for that pass.
- Single user; actions operate on explicit IDs.

## Testing

- Existing tests keep passing (imports adjusted for refactor).
- New pytest coverage: duplicate grouping (pure functions on synthetic rows), suggestion state machine (pending→approved/rejected/applied), safety logging incl. delete entries, rename-conflict behavior.
- UI stays thin (fetch + render); no test harness for it.

## Non-goals

- Audio-fingerprint-based duplicate matching.
- Auto-applying confident suggestions.
- Permanent deletion or emptying Trash.
- Multi-user/auth support; network exposure beyond localhost.
