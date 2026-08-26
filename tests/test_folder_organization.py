"""Tests for folder organization feature.

This module tests the hierarchical folder structure creation:
<Artist>/<Album>/Artist - Album - <Track Number> - <Track Name>.mp3

Features tested:
- Directory creation (Artist/Album/ hierarchy)
- File moving to correct locations
- Track number formatting (zero-padding to 2 digits)
- Files without track numbers (fallback to Artist - Album - Title)
- Content preservation during folder moves (checksum verification)
- Change logging for folder moves
- Dry-run mode (preview without creating folders)
- Special character sanitization in folder names
- Track number parsing from filenames

Testing approach: Integration tests with mocked MP3 library and APIs,
using temporary file systems to verify folder structure and file placement.
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


def test_folder_structure_created(tmp_path, monkeypatch):
    """Test that Artist/Album/ folder structure is created."""
    # Create a fake mp3 file
    src = tmp_path / 'track01.mp3'
    src.write_bytes(b'FAKE_MP3_DATA')

    # Mock parse_filename to return usable metadata
    monkeypatch.setattr(module, 'parse_filename', lambda path: {
        'albumartist': 'Coldplay',
        'album': 'Parachutes',
        'title': 'Yellow',
        'tracknumber': '1'
    })

    # Run sync
    success = module.sync_metadata_and_rename(str(src), dry_run=False, logger=None)
    assert success is True

    # Verify folder structure created
    artist_dir = tmp_path / 'Coldplay'
    album_dir = artist_dir / 'Parachutes'
    assert artist_dir.exists()
    assert album_dir.exists()
    assert album_dir.is_dir()


def test_file_moved_to_correct_location(tmp_path, monkeypatch):
    """Test that file is moved to Artist/Album/Artist - Album - Track - Title.mp3."""
    src = tmp_path / 'unknown.mp3'
    src.write_bytes(b'FAKE_MP3_DATA')

    monkeypatch.setattr(module, 'parse_filename', lambda path: {
        'albumartist': 'The Beatles',
        'album': 'Abbey Road',
        'title': 'Come Together',
        'tracknumber': '1'
    })

    success = module.sync_metadata_and_rename(str(src), dry_run=False, logger=None)
    assert success is True

    # Verify file at new location
    expected_path = tmp_path / 'The Beatles' / 'Abbey Road' / 'The Beatles - Abbey Road - 01 - Come Together.mp3'
    assert expected_path.exists()
    assert not src.exists()  # Original file should be moved


def test_track_number_padded(tmp_path, monkeypatch):
    """Test that track numbers are zero-padded to 2 digits."""
    src = tmp_path / 'song.mp3'
    src.write_bytes(b'FAKE_MP3_DATA')

    monkeypatch.setattr(module, 'parse_filename', lambda path: {
        'albumartist': 'Artist',
        'album': 'Album',
        'title': 'Song',
        'tracknumber': '3'
    })

    success = module.sync_metadata_and_rename(str(src), dry_run=False, logger=None)
    assert success is True

    expected_path = tmp_path / 'Artist' / 'Album' / 'Artist - Album - 03 - Song.mp3'
    assert expected_path.exists()


def test_no_track_number_still_works(tmp_path, monkeypatch):
    """Test that files without track numbers still get organized."""
    src = tmp_path / 'song.mp3'
    src.write_bytes(b'FAKE_MP3_DATA')

    monkeypatch.setattr(module, 'parse_filename', lambda path: {
        'albumartist': 'Artist',
        'album': 'Album',
        'title': 'Song Title'
    })

    success = module.sync_metadata_and_rename(str(src), dry_run=False, logger=None)
    assert success is True

    # Without track number, filename is Artist - Album - Title
    expected_path = tmp_path / 'Artist' / 'Album' / 'Artist - Album - Song Title.mp3'
    assert expected_path.exists()


def test_checksum_preserved_across_folder_move(tmp_path, monkeypatch):
    """Test that file content is unchanged after moving to folder structure."""
    src = tmp_path / 'track.mp3'
    content = b'FAKE_MP3_DATA_WITH_AUDIO'
    src.write_bytes(content)

    # Compute checksum before
    before = module.compute_checksum(str(src))

    monkeypatch.setattr(module, 'parse_filename', lambda path: {
        'albumartist': 'Artist',
        'album': 'Album',
        'title': 'Track',
        'tracknumber': '5'
    })

    success = module.sync_metadata_and_rename(str(src), dry_run=False, logger=None)
    assert success is True

    # Find new location and verify checksum
    new_path = tmp_path / 'Artist' / 'Album' / 'Artist - Album - 05 - Track.mp3'
    assert new_path.exists()
    
    after = module.compute_checksum(str(new_path))
    assert before == after


def test_logger_records_folder_move(tmp_path, monkeypatch):
    """Test that ChangeLogger records the new folder path."""
    src = tmp_path / 'song.mp3'
    src.write_bytes(b'FAKE_MP3_DATA')

    log_file = tmp_path / 'changes.json'
    logger = module.ChangeLogger(str(log_file))

    monkeypatch.setattr(module, 'parse_filename', lambda path: {
        'albumartist': 'Artist',
        'album': 'Album',
        'title': 'Song',
        'tracknumber': '7'
    })

    success = module.sync_metadata_and_rename(str(src), dry_run=False, logger=logger)
    assert success is True

    assert len(logger.changes) == 1
    change = logger.changes[0]
    
    # Verify original and new paths recorded
    assert change['original_path'].endswith('song.mp3')
    assert 'Artist' in change['new_path']
    assert 'Album' in change['new_path']
    assert 'Artist - Album - 07 - Song.mp3' in change['new_path']


def test_dry_run_does_not_create_folders(tmp_path, monkeypatch):
    """Test that dry-run mode doesn't create folders or move files."""
    src = tmp_path / 'song.mp3'
    src.write_bytes(b'FAKE_MP3_DATA')

    monkeypatch.setattr(module, 'parse_filename', lambda path: {
        'albumartist': 'Artist',
        'album': 'Album',
        'title': 'Song',
        'tracknumber': '1'
    })

    success = module.sync_metadata_and_rename(str(src), dry_run=True, logger=None)
    assert success is True

    # Verify folders not created
    artist_dir = tmp_path / 'Artist'
    assert not artist_dir.exists()
    
    # Original file should still exist
    assert src.exists()


def test_special_characters_sanitized_in_folders(tmp_path, monkeypatch):
    """Test that special characters in artist/album names are sanitized."""
    src = tmp_path / 'song.mp3'
    src.write_bytes(b'FAKE_MP3_DATA')

    monkeypatch.setattr(module, 'parse_filename', lambda path: {
        'albumartist': 'AC/DC',
        'album': 'Back in Black: Special Edition',
        'title': 'Hells Bells',
        'tracknumber': '1'
    })

    success = module.sync_metadata_and_rename(str(src), dry_run=False, logger=None)
    assert success is True

    # Verify sanitized folder names
    artist_dir = tmp_path / 'AC_DC'
    album_dir = artist_dir / 'Back in Black - Special Edition'
    assert artist_dir.exists()
    assert album_dir.exists()


def test_parse_filename_recognizes_track_numbers(tmp_path):
    """Test that parse_filename extracts track numbers correctly."""
    # Full output format: "Artist - Album - NN - Title.mp3"
    result = module.parse_filename('/path/to/Coldplay - Parachutes - 05 - Yellow.mp3')
    assert result['albumartist'] == 'Coldplay'
    assert result['album'] == 'Parachutes'
    assert result['tracknumber'] == '05'
    assert result['title'] == 'Yellow'

    # Track number format: "01 - Song Title.mp3"
    result = module.parse_filename('/path/to/01 - Yellow.mp3')
    assert result['tracknumber'] == '01'
    assert result['title'] == 'Yellow'

    # Single digit
    result = module.parse_filename('/path/to/5 - Something.mp3')
    assert result['tracknumber'] == '5'
    assert result['title'] == 'Something'

    # Three digits
    result = module.parse_filename('/path/to/125 - Track.mp3')
    assert result['tracknumber'] == '125'

    # Old format still works
    result = module.parse_filename('/path/to/Artist - Album - Song.mp3')
    assert result['albumartist'] == 'Artist'
    assert result['album'] == 'Album'
    assert result['title'] == 'Song'
