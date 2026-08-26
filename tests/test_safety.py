"""Tests for applying approved suggestions and trashing duplicates."""

import json
import os

import pytest

from core import safety
from core.changelog import ChangeLogger
from core.library_db import LibraryDB

FULL = {'artist': 'Art', 'albumartist': 'Art', 'album': 'Alb',
        'title': 'Song', 'tracknumber': '1'}


@pytest.fixture()
def db_and_logger(tmp_path):
    db = LibraryDB(str(tmp_path / 'lib.db'))
    logger = ChangeLogger(str(tmp_path / 'changes.json'))
    yield db, logger
    db.close()


@pytest.fixture()
def fake_fs(tmp_path, monkeypatch):
    """Real files on disk, but write_tags faked (content is not real MP3)."""
    written = {}

    def fake_write_tags(path, fields):
        written[path] = fields
        return True

    monkeypatch.setattr(safety, 'write_tags', fake_write_tags)
    return written


def seed(db, path, tags, suggestion_fields=None, status=None):
    db.upsert_file({'path': path, 'filename': path.split('/')[-1],
                    'size': 1, 'mtime': 1.0, 'checksum': 'c',
                    'duration': 1.0, 'bitrate': 1, **tags})
    if suggestion_fields is not None:
        fid = db.get_file(path)['id']
        db.replace_suggestion(fid, suggestion_fields, {'title': 'test'}, 0.9)
        sid = db.list_suggestions()[0]['id']
        if status:
            db.set_suggestion_status(sid, status)
        return sid


def test_default_log_path_has_timestamp_format(tmp_path):
    got = safety.default_log_path(str(tmp_path))
    assert got.startswith(str(tmp_path / 'changes_'))
    assert got.endswith('.json')


def test_apply_batch_writes_tags_moves_and_logs(tmp_path, db_and_logger, fake_fs):
    db, logger = db_and_logger
    mp3 = tmp_path / 'junk.mp3'
    mp3.write_bytes(b'data')
    sid = seed(db, str(mp3), dict(FULL, title=None, tracknumber=None),
               {'title': 'Real Name', 'tracknumber': '4'}, status='approved')
    summary = safety.apply_batch(db, logger)
    expected = tmp_path / 'Art' / 'Alb' / '04 - Real Name.mp3'
    assert len(summary['applied']) == 1
    assert expected.exists() and not mp3.exists()
    assert db.get_file(str(expected))['title'] == 'Real Name'
    assert db.get_suggestion(sid)['status'] == 'applied'
    entry = logger.changes[-1]
    assert entry['operation'] == 'metadata+rename'
    assert entry['new_path'] == str(expected)
    assert fake_fs[str(mp3)] == {'title': 'Real Name', 'tracknumber': '4'}
    assert (tmp_path / 'changes.json').exists()  # logger.save() ran


def test_apply_conflict_leaves_file_in_place(tmp_path, db_and_logger, fake_fs):
    db, logger = db_and_logger
    mp3 = tmp_path / 'junk.mp3'
    mp3.write_bytes(b'data')
    blocker = tmp_path / 'Art' / 'Alb' / '04 - Real Name.mp3'
    blocker.parent.mkdir(parents=True)
    blocker.write_bytes(b'other')
    sid = seed(db, str(mp3), dict(FULL, title=None, tracknumber=None),
               {'title': 'Real Name', 'tracknumber': '4'}, status='approved')
    summary = safety.apply_batch(db, logger)
    assert len(summary['conflicts']) == 1
    assert summary['conflicts'][0]['target'] == str(blocker)
    assert mp3.exists() and db.get_file(str(mp3)) is not None
    assert db.get_suggestion(sid)['status'] == 'approved'  # retryable after user acts


def test_pending_and_rejected_are_not_applied(tmp_path, db_and_logger, fake_fs):
    db, logger = db_and_logger
    mp3 = tmp_path / 'x.mp3'
    mp3.write_bytes(b'data')
    seed(db, str(mp3), FULL, {'title': 'Nope'}, status='rejected')
    summary = safety.apply_batch(db, logger)
    assert summary['applied'] == [] and summary['conflicts'] == []
    assert mp3.exists()


def test_missing_file_reported_as_error(tmp_path, db_and_logger, fake_fs):
    db, logger = db_and_logger
    seed(db, str(tmp_path / 'ghost.mp3'), FULL,
         {'title': 'X'}, status='approved')
    summary = safety.apply_batch(db, logger)
    assert len(summary['errors']) == 1
    assert 'missing' in summary['errors'][0]['error']


def test_tag_write_failure_reported_not_fatal(tmp_path, db_and_logger, monkeypatch):
    db, logger = db_and_logger
    mp3 = tmp_path / 'y.mp3'
    mp3.write_bytes(b'data')
    seed(db, str(mp3), dict(FULL, title=None), {'title': 'Z'}, status='approved')

    def failing_write(path, fields):
        return False

    monkeypatch.setattr(safety, 'write_tags', failing_write)
    summary = safety.apply_batch(db, logger)
    assert len(summary['errors']) == 1
    assert mp3.exists()  # no move attempted after failed tag write


def test_trash_files_moves_to_trash_and_updates_db(tmp_path, db_and_logger,
                                                   monkeypatch):
    db, logger = db_and_logger
    doomed = tmp_path / 'dup.mp3'
    doomed.write_bytes(b'data')
    seed(db, str(doomed), FULL)
    sent = []

    def fake_send2trash(path):
        sent.append(path)
        # Real send2trash removes the original; emulate that here.
        os.unlink(path)
        return '/FakeTrash/dup.mp3'

    monkeypatch.setattr(safety, 'send2trash', fake_send2trash)
    results = safety.trash_files(db, [str(doomed)], logger)
    assert results == [{'path': str(doomed), 'ok': True}]
    assert sent == [str(doomed)]
    assert not doomed.exists()
    assert db.get_file(str(doomed)) is None
    entry = logger.changes[-1]
    assert entry['operation'] == 'delete'
    assert entry['trash_destination'] == '/FakeTrash/dup.mp3'
    assert (tmp_path / 'changes.json').exists()


def test_trash_failure_reported_not_raised(tmp_path, db_and_logger, monkeypatch):
    db, logger = db_and_logger
    doomed = tmp_path / 'keep.mp3'
    doomed.write_bytes(b'data')
    seed(db, str(doomed), FULL)

    def boom(path):
        raise RuntimeError('locked')

    monkeypatch.setattr(safety, 'send2trash', boom)
    results = safety.trash_files(db, [str(doomed)], logger)
    assert results[0]['ok'] is False
    assert 'locked' in results[0]['error']
    assert doomed.exists()
    assert db.get_file(str(doomed)) is not None
