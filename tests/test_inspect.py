"""Tests for the --inspect tag inspector (Feature D).

inspect_mp3_tags() reads raw ID3 frames from a file and returns a dict of
the audited fields; format_inspect_table() renders a CSV-style table with
'---' placeholders for missing frames.

Testing approach: real mutagen ID3 tags written to temporary files, plus
pure-function tests over the table formatter.
"""

import importlib.util
from pathlib import Path

import pytest
from mutagen.id3 import ID3, TIT2, TPE1, TPE2, TDRC, TRCK, TCON, TBPM, TCOM

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = PROJECT_ROOT / 'update-mp3-metadata.py'

spec = importlib.util.spec_from_file_location('update_mp3_module', str(MODULE_PATH))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def _make_tag_file(tmp_path, name, frames):
    tag = ID3()
    for frame in frames:
        tag.add(frame)
    path = tmp_path / name
    tag.save(str(path))
    return str(path)


class TestInspectMp3Tags:
    def test_reads_present_frames(self, tmp_path):
        path = _make_tag_file(tmp_path, 'a.tags', [
            TIT2(encoding=3, text=['Yellow']),
            TPE1(encoding=3, text=['Coldplay']),
            TPE2(encoding=3, text=['Coldplay']),
            TDRC(encoding=3, text=['2000']),
            TRCK(encoding=3, text=['3/10']),
            TCON(encoding=3, text=['Rock']),
            TBPM(encoding=3, text=['128']),
            TCOM(encoding=3, text=['C. Martin']),
        ])
        result = module.inspect_mp3_tags(path)
        assert result['TIT2'] == 'Yellow'
        assert result['TPE1'] == 'Coldplay'
        assert result['TPE2'] == 'Coldplay'
        assert result['TDRC'] == '2000'
        assert result['TRCK'] == '3/10'
        assert result['TCON'] == 'Rock'
        assert result['TBPM'] == '128'
        assert result['TCOM'] == 'C. Martin'

    def test_missing_frames_are_none(self, tmp_path):
        path = _make_tag_file(tmp_path, 'b.tags', [TIT2(encoding=3, text=['Title Only'])])
        result = module.inspect_mp3_tags(path)
        assert result['TIT2'] == 'Title Only'
        assert result['TPE1'] is None
        assert result['TPE2'] is None
        assert result['TDRC'] is None
        assert result['TRCK'] is None
        assert result['TCON'] is None
        assert result['TBPM'] is None
        assert result['TCOM'] is None

    def test_all_expected_fields_present(self, tmp_path):
        path = _make_tag_file(tmp_path, 'c.tags', [])
        result = module.inspect_mp3_tags(path)
        assert set(result.keys()) == {'TIT2', 'TPE1', 'TPE2', 'TDRC', 'TRCK', 'TCON', 'TBPM', 'TCOM'}

    def test_invalid_file_returns_none_fields(self, tmp_path):
        path = tmp_path / 'not-a-tag.bin'
        path.write_bytes(b'garbage')
        result = module.inspect_mp3_tags(str(path))
        assert set(result.keys()) == {'TIT2', 'TPE1', 'TPE2', 'TDRC', 'TRCK', 'TCON', 'TBPM', 'TCOM'}
        assert all(v is None for v in result.values())


class TestFormatInspectTable:
    FIELDS = ['TIT2', 'TPE1', 'TPE2', 'TDRC', 'TRCK', 'TCON', 'TBPM', 'TCOM']

    def test_missing_values_shown_as_dash_dash(self):
        rows = [{'file': 'song.mp3', **{f: None for f in self.FIELDS}}]
        table = module.format_inspect_table(rows)
        assert table.count('---') >= len(self.FIELDS)

    def test_contains_header_and_values(self):
        rows = [{
            'file': 'song.mp3',
            'TIT2': 'Yellow', 'TPE1': 'Coldplay', 'TPE2': None,
            'TDRC': '2000', 'TRCK': '3', 'TCON': 'Rock',
            'TBPM': '128', 'TCOM': None,
        }]
        table = module.format_inspect_table(rows)
        lines = table.splitlines()
        assert len(lines) == 2  # header + one row
        assert 'file' in lines[0] and 'TIT2' in lines[0]
        assert 'Yellow' in lines[1]
        assert '---' in lines[1]

    def test_csv_output(self):
        rows = [{
            'file': 'a.mp3',
            'TIT2': 'X', 'TPE1': None, 'TPE2': None,
            'TDRC': None, 'TRCK': None, 'TCON': None,
            'TBPM': None, 'TCOM': None,
        }]
        csv_text = module.format_inspect_table(rows, fmt='csv')
        assert 'file,TIT2,TPE1,TPE2,TDRC,TRCK,TCON,TBPM,TCOM' in csv_text
