# Diff Review Notes
> Branch: `sandbox/feat/web-app` vs `origin/main`  
> Reviewer session: 2026-08-23

---

## Open changes to make

### [2] Filename format — include full context
**Decision:** Use `Artist - Album - NN - Title.mp3` (self-describing, portable) rather than the current `NN - Title.mp3` (folder-dependent).

**Rationale discussed:**
- Current format loses album and artist context if files are ever moved out of the folder hierarchy (USB copy, flat import, cloud sync).
- `Album - NN - Title.mp3` sorts better than `NN - Album - Title.mp3` when flattened (albums cluster together), but neither is a recognised convention.
- `Artist - Album - NN - Title.mp3` is the most portable and self-describing. It's also the closest to the old `import os.py` format (`Artist - Album - Title.mp3`), adding only the track number.

**Files to change:**
- `update-mp3-metadata.py:856-862` — the `new_name` construction in `sync_metadata_and_rename`
- `core/utils.py:82-99` — `parse_filename` currently handles ≤3 parts; a 4-part `Artist - Album - NN - Title` split will need a new branch (first part non-numeric = albumartist, second = album, third = track number if numeric, fourth = title).
- Tests in `tests/test_folder_organization.py` and `tests/test_utils.py` will need updating to match the new format.

---

### [4] AcoustID API key hard-coded in source
**Decision:** `api_key = 'cSpUJKpD'` is embedded directly in `query_acoustid`. Comment says "replace with your own for production" but there is no mechanism to do so without editing source.

**Notes:**
- `cSpUJKpD` is AcoustID's public demo key — not a secret, but shared and rate-limited. Real load will be throttled.
- Inconsistent with how `DISCOGS_TOKEN` is handled in the same diff (CLI arg + env var fallback at `update-mp3-metadata.py:1000`).

**Files to change:**
- `update-mp3-metadata.py:558` — replace hardcoded string with `os.environ.get('ACOUSTID_KEY', 'cSpUJKpD')`.
- `update-mp3-metadata.py` argparse block — add optional `--acoustid-key` CLI arg (mirrors `--discogs-token`), passed into `query_acoustid`.
- Update `query_acoustid` signature to accept `api_key` as a parameter rather than reading it from a closure.

---

## Decisions accepted as-is

- **[1] `albumartist` as folder organiser** — correct; keeps compilation albums together.
- **[7] `core/` package extraction** — no objection.
- **[9] `importlib` test loading** — consequence of hyphenated filename; acceptable as-is. Optional improvement: centralise the `spec_from_file_location` call in `conftest.py` to eliminate the 5-line boilerplate duplicated across all 10 test files. Longer-term option: rename script to `update_mp3_metadata.py` and use a normal `import`.

---

## Decisions not reviewed in this session

- **[3] `"not found"` sentinel written into ID3 tags**
- **[8] `parse_filename` yields `albumartist` not `artist`**
- **[10] Discogs token via CLI arg (visible in `ps` output)**
- The 50% AcoustID confidence threshold

---

## Minor / future extensions

### [5] Dual JSON/JSONL changelog — rough edges
Design intent is sound (array for `--rollback`, JSONL for grep/tail). Three minor issues:

1. **Double extension:** JSONL is named `changes_TIMESTAMP.json.jsonl` (appending `.jsonl` to the array filename). Consider `changes_TIMESTAMP.jsonl` as a sibling instead.
2. **Append mode is almost always a no-op:** JSONL is opened with `'a'` but the timestamp in the filename means each run creates a fresh file anyway. The only case where append accumulates is `--log` with a fixed path — where the JSON array is *overwritten* each run while the JSONL *grows*. Inconsistent.
3. **JSONL path logic is duplicated:** `save_jsonl` recomputes the target path independently of `resolve_log_path`, creating a second place to update if naming conventions change.

### [6] Cover art — extend beyond Discogs (future feature)
Current implementation (`--fetch-cover` via Discogs) is a reasonable starting point and correctly opt-in so default behaviour is unchanged. Recommended extensions for a future iteration:

- **Additional sources:** Last.fm and MusicBrainz Cover Art Archive are free/open alternatives that don't require a personal token; could fall back across sources in priority order.
- **Format detection:** current code always embeds as `image/jpeg` regardless of what Discogs actually returns. A PNG source would be mislabelled.
- **Idempotency:** re-running with `--fetch-cover` always re-fetches; could check whether an APIC frame already exists before hitting the network.
- **Size floor:** there's a 1 MB cap (`MAX_IMAGE_BYTES`) to avoid large scans, but no minimum — a 1×1 placeholder image would pass. A minimum dimension check would help.

---

## Recommendations summary

### Block merge on
1. **[2] Filename format** — change `new_name` to `Artist - Album - NN - Title.mp3`; update `parse_filename` to handle 4-part splits; update affected tests.
2. **[4] AcoustID key** — read from `ACOUSTID_KEY` env var / `--acoustid-key` CLI arg; pass as parameter into `query_acoustid`; keep demo key as fallback default.

### Before next feature work
3. **[9] Test boilerplate** — centralise `importlib` module load in `conftest.py`, or rename script to `update_mp3_metadata.py`.

### Future iterations
4. **[6] Cover art** — multi-source fallback (MusicBrainz CAA, Last.fm), MIME type detection, idempotency check, minimum dimension floor.
5. **[5] JSONL naming** — clean up double extension and document `--log` fixed-path behaviour.

### Not reviewed — carry forward
- [3] `"not found"` sentinel in ID3 tags
- [8] `parse_filename` `albumartist` vs `artist` mapping
- [10] Discogs token CLI arg exposure
- AcoustID 50% confidence threshold
