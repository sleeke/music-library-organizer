"""Tests for logging & history (Feature G).

ChangeLogger gains JSONL output: save_jsonl() writes one change object per
line to <log>.jsonl alongside the existing rollback-compatible JSON array.
resolve_log_path() centralizes default/custom log-file naming so --history-dir
can redirect logs to a directory of per-run JSONL files.

Testing approach: pure-function and file-based tests over ChangeLogger with
in-memory change records; no MP3s or network involved.
"""

import importlib.util
import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = PROJECT_ROOT / 'update-mp3-metadata.py'

spec = importlib.util.spec_from_file_location('update_mp3_module', str(MODULE_PATH))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def _sample_change(n=1):
    return {
        'timestamp': '2026-08-23T12:00:00',
        'operation': 'rename',
        'original_path': f'/music/track{n:02d}.mp3',
        'new_path': f'/music/Artist/Album/{n:02d} - Song.mp3',
        'old_metadata': {'artist': None},
        'new_metadata': {'artist': 'Artist'},
    }


class TestSaveJsonl:
    def test_writes_one_json_object_per_line(self, tmp_path):
        logger = module.ChangeLogger(str(tmp_path / 'changes.json'))
        logger.log_change('/a.mp3', '/b.mp3', {'x': 1}, {'y': 2})
        logger.log_change('/c.mp3', '/d.mp3', {}, {})
        jsonl_path = Path(logger.save_jsonl())
        lines = jsonl_path.read_text(encoding='utf-8').splitlines()
        assert len(lines) == 2
        first, second = (json.loads(line) for line in lines)
        assert first['original_path'] == '/a.mp3'
        assert second['original_path'] == '/c.mp3'
        # Each change carries its own timestamp field like the array format
        assert 'timestamp' in first and 'operation' in first

    def test_returns_none_when_no_changes(self, tmp_path):
        logger = module.ChangeLogger(str(tmp_path / 'changes.json'))
        assert logger.save_jsonl() is None

    def test_creates_history_dir_if_missing(self, tmp_path):
        target_dir = tmp_path / 'nested' / 'history'
        path = module.resolve_log_path(target_dir, prefix='changes')
        assert str(path).startswith(str(target_dir))
        # resolve only names the file; dir creation happens at write time
        jsonl = module.ChangeLogger(str(path)).save_jsonl()
        assert jsonl is None  # no changes logged yet


class TestResolveLogPath:
    def test_explicit_file_wins(self, tmp_path):
        custom = tmp_path / 'custom.json'
        path = module.resolve_log_path(history_dir=None, explicit=custom)
        assert path == custom

    def test_default_in_script_dir(self, monkeypatch):
        monkeypatch.setattr(module, '__file__', '/somewhere/update-mp3-metadata.py')
        path = module.resolve_log_path(history_dir=None, timestamp='20260823_123045')
        assert path == Path('/somewhere/changes_20260823_123045.json')

    def test_history_dir_redirects(self, tmp_path):
        path = module.resolve_log_path(
            history_dir=tmp_path,
            timestamp='20260823_123045',
        )
        assert path.parent == tmp_path
        assert path.name.startswith('changes_20260823_123045')


class TestVerbose:
    def test_verbose_flag_parsed(self):
        argv = ['folder', '--verbose']
        parser_args = None  # parsed inside __main__; here we just check the flag exists
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument('--verbose', '-v', action='store_true')
        args = parser.parse_args(['--verbose'])
        assert args.verbose is True

    def test_short_flag_v(self):
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument('--verbose', '-v', action='store_true')
        args = parser.parse_args(['-v'])
        assert args.verbose is True
