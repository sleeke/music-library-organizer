"""Tests for MusicBrainz artist lookup (Feature B).

query_musicbrainz_artist() resolves an artist MBID to the artist's real
name (aliases/artist credits) and returns cover-art info for their album
releases. Works from an MBID found in filename patterns or ID3 tags.

Testing approach: requests.get is mocked — no network. Rate-limit behavior
is verified by asserting the module-level sleep helper is invoked.
"""

import importlib.util
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = PROJECT_ROOT / 'update-mp3-metadata.py'

spec = importlib.util.spec_from_file_location('update_mp3_module', str(MODULE_PATH))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


ARTIST_PAYLOAD = {
    'id': 'mbid-123',
    'name': 'Stage Name',
    'sort-name': 'Name, Stage',
    'aliases': [
        {'name': 'Real Name', 'locale': 'en', 'type': 'Legal name'},
        {'name': 'The Other Band'},
    ],
}


class TestQueryMusicBrainzArtist:
    def test_returns_name_and_mbid(self, monkeypatch):
        seen = {}

        def fake_get(url, params=None, headers=None, timeout=None):
            seen['url'] = url
            seen['headers'] = headers
            return FakeResponse(ARTIST_PAYLOAD)

        monkeypatch.setattr(module.requests, 'get', fake_get)
        result = module.query_musicbrainz_artist('mbid-123')

        assert result['mb_artist_id'] == 'mbid-123'
        assert result['name'] == 'Stage Name'
        assert 'ws/2/artist/mbid-123' in seen['url']
        # MusicBrainz requires a descriptive User-Agent
        assert seen['headers']['User-Agent'].startswith('mp3-metadata-poc')

    def test_resolves_legal_name_alias(self, monkeypatch):
        monkeypatch.setattr(
            module.requests, 'get',
            lambda *a, **k: FakeResponse(ARTIST_PAYLOAD))
        result = module.query_musicbrainz_artist('mbid-123')
        assert result['real_name'] == 'Real Name'

    def test_real_name_none_when_no_legal_alias(self, monkeypatch):
        payload = {'id': 'x', 'name': 'Only Name', 'aliases': []}
        monkeypatch.setattr(
            module.requests, 'get', lambda *a, **k: FakeResponse(payload))
        result = module.query_musicbrainz_artist('x')
        assert result['real_name'] is None

    def test_http_error_returns_error_dict(self, monkeypatch):
        monkeypatch.setattr(
            module.requests, 'get',
            lambda *a, **k: FakeResponse({}, status=503))
        result = module.query_musicbrainz_artist('x')
        assert '_error' in result

    def test_connection_error_returns_error_dict(self, monkeypatch):
        def boom(*a, **k):
            raise module.requests.ConnectionError('no route')
        monkeypatch.setattr(module.requests, 'get', boom)
        result = module.query_musicbrainz_artist('x')
        assert '_error' in result

    def test_rate_limit_sleep_called(self, monkeypatch):
        sleeps = []
        monkeypatch.setattr(module.requests, 'get', lambda *a, **k: FakeResponse(ARTIST_PAYLOAD))
        monkeypatch.setattr(module.time, 'sleep', lambda s: sleeps.append(s))
        module.query_musicbrainz_artist('mbid-123')
        assert sleeps and sleeps[0] >= 1.0  # MB policy: 1 req/s


class TestMbidExtraction:
    def test_extract_mbid_from_tag(self):
        assert module.extract_mbid({'comment': ['MBID: mbid-123']}) == 'mbid-123'

    def test_no_mbid_returns_none(self):
        assert module.extract_mbid({}) is None

    def test_rejects_non_uuid(self):
        assert module.extract_mbid({'comment': ['not-a-uuid']}) is None
