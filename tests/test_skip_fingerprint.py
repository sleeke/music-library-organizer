"""Tests for the --skip-fingerprint flag (Feature F).

When skip_fingerprint is passed to sync_metadata_and_rename(), the AcoustID
fingerprint lookup must be skipped entirely and processing falls straight
through to the text-based iTunes lookup.

Testing approach: mock query_acoustid and query_itunes_api, assert
query_acoustid is never called with the flag set and still used without it.
The MP3 patch shares one FakeAudio per test so assertions can read back the
metadata sync_metadata_and_rename wrote (the file itself is a dummy byte blob).
"""

import importlib.util
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = PROJECT_ROOT / 'update-mp3-metadata.py'

spec = importlib.util.spec_from_file_location('update_mp3_module', str(MODULE_PATH))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeAudio:
    """Minimal EasyID3 stand-in: everything missing except what we seed."""

    def __init__(self, path, initial=None):
        self._meta = {} if initial is None else dict(initial)
        self.saved = False

    def get(self, key, default=None):
        if key in self._meta:
            return [self._meta.get(key)]
        return default if default is not None else [None]

    def __getitem__(self, key):
        return [self._meta.get(key)]

    def __setitem__(self, key, value):
        self._meta[key] = value

    def __contains__(self, key):
        return key in self._meta

    def save(self):
        self.saved = True


@pytest.fixture(autouse=True)
def patch_env(monkeypatch, tmp_path):
    """Patch MP3 loading and give each test a real (dummy) file to move.

    A single FakeAudio is shared per test: sync_metadata_and_rename loads its
    own instance at entry, so returning the same object for every path lets
    tests assert on the metadata that was written.
    """
    shared = {}

    def _fake_mp3(path, ID3=None):
        if 'audio' not in shared:
            shared['audio'] = FakeAudio(path)
        return shared['audio']

    mp3_file = tmp_path / 'Artist - Album - Song.mp3'
    mp3_file.write_bytes(b'FAKE_MP3_DATA')

    monkeypatch.setattr(module, 'MP3', _fake_mp3)
    yield


def _track_calls(monkeypatch, itunes_result):
    """Wire recording stubs over query_acoustid / query_itunes_api."""
    calls = {'acoustid': 0}

    def fake_acoustid(path, api_key=None):
        calls['acoustid'] += 1
        return {
            'artist': 'Fingerprint Artist',
            'albumartist': 'Fingerprint Artist',
            'album': 'Fingerprint Album',
            'title': 'Fingerprint Song',
            'tracknumber': '7',
            'confidence': 0.9,
        }

    def fake_itunes(*args, **kwargs):
        # Return whatever was asked-for fields; simple static result.
        return dict(itunes_result)

    monkeypatch.setattr(module, 'query_acoustid', fake_acoustid)
    monkeypatch.setattr(module, 'query_itunes_api', fake_itunes)
    return calls


class TestSkipFingerprint:
    def test_acoustid_not_called_when_flag_set(self, tmp_path, monkeypatch):
        src = tmp_path / 'Artist - Album - Song.mp3'
        calls = _track_calls(
            monkeypatch,
            {'artist': 'iTunes Artist', 'title': 'Song', 'album': 'Album'},
        )

        success = module.sync_metadata_and_rename(str(src), dry_run=True,
                                                  skip_fingerprint=True)
        assert success is True
        assert calls['acoustid'] == 0

    def test_acoustid_still_used_without_flag(self, tmp_path, monkeypatch):
        src = tmp_path / 'Artist - Album - Song.mp3'
        calls = _track_calls(monkeypatch, {'_error': 'not needed'})

        success = module.sync_metadata_and_rename(str(src), dry_run=True,
                                                  skip_fingerprint=False)
        assert success is True
        assert calls['acoustid'] == 1

    def test_falls_through_to_itunes_lookup(self, tmp_path, monkeypatch):
        """With fingerprinting skipped, iTunes fills fields neither tags nor
        filename provided (here: tracknumber)."""
        src = tmp_path / 'Artist - Album - Song.mp3'  # seeds artist/album/title
        holder = {}

        def fake_itunes(*args, **kwargs):
            holder['searched'] = kwargs
            return {'tracknumber': '3'}

        calls = {'acoustid': 0}
        monkeypatch.setattr(module, 'query_acoustid',
                            lambda p, api_key=None: calls.__setitem__('acoustid', calls['acoustid'] + 1) or {})
        monkeypatch.setattr(module, 'query_itunes_api', fake_itunes)

        success = module.sync_metadata_and_rename(str(src), dry_run=False,
                                                  skip_fingerprint=True)
        assert success is True
        assert calls['acoustid'] == 0          # fingerprinting skipped
        assert 'searched' in holder            # iTunes lookup happened
        assert holder['searched']['artist'] == 'Artist'  # seeded from filename
        assert holder['searched']['title'] == 'Song'
        audio = module.MP3(str(src))  # shared FakeAudio instance
        assert audio['tracknumber'][0] == '3'
        assert audio['album'][0] == 'Album'    # untouched by lookup

    def test_composes_with_dry_run(self, tmp_path, monkeypatch):
        """skip_fingerprint + dry-run must not write tags or move files."""
        src = tmp_path / 'Artist - Album - Song.mp3'
        before = src.read_bytes()
        _track_calls(
            monkeypatch,
            {'artist': 'iTunes Artist', 'albumartist': 'Album Artist',
             'album': 'Album', 'title': 'Song', 'tracknumber': '3'},
        )
        audio = module.MP3(str(src))

        success = module.sync_metadata_and_rename(str(src), dry_run=True,
                                                  skip_fingerprint=True)
        assert success is True
        assert src.exists()                       # not moved
        assert src.read_bytes() == before         # content untouched
        assert not (tmp_path / 'Artist').exists() # no folder structure created
