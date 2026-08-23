# Remaining Tasks Summary — `update-mp3-metadata.py` Enhancement Session

**Session Date:** 2026-08-23 (second session)
**Project:** `/Users/selwyn.leeke/Documents/DEV/mp3-metadata-poc`
**Branch:** `feat/web-app`

---

## ✅ Completed This Session

### 1. Utils Extraction Finished & Committed
- Removed the four duplicated local function definitions (`sanitize_filename`, `compute_checksum`, `scan_mp3_files`, `parse_filename`) that were shadowing the `core.utils` import in `update-mp3-metadata.py`.
- Full test suite green (24 tests at that point).
- Committed as `e23d39d` ("refactor: extract utils into core package; CLI imports from core").
- Follow-up commit `1af7ec3` removed accidentally committed `core/__pycache__`.

### 2. Feature A: Genre & BPM Extraction — DONE, Committed (`a9b5584`)
- Added to `update-mp3-metadata.py`: `normalize_genre_list()`, `extract_genre()`, `extract_bpm()`.
- Reads raw ID3 frames via `mutagen.id3.ID3` / `TCON` / `TBPM` (works regardless of EasyID3 key support).
- Handles numeric genres ("17", "(17)" — mutagen resolves to ID3v1 names), textual genres, multi-genre joined with `"; "`. BPM floats are rounded to int.
- Tests: `tests/test_genre_bpm.py` (12 tests).

### 3. Feature D: `--inspect` Tag Inspector — IMPLEMENTED & TESTED, **NOT YET COMMITTED**
Working tree contains (uncommitted):
- `update-mp3-metadata.py`: `INSPECT_FIELDS`, `MISSING_TAG`, `_first_frame_text()`, `inspect_mp3_tags()`, `format_inspect_table(rows, fmt='table'|'csv')`, `run_inspect(folder, fmt)`; CLI flags `--inspect` and `--csv` wired into `__main__` (read-only, exits after printing).
- `tests/test_inspect.py`: 7 tests covering frame reading, missing-frame `None`s, invalid-file handling, table + CSV formatting.
- Both new test files pass (19 tests across `test_genre_bpm.py` + `test_inspect.py`). End-to-end CLI smoke test of `--inspect` was started but interrupted — worth doing once before/after committing.

---

## 🔄 Immediate Next Step (New Session)

```bash
./venv/bin/python -m pytest -q          # full suite should be green (~31 tests)
git add update-mp3-metadata.py tests/test_inspect.py
git commit -m "feat: add --inspect ID3 tag audit subcommand (--csv for CSV output)"
# Optional smoke test:
mkdir -p /tmp/inspect-demo && ./venv/bin/python update-mp3-metadata.py --inspect /tmp/inspect-demo
```

> **Note:** `source venv/bin/activate && pytest` does NOT work on this machine (venv symlinks resolve to Homebrew Python which lacks pytest). Always invoke `./venv/bin/python -m pytest` directly.

---

## 📋 Remaining Features (in planned order)

### 1. Commit Feature D (see above)

### 2. Feature F: `--skip-fingerprint` Flag (was task #23)
- New CLI flag; when set, skip `query_acoustid()` entirely and go straight to text-based iTunes lookup.
- Default behavior unchanged when flag absent. Must compose with `--dry-run`.
- TDD: mock `query_acoustid` and assert it is never called when flag is passed through to `sync_metadata_and_rename()`.

### 3. Feature G: Logging & History (was task #24)
- `--history-dir <path>` option: store per-run change logs there in **JSONL** format (one change object per line).
- `--verbose` / `-v` flag for detailed progress output.
- Current `ChangeLogger.save()` writes a single JSON array to `changes_<timestamp>.json` — keep rollback compatibility while adding the JSONL path.

### 4. Feature E: Batch Mode `--batch` (was task #25)
- Process entire folder in one pass with progress counter output and an end-of-run summary (updated vs. skipped counts).
- Sequential processing acceptable for POC; if parallelizing API calls, respect rate limits (iTunes ~0.5s delay, MusicBrainz 1 req/s, Discogs similar).

### 5. Feature B: MusicBrainz Artist Lookup (was task #26)
- For artists with MBIDs in filename/tags, fetch artist credits from MB (`ws/2`).
- Resolve stage names → real names; detect cover art on album releases.
- Add `mb_artist_id` field to metadata results.
- Mock HTTP in tests; honor MB User-Agent + rate limit.

### 6. Feature C: Cover Art Fetch & Embed (was task #27)
- Query Discogs API for album artwork; download highest-res cover (~1MB cap).
- Embed into MP3 via ID3 `APIC` frame (note: session notes mentioned TPEV/USLT, but APIC is the correct picture frame).
- Handle multi-artist albums gracefully; network mocked in tests.

### 7. Documentation & Cleanup (was task #28)
- Update docstrings for all new functions; usage examples in argparse epilog.
- Consistent type hints throughout.
- Changelog comment block at top of `update-mp3-metadata.py`.
- Consider README update.

---

## 📝 Housekeeping / Notes

- **Untracked files** never committed: `STATUS.md`, `agent-output/`, `changes_20260216_211150.json`, root `__pycache__/`, `tests/__pycache__/`. Decide whether to gitignore or commit these.
- All new features must respect `--dry-run` (preview only, no writes).
- Existing behavior must not change when new flags are absent — current suite is the regression net.
- Public AcoustID test key `cSpUJKpD` is hardcoded in `query_acoustid()`; fine for POC.
- `feature_requirements.md` referenced by the original plan was never found in the repo — feature specs above come from the prior session summary.

---

*End of session summary.*
