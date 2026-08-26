"""Tests for the incremental folder scanner (tag reading mocked)."""

import pytest

from core import scanner
from core.library_db import LibraryDB


@pytest.fixture()
def db(tmp_path):
    database = LibraryDB(str(tmp_path / 'lib.db'))
    yield database
    database.close()


DEFAULT_TAGS = {'artist': 'Art', 'albumartist': 'Art', 'album': 'Alb',
                'title': 'T', 'tracknumber': '1'}


def fake_read_tags(path):
    return DEFAULT_TAGS


FAKE_AUDIO_INFO = (123.0, 320000)


@pytest.fixture(autouse=True)
def patch_read_tags(monkeypatch):
    monkeypatch.setattr(scanner, 'read_tags', fake_read_tags)
    monkeypatch.setattr(scanner, 'read_audio_info',
                        lambda p: FAKE_AUDIO_INFO)


def _make_tree(tmp_path, names=('a.mp3', 'b.mp3')):
    for n in names:
        (tmp_path / n).write_bytes(b'ID3DATA' + n.encode())


def _make_tree(tmp_path, names=('a.mp3', 'b.mp3')):
    for n in names:
        (tmp_path / n).write_bytes(b'ID3DATA' + n.encode())


def test_scan_populates_index(tmp_path, db):
    _make_tree(tmp_path)
    stats = scanner.scan_folder(db, str(tmp_path))
    assert stats['total'] == 2
    assert stats['updated'] == 2
    assert stats['errors'] == 0
    files = db.all_files()
    assert {f['filename'] for f in files} == {'a.mp3', 'b.mp3'}
    assert all(f['checksum'] for f in files)


def test_second_scan_is_incremental(tmp_path, db):
    _make_tree(tmp_path)
    scanner.scan_folder(db, str(tmp_path))
    stats = scanner.scan_folder(db, str(tmp_path))
    assert stats['unchanged'] == 2 and stats['updated'] == 0


def test_changed_mtime_rescans(tmp_path, db):
    import os
    _make_tree(tmp_path, names=('a.mp3',))
    scanner.scan_folder(db, str(tmp_path))
    os.utime(tmp_path / 'a.mp3', (1000, 1000))
    stats = scanner.scan_folder(db, str(tmp_path))
    assert stats['updated'] >= 1


def test_invalid_mp3_recorded_as_error(tmp_path, db, monkeypatch):
    (tmp_path / 'bad.mp3').write_bytes(b'whatever')
    monkeypatch.setattr(scanner, 'read_tags', lambda p: None)
    stats = scanner.scan_folder(db, str(tmp_path))
    assert stats['errors'] == 1
    assert db.get_file(str(tmp_path / 'bad.mp3'))['error']


def test_prunes_rows_deleted_from_disk(tmp_path, db):
    gone = tmp_path / 'gone.mp3'
    gone.write_bytes(b'x')
    scanner.scan_folder(db, str(tmp_path))
    gone.unlink()
    stats = scanner.scan_folder(db, str(tmp_path))
    assert stats['removed'] == 1
    assert db.get_file(str(gone)) is None


def test_new_root_resets_library(tmp_path, db):
    lib1 = tmp_path / 'lib1'
    lib2 = tmp_path / 'lib2'
    lib1.mkdir(); lib2.mkdir()
    (lib1 / 'x.mp3').write_bytes(b'a')
    (lib2 / 'y.mp3').write_bytes(b'b')
    scanner.scan_folder(db, str(lib1))
    scanner.scan_folder(db, str(lib2))
    assert {f['path'] for f in db.all_files()} == {str(lib2 / 'y.mp3')}


def test_progress_callback_reports_totals(tmp_path, db):
    _make_tree(tmp_path)
    seen = []
    scanner.scan_folder(db, str(tmp_path),
                        progress_cb=lambda d, t, phase: seen.append((d, t, phase)))
    assert seen[-1][0] == seen[-1][1] == 2
    assert {phase for _, _, phase in seen} == {'scan'}


def test_scan_records_duration_and_bitrate(tmp_path, db):
    _make_tree(tmp_path)
    scanner.scan_folder(db, str(tmp_path))
    for f in db.all_files():
        assert f['duration'] == FAKE_AUDIO_INFO[0]
        assert f['bitrate'] == FAKE_AUDIO_INFO[1]


def test_scan_refreshes_rows_missing_duration_or_bitrate(tmp_path, db):
    # Simulate a legacy row written before duration/bitrate were captured.
    _make_tree(tmp_path, names=('a.mp3',))
    db.upsert_file({'path': str(tmp_path / 'a.mp3'), 'filename': 'a.mp3',
                    'size': (tmp_path / 'a.mp3').stat().st_size,
                    'mtime': (tmp_path / 'a.mp3').stat().st_mtime,
                    'duration': None, 'bitrate': None, **DEFAULT_TAGS})
    stats = scanner.scan_folder(db, str(tmp_path))
    assert stats['updated'] == 1 and stats['unchanged'] == 0
    row = db.get_file(str(tmp_path / 'a.mp3'))
    assert row['duration'] == FAKE_AUDIO_INFO[0]
    assert row['bitrate'] == FAKE_AUDIO_INFO[1]
