"""Unit tests for the SQLite library index."""

import json

import pytest

from core.library_db import LibraryDB


@pytest.fixture()
def db(tmp_path):
    database = LibraryDB(str(tmp_path / 'lib.db'))
    yield database
    database.close()


FILE_A = {
    'path': '/music/a.mp3', 'filename': 'a.mp3', 'size': 100, 'mtime': 1.0,
    'checksum': 'abc', 'duration': 180.0, 'bitrate': 128000,
    'artist': 'Artist', 'albumartist': 'Artist', 'album': 'Album',
    'title': 'Song A', 'tracknumber': '1',
}


def json_load(s):
    return json.loads(s)


def test_upsert_and_get_file(db):
    db.upsert_file(FILE_A)
    row = db.get_file('/music/a.mp3')
    assert isinstance(row, dict)
    assert row['title'] == 'Song A'
    assert row['filename'] == 'a.mp3'


def test_upsert_is_idempotent_on_path(db):
    db.upsert_file(dict(FILE_A))
    db.upsert_file(dict(FILE_A, title='Changed'))
    rows, total = db.list_files()
    assert total == 1
    assert db.get_file('/music/a.mp3')['title'] == 'Changed'


def test_mark_error_creates_error_row(db):
    db.mark_error('/music/bad.mp3', 'corrupt')
    assert db.get_file('/music/bad.mp3')['error'] == 'corrupt'


def test_prune_missing_removes_gone_files(db, tmp_path):
    live = tmp_path / 'live.mp3'
    live.write_bytes(b'x')
    db.upsert_file(dict(FILE_A, path=str(live)))
    db.upsert_file(dict(FILE_A, path=str(tmp_path / 'gone.mp3')))
    removed = db.prune_missing(str(tmp_path))
    assert removed == 1
    assert db.get_file(str(live)) is not None
    assert db.get_file(str(tmp_path / 'gone.mp3')) is None


def test_list_files_search_and_pagination(db):
    db.upsert_file(FILE_A)
    db.upsert_file(dict(FILE_A, path='/b.mp3', title='Zeppelin'))
    rows, total = db.list_files(q='zepp')
    assert total == 1 and rows[0]['title'] == 'Zeppelin'
    rows, total = db.list_files(limit=1)
    assert total == 2 and len(rows) == 1


def test_suggestion_lifecycle(db):
    db.upsert_file(FILE_A)
    fid = db.get_file('/music/a.mp3')['id']
    db.replace_suggestion(fid, {'title': 'Better'}, {'title': 'acoustid'}, 0.93)
    sug = db.list_suggestions(status='pending')[0]
    assert json_load(sug['fields_json']) == {'title': 'Better'}
    db.update_suggestion_fields(sug['id'], {'title': 'Edited'})
    assert json_load(db.get_suggestion(sug['id'])['fields_json']) == {'title': 'Edited'}
    db.set_suggestion_status(sug['id'], 'approved')
    assert db.list_suggestions(status='pending') == []
    assert db.list_suggestions(status='approved')[0]['status'] == 'approved'


def test_replace_suggestion_supersedes_pending(db):
    db.upsert_file(FILE_A)
    fid = db.get_file('/music/a.mp3')['id']
    db.replace_suggestion(fid, {'title': 'first'}, {}, None)
    db.replace_suggestion(fid, {'title': 'second'}, {}, None)
    pending = db.list_suggestions(status='pending')
    assert len(pending) == 1
    assert json_load(pending[0]['fields_json']) == {'title': 'second'}


def test_remove_file_cascades_suggestions(db):
    db.upsert_file(FILE_A)
    fid = db.get_file('/music/a.mp3')['id']
    db.replace_suggestion(fid, {'title': 'x'}, {}, None)
    db.remove_file('/music/a.mp3')
    assert db.get_file('/music/a.mp3') is None
    assert db.list_suggestions() == []


def test_dismissed_clusters(db):
    db.dismiss_cluster('key-1')
    db.dismiss_cluster('key-1')  # idempotent
    assert db.dismissed_keys() == {'key-1'}
