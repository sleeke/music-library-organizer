"""Tests for the suggestion engine (online lookups mocked)."""

import json

import pytest

from core import suggester
from core.library_db import LibraryDB

FULL_TAGS = {'artist': 'A', 'albumartist': 'A', 'album': 'L',
             'title': 'T', 'tracknumber': '1'}


@pytest.fixture(autouse=True)
def no_lookups(monkeypatch):
    monkeypatch.setattr(suggester, 'query_acoustid', lambda p: {})
    monkeypatch.setattr(suggester, 'query_itunes_api', lambda **kw: {'_error': 'mocked'})


def test_complete_tags_need_nothing():
    assert suggester.needs_suggestion(FULL_TAGS) is False


def test_missing_title_needs_suggestion():
    assert suggester.needs_suggestion(dict(FULL_TAGS, title=None)) is True


def test_unknown_and_digit_only_are_invalid():
    assert suggester.needs_suggestion(dict(FULL_TAGS, artist='Unknown')) is True
    assert suggester.needs_suggestion(dict(FULL_TAGS, title='12')) is True


def test_not_found_stamp_is_invalid():
    assert suggester.needs_suggestion(dict(FULL_TAGS, album='not found')) is True


def test_blank_and_dash_are_invalid():
    assert suggester.needs_suggestion(dict(FULL_TAGS, album='   ')) is True
    assert suggester.needs_suggestion(dict(FULL_TAGS, album='-')) is True


def test_filename_fills_missing_fields(monkeypatch, tmp_path):
    p = tmp_path / 'Cool Band - Great Hit.mp3'
    monkeypatch.setattr(suggester, 'query_acoustid', lambda p_: {'_error': 'disabled'})
    fields, sources, conf = suggester.generate_for_file(
        str(p), dict(FULL_TAGS, artist=None, albumartist=None, title=None))
    assert fields['title'] == 'Great Hit'
    assert sources['title'] == 'filename'
    assert conf is None


def test_acoustid_fills_after_filename(monkeypatch, tmp_path):
    p = tmp_path / 'junk.mp3'
    monkeypatch.setattr(suggester, 'query_acoustid', lambda p_: {
        'artist': 'Finger Artist', 'albumartist': 'Finger Artist',
        'album': 'Finger Album', 'title': 'Finger Title',
        'tracknumber': '5', 'confidence': 0.91})
    # tracknumber must be unset too — a valid existing tag is never overwritten
    fields, sources, conf = suggester.generate_for_file(
        str(p), dict(FULL_TAGS, artist=None, albumartist=None,
                     album=None, title=None, tracknumber=None))
    assert fields['artist'] == 'Finger Artist'
    assert sources['artist'] == 'acoustid'
    assert conf == 0.91
    assert fields['tracknumber'] == '5'
    assert sources['tracknumber'] == 'acoustid'


def test_valid_fields_never_overwritten(monkeypatch, tmp_path):
    p = tmp_path / '01 - Known Song.mp3'
    monkeypatch.setattr(suggester, 'query_acoustid', lambda p_: {
        'artist': 'Wrong', 'albumartist': 'Wrong', 'album': 'Wrong',
        'title': 'Wrong', 'tracknumber': '99', 'confidence': 0.99})
    fields, sources, conf = suggester.generate_for_file(str(p), dict(FULL_TAGS))
    assert fields == {} and sources == {} and conf is None


def test_itunes_fallback_used_when_acoustid_empty(monkeypatch, tmp_path):
    p = tmp_path / 'Some Artist - Some Song.mp3'

    def fake_itunes(**kw):
        return {'artist': 'IT Artist', 'albumartist': 'IT Artist',
                'album': 'IT Album', 'title': 'IT Title', 'tracknumber': '2'}

    monkeypatch.setattr(suggester, 'query_itunes_api', fake_itunes)
    monkeypatch.setattr(suggester, 'query_acoustid', lambda p_: {'_error': 'off'})
    fields, sources, conf = suggester.generate_for_file(
        str(p), dict(FULL_TAGS, album=None))
    assert fields['album'] == 'IT Album'
    assert sources['album'] == 'itunes'
    assert conf is None


def test_run_suggest_pass_stores_pending_suggestions(tmp_path):
    db = LibraryDB(str(tmp_path / 'lib.db'))
    try:
        mp3 = tmp_path / 'Band - Song.mp3'
        db.upsert_file({'path': str(mp3), 'filename': 'Band - Song.mp3',
                        'size': 1, 'mtime': 1.0, 'checksum': 'c',
                        'duration': 1.0, 'bitrate': 1,
                        'artist': None, 'albumartist': None, 'album': None,
                        'title': None, 'tracknumber': None})
        stats = suggester.run_suggest_pass(db)
        assert stats['considered'] == 1 and stats['suggested'] == 1
        pending = db.list_suggestions(status='pending')
        assert len(pending) == 1
        assert json.loads(pending[0]['fields_json'])['title'] == 'Song'
    finally:
        db.close()


def test_run_suggest_pass_skips_error_rows(tmp_path):
    db = LibraryDB(str(tmp_path / 'lib.db'))
    try:
        db.mark_error('/gone/broken.mp3', 'corrupt')
        stats = suggester.run_suggest_pass(db)
        assert stats == {'considered': 0, 'suggested': 0}
    finally:
        db.close()
