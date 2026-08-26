# Review Suggestions

## #7 — iTunes lookup issues one API call per missing field

**Where:** `update-mp3-metadata.py:522-557` (loop `for key in ['artist', 'albumartist', 'album', 'title', 'tracknumber']`); `query_itunes_api` defined in `core/lookups.py:151`.

### What the code does now

For every field that is still missing after fingerprinting, the code calls `query_itunes_api`
separately — up to **5 HTTP requests per file**, each followed by `time.sleep(0.5)`.
Worse, each response only has its single `key` applied; the rest of that same response
(album, title, tracknumber…) is discarded and the loop re-queries for the next field.

### Why it's worth fixing

- **Throughput:** 5 requests × ~0.5s sleep ≈ 2.5s of pure waiting per file, vs ~0.5s for
  one batched call. Over a large library that is minutes → seconds.
- **API load / rate-limit risk:** 5× the traffic to `itunes.apple.com`, which increases
  the chance of throttling and makes the `time.sleep` rationale self-defeating.
- **Correctness oddity:** the iTunes Search API already returns a *complete* track record
  (`artistName`, `collectionName`, `trackName`, `trackNumber`) in a single response.
  Throwing that away and re-querying per field is both wasteful and harder to follow.

### Suggested fix

Query once, then apply every field the response contains:

```python
    # If still missing after fingerprinting, do ONE text-based iTunes lookup
    # for the whole track, then fill whatever fields it returned.
    def _clean(value):
        return None if value in (None, 'Unknown', '-', '', ' ') else value

    search_artist = _clean(audio.get('artist', [None])[0])
    search_title = _clean(audio.get('title', [None])[0])
    search_album = _clean(audio.get('album', [None])[0])

    if not search_artist and not search_title:
        print(f"Warning: Skipping online lookup for {os.path.basename(mp3_path)} - no artist or title to search")
    else:
        itunes_result = query_itunes_api(
            artist=search_artist,
            title=search_title,
            album=search_album,
        )
        if '_error' in itunes_result:
            print(f"Warning: iTunes lookup failed for {os.path.basename(mp3_path)}: {itunes_result['_error']}")
        else:
            for key in ['artist', 'albumartist', 'album', 'title', 'tracknumber']:
                current_value = audio.get(key, [None])[0]
                if key in itunes_result and itunes_result[key] and (
                    not current_value or current_value in ['Unknown', '-', '', ' ']
                ):
                    audio[key] = itunes_result[key]
                    changed = True
        time.sleep(0.5)  # Be respectful with API rate
```

### Trade-off to note

The old loop re-built its search terms each iteration as fields got filled (e.g. after
resolving `artist` it would search again with the new artist + title). The single-query
version does not. In practice this is negligible — `query_itunes_api` already asks for
`limit=1` and returns a full track, so the first response should carry every field we
need. If a case surfaces where a follow-up query genuinely helps, it can be added as a
second, conditional call rather than an unconditional 5× loop.

### Verification

`tests/test_sync.py` and `tests/test_folder_organization.py` exercise the rename/log
path but not the online lookup directly. Add a focused unit test that proves the fix
issues **one** call and fills **all** returned fields.

#### Plan for the unit test

Add to `tests/test_sync.py` (it already imports `module` via importlib and has an
`autouse` `patch_mp3` fixture that stubs `MP3`, `acoustid.match`, and
`query_itunes_api`).

```python
def test_itunes_lookup_fills_all_fields_from_one_call(tmp_path, monkeypatch):
    """A single iTunes response should populate every missing field at once.

    Guards against regression of #7: the per-field loop used to call
    query_itunes_api once per missing field. After the fix, exactly one
    call is made and all five fields from that one record are applied.
    """
    src = tmp_path / 'unknown.mp3'
    src.write_bytes(b'FAKE_MP3_DATA')

    # Start with no usable metadata; filename parsing yields nothing.
    monkeypatch.setattr(module, 'parse_filename', lambda path: {})

    # Capture call count + return a full track record (as the real API does).
    calls = []
    full_record = {
        'artist': 'Adele',
        'albumartist': 'Adele',
        'album': '21',
        'title': 'Rolling in the Deep',
        'tracknumber': '1',
    }

    def fake_itunes(**kwargs):
        calls.append(kwargs)
        return full_record

    monkeypatch.setattr(module, 'query_itunes_api', fake_itunes)

    logger = module.ChangeLogger(str(tmp_path / 'changes.json'))
    success = module.sync_metadata_and_rename(str(src), dry_run=False, logger=logger)
    assert success is True

    # Exactly ONE network call, not up to five.
    assert len(calls) == 1

    # All five fields filled from that single record.
    fake_audio = module.MP3(str(src), ID3=module.EasyID3)  # post-run tags
    assert fake_audio.get('artist', [None])[0] == 'Adele'
    assert fake_audio.get('albumartist', [None])[0] == 'Adele'
    assert fake_audio.get('album', [None])[0] == '21'
    assert fake_audio.get('title', [None])[0] == 'Rolling in the Deep'
    assert fake_audio.get('tracknumber', [None])[0] == '1'
```

**Notes on the harness (read before writing):**
- `patch_mp3` already stubs `query_itunes_api` with `{'_error': 'mocked'}`, so the
  `monkeypatch.setattr(module, 'query_itunes_api', fake_itunes)` above *overrides* it for
  just this test — good, that's what we want.
- The autouse fixture also forces `acoustid.match` to `[]`, so no fingerprinting runs and
  the loop falls straight through to the iTunes branch — exactly the path we're testing.
- `FakeAudio` in this file fakes `mutagen` (returns lists via `.get(key,[None])[0]` and
  supports `audio[key] = value`); the assertions read tags the same way
  `sync_metadata_and_rename` writes them, so no real MP3 is needed.
- **Skip the dry-run/checksum/logging assertions here** — this test is narrow on purpose:
  it asserts *call count + field population*. Preserve-content and rename-log behavior are
  already covered by `test_sync_metadata_and_rename_preserves_content_and_logs`.

**Optional second test (negative case):** patch `query_itunes_api` to return
`{'_error': 'HTTP 503'}` and assert that (a) it is still called exactly once and (b) the
missing fields end up as the `'not found'` sentinel rather than crashing — locking in the
"API failed, continue" behavior.
