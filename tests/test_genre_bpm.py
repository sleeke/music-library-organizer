"""Tests for genre & BPM extraction from ID3 tags (Feature A).

These functions read TCON (genre) and TBPM (BPM) frames directly via
mutagen ID3, so they work regardless of EasyID3 key registration.

Testing approach: unit tests against real mutagen ID3 tags written to
temporary files, plus pure-function tests for normalization helpers.
"""

import importlib.util
import os
from pathlib import Path

import pytest
from mutagen.id3 import ID3, TCON, TBPM

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = PROJECT_ROOT / 'update-mp3-metadata.py'

spec = importlib.util.spec_from_file_location('update_mp3_module', str(MODULE_PATH))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def _make_tag_file(tmp_path, name, frames):
    """Create a standalone ID3 tag file with the given frames."""
    tag = ID3()
    for frame in frames:
        tag.add(frame)
    path = tmp_path / name
    tag.save(str(path))
    return str(path)


class TestExtractGenre:
    def test_textual_genre(self, tmp_path):
        path = _make_tag_file(tmp_path, 'a.tags', [TCON(encoding=3, text=['Drum & Bass'])])
        assert module.extract_genre(path) == 'Drum & Bass'

    def test_numeric_genre_resolved_to_name(self, tmp_path):
        # ID3v1 numeric reference 17 == Rock; mutagen resolves it
        path = _make_tag_file(tmp_path, 'b.tags', [TCON(encoding=3, text=['17'])])
        assert module.extract_genre(path) == 'Rock'

    def test_parenthesized_numeric_genre(self, tmp_path):
        path = _make_tag_file(tmp_path, 'c.tags', [TCON(encoding=3, text=['(13)'])])
        assert module.extract_genre(path) == 'Pop'

    def test_multiple_genres_joined(self, tmp_path):
        path = _make_tag_file(tmp_path, 'd.tags', [TCON(encoding=3, text=['Rock', 'Pop'])])
        result = module.extract_genre(path)
        assert 'Rock' in result and 'Pop' in result

    def test_missing_frame_returns_none(self, tmp_path):
        path = _make_tag_file(tmp_path, 'e.tags', [])
        assert module.extract_genre(path) is None


class TestExtractBpm:
    def test_integer_bpm(self, tmp_path):
        path = _make_tag_file(tmp_path, 'f.tags', [TBPM(encoding=3, text=['128'])])
        assert module.extract_bpm(path) == 128

    def test_float_bpm_rounded(self, tmp_path):
        path = _make_tag_file(tmp_path, 'g.tags', [TBPM(encoding=3, text=['128.5'])])
        assert module.extract_bpm(path) == 128

    def test_missing_frame_returns_none(self, tmp_path):
        path = _make_tag_file(tmp_path, 'h.tags', [])
        assert module.extract_bpm(path) is None

    def test_non_numeric_bpm_returns_none(self, tmp_path):
        path = _make_tag_file(tmp_path, 'i.tags', [TBPM(encoding=3, text=['fast'])])
        assert module.extract_bpm(path) is None


class TestNormalizeGenreList:
    def test_deduplicates_repeated_values(self):
        assert module.normalize_genre_list(['Rock', 'Rock']) == ['Rock']

    def test_preserves_order(self):
        assert module.normalize_genre_list(['Pop', 'Rock']) == ['Pop', 'Rock']

    def test_empty_list(self):
        assert module.normalize_genre_list([]) == []
