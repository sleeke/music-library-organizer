"""Tests for utility functions.

This module tests core utility functions that support the MP3 metadata script:
- sanitize_filename: Removes invalid filesystem characters
- parse_filename: Extracts metadata from filename patterns
- compute_checksum: Verifies file content integrity

Testing approach: Unit tests with direct function calls and temporary files.
"""

import importlib.util
import os
from pathlib import Path
import hashlib

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = PROJECT_ROOT / 'update-mp3-metadata.py'

spec = importlib.util.spec_from_file_location('update_mp3_module', str(MODULE_PATH))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_sanitize_and_parse_filename():
    """Test filename sanitization and metadata extraction.
    
    Verifies that:
    - Invalid filesystem characters are removed/replaced
    - Album artist, album, and title are correctly parsed from filenames
    - The standard 3-part format is recognized
    """
    s = 'Artist/Name: The? *Title*'
    sanitized = module.sanitize_filename(s)
    assert '/' not in sanitized
    assert ':' not in sanitized

    filename = 'Coldplay - Parachutes - Yellow.mp3'
    parsed = module.parse_filename(filename)
    assert parsed['albumartist'] == 'Coldplay'
    assert parsed['album'] == 'Parachutes'
    assert parsed['title'] == 'Yellow'


def test_compute_checksum(tmp_path):
    """Test SHA256 checksum computation for file integrity verification.
    
    Verifies that compute_checksum produces correct SHA256 hashes
    that can be used to verify file content hasn't changed during
    metadata updates or file moves.
    """
    p = tmp_path / 'file.bin'
    data = b'hello world\n'
    p.write_bytes(data)
    # compute hash independently
    expected = hashlib.sha256(data).hexdigest()
    got = module.compute_checksum(str(p))
    assert got == expected
