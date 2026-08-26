"""Tests for metadata sync and file renaming operations.

This module tests the core sync_metadata_and_rename function which:
- Fills missing metadata from filenames
- Updates MP3 ID3 tags
- Organizes files into folder structures
- Logs changes for rollback capability

Testing approach: Integration-style tests with mocked MP3 library (mutagen),
mocked API calls (AcoustID, iTunes), and temporary file system operations.

Key features tested:
- Content preservation (checksum verification)
- Metadata extraction and updates
- Folder organization
- Change logging for rollback
"""

import importlib.util
import os
from pathlib import Path
import json

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = PROJECT_ROOT / 'update-mp3-metadata.py'

spec = importlib.util.spec_from_file_location('update_mp3_module', str(MODULE_PATH))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeAudio:
    def __init__(self, path, initial=None):
        self._path = path
        self._meta = {} if initial is None else dict(initial)

    def get(self, key, default=None):
        # mimic mutagen returning lists
        if key in self._meta:
            return [self._meta.get(key)]
        if default is not None:
            return default
        return [None]

    def __getitem__(self, key):
        # support audio['artist'] style access returning a list
        return [self._meta.get(key)]

    def __setitem__(self, key, value):
        # allow setting a value (string)
        self._meta[key] = value

    def __contains__(self, key):
        return key in self._meta

    def save(self):
        # no-op for fake
        return


@pytest.fixture(autouse=True)
def patch_mp3(monkeypatch, tmp_path):
    # Patch module.MP3 to return our FakeAudio
    def _fake_mp3(path, ID3=None):
        return FakeAudio(path)

    monkeypatch.setattr(module, 'MP3', _fake_mp3)
    # Patch acoustid.match to return empty generator
    monkeypatch.setattr(module.acoustid, 'match', lambda *a, **k: [])
    # Patch iTunes API to return empty results
    monkeypatch.setattr(module, 'query_itunes_api', lambda *a, **k: {'_error': 'mocked'})
    yield


def test_sync_metadata_and_rename_preserves_content_and_logs(tmp_path, monkeypatch):
    """Test that file content is preserved and changes are logged.
    
    Verifies the complete sync workflow:
    - File content (checksum) unchanged after processing
    - File moved to correct folder structure
    - Changes logged for rollback capability
    - Metadata applied from parsed filename
    """
    # Create a fake mp3 file (content is arbitrary bytes) with a generic name
    src = tmp_path / 'track01.mp3'
    src.write_bytes(b'FAKE_MP3_DATA')

    # Compute checksum before
    before = module.compute_checksum(str(src))

    # Prepare logger
    log_file = tmp_path / 'changes.json'
    logger = module.ChangeLogger(str(log_file))

    # Ensure filename parsing will return usable metadata for this test
    monkeypatch.setattr(module, 'parse_filename', lambda path: {'albumartist': 'Artist', 'album': 'Album', 'title': 'Song'})

    # Run sync (not dry-run)
    success = module.sync_metadata_and_rename(str(src), dry_run=False, logger=logger)
    assert success is True

    # Find renamed file in folder structure Artist/Album/Artist - Album - Title.mp3
    expected_path = tmp_path / 'Artist' / 'Album' / 'Artist - Album - Song.mp3'
    assert expected_path.exists()

    # Check checksum unchanged
    after = module.compute_checksum(str(expected_path))
    assert before == after

    # Logger should have one change
    assert len(logger.changes) == 1
    change = logger.changes[0]
    assert change['original_path'].endswith('track01.mp3')
    assert 'Artist' in change['new_path']
    assert 'Album' in change['new_path']
    assert 'Artist - Album - Song.mp3' in change['new_path']

    # Save and load log to confirm valid JSON
    logger.save()
    data = json.loads(log_file.read_text())
    assert isinstance(data, list)
    assert data[0]['original_path']


def test_itunes_lookup_fills_all_fields_from_one_call(tmp_path, monkeypatch):
    """A single iTunes response should populate every missing field at once.

    Guards against regression of review suggestion #7: the per-field loop used
    to call query_itunes_api once per missing field. After the fix, exactly one
    call is made and all five fields from that one record are applied.
    """
    src = tmp_path / 'unknown.mp3'
    src.write_bytes(b'FAKE_MP3_DATA')

    # Start with no usable metadata; filename parsing yields nothing. Seed a
    # title so the lookup has something to search with, and cache the
    # FakeAudio per path so post-run tag reads see the same object the sync
    # wrote to (the autouse fixture otherwise returns a fresh empty fake).
    monkeypatch.setattr(module, 'parse_filename', lambda path: {})
    store = {}

    def cached_mp3(path, ID3=None):
        key = str(path)
        if key not in store:
            store[key] = FakeAudio(key, initial={'title': 'Some Song'})
        return store[key]

    monkeypatch.setattr(module, 'MP3', cached_mp3)

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
        return dict(full_record)

    monkeypatch.setattr(module, 'query_itunes_api', fake_itunes)

    logger = module.ChangeLogger(str(tmp_path / 'changes.json'))
    success = module.sync_metadata_and_rename(str(src), dry_run=False, logger=logger)
    assert success is True

    # Exactly ONE network call, not up to five.
    assert len(calls) == 1

    # Every field that was missing is filled from that single record;
    # the pre-existing (searchable) title is preserved, not clobbered.
    fake_audio = module.MP3(str(src), ID3=module.EasyID3)  # post-run tags
    assert fake_audio.get('artist', [None])[0] == 'Adele'
    assert fake_audio.get('albumartist', [None])[0] == 'Adele'
    assert fake_audio.get('album', [None])[0] == '21'
    assert fake_audio.get('tracknumber', [None])[0] == '1'
    assert fake_audio.get('title', [None])[0] == 'Some Song'


def test_itunes_api_error_continues_without_crash(tmp_path, monkeypatch):
    """When the iTunes API fails, the file is still processed gracefully.

    The lookup must run exactly once, the remaining fields end up as the
    'not found' sentinel, and sync still reports success.
    """
    src = tmp_path / 'unknown2.mp3'
    src.write_bytes(b'FAKE_MP3_DATA')

    # Same harness as above: cached FakeAudio seeded with a searchable title.
    monkeypatch.setattr(module, 'parse_filename', lambda path: {})
    store = {}

    def cached_mp3(path, ID3=None):
        key = str(path)
        if key not in store:
            store[key] = FakeAudio(key, initial={'title': 'Some Song'})
        return store[key]

    monkeypatch.setattr(module, 'MP3', cached_mp3)

    calls = []

    def failing_itunes(**kwargs):
        calls.append(kwargs)
        return {'_error': 'HTTP 503'}

    monkeypatch.setattr(module, 'query_itunes_api', failing_itunes)

    logger = module.ChangeLogger(str(tmp_path / 'changes.json'))
    success = module.sync_metadata_and_rename(str(src), dry_run=False, logger=logger)
    assert success is True

    assert len(calls) == 1  # attempted exactly once, no retry storm

    fake_audio = module.MP3(str(src), ID3=module.EasyID3)
    # Fields the failed lookup was meant to fill end up as the sentinel;
    # the seeded title survives untouched.
    for key in ('artist', 'albumartist', 'album'):
        assert fake_audio.get(key, [None])[0] == 'not found'
    assert fake_audio.get('title', [None])[0] == 'Some Song'
