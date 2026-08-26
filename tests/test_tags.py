"""Tests for tag reading/writing helpers (mutagen mocked)."""

import pytest

from core import tags


class FakeInfo:
    length = 123.5
    bitrate = 192000


class FakeAudio:
    """Mimics mutagen's MP3(EasyID3) enough for read/write helpers."""

    instances = {}

    def __init__(self, path, ID3=None):
        self.info = FakeInfo()
        if path not in FakeAudio.instances:
            FakeAudio.instances[path] = {'artist': ['Real Artist'], 'title': ['Real Title']}
        self._meta = FakeAudio.instances[path]
        self.saved = {}

    def get(self, key, default=None):
        return self._meta.get(key, default if default is not None else [None])

    def __setitem__(self, key, value):
        self.saved[key] = value

    def save(self):
        self._meta.update(self.saved)


@pytest.fixture()
def fake_mp3(monkeypatch):
    FakeAudio.instances = {}
    monkeypatch.setattr(tags, 'MP3', FakeAudio)
    return FakeAudio


def test_read_tags_returns_all_five_keys(fake_mp3):
    got = tags.read_tags('/fake/a.mp3')
    assert set(got.keys()) == set(tags.TAG_KEYS)
    assert got['artist'] == 'Real Artist'
    assert got['album'] is None


def test_read_tags_returns_none_on_error(monkeypatch):
    def boom(path, ID3=None):
        raise RuntimeError('bad file')
    monkeypatch.setattr(tags, 'MP3', boom)
    assert tags.read_tags('/fake/bad.mp3') is None


def test_read_audio_info(fake_mp3):
    duration, bitrate = tags.read_audio_info('/fake/a.mp3')
    assert duration == 123.5
    assert bitrate == 192000


def test_write_tags_sets_only_given_fields(fake_mp3):
    assert tags.write_tags('/fake/a.mp3', {'album': 'New Album'}) is True
    probe = FakeAudio('/fake/a.mp3')  # same backing store => saved value visible
    assert probe._meta['album'] == 'New Album'
    assert probe._meta['title'] == ['Real Title']  # untouched field


def test_write_tags_ignores_unknown_keys_and_none_values(fake_mp3):
    assert tags.write_tags('/fake/a.mp3', {'bogus': 'x', 'title': None}) is True
    probe = FakeAudio('/fake/a.mp3')
    assert 'bogus' not in probe.saved
    assert 'title' not in probe.saved


def test_write_tags_returns_false_on_error(monkeypatch):
    class Boom(FakeAudio):
        def save(self):
            raise RuntimeError('disk full')
    monkeypatch.setattr(tags, 'MP3', Boom)
    assert tags.write_tags('/fake/x.mp3', {'album': 'x'}) is False
