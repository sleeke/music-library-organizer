"""Tests for batch mode --batch (Feature E).

With the flag, sync_metadata_and_rename() processes every MP3 under the
folder in one pass and prints a progress counter plus an end-of-run
summary (updated / skipped counts). Without it, behavior is unchanged.

Testing approach: monkeypatch scan_mp3_files + sync_metadata_and_rename,
capture stdout via capsys.
"""

import importlib.util
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = PROJECT_ROOT / 'update-mp3-metadata.py'

spec = importlib.util.spec_from_file_location('update_mp3_module', str(MODULE_PATH))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def batch_run(monkeypatch):
    """Wire fake files + per-file outcomes; returns (run, calls)."""
    def _install(files, outcomes):
        monkeypatch.setattr(module, 'scan_mp3_files', lambda folder: list(files))
        calls = {'processed': []}

        def fake_sync(path, **kwargs):
            calls['processed'].append((path, kwargs))
            return outcomes[path]

        monkeypatch.setattr(module, 'sync_metadata_and_rename', fake_sync)
        return calls
    return _install


class TestRunBatch:
    def test_processes_all_files_and_prints_summary(self, capsys, batch_run):
        files = ['/m/a.mp3', '/m/b.mp3', '/m/c.mp3']
        calls = batch_run(files, {f: True for f in files})

        module.run_batch('/m')
        out = capsys.readouterr().out

        assert len(calls['processed']) == 3
        assert all(kwargs == {} for _, kwargs in calls['processed'])  # defaults preserved
        assert '[1/3]' in out and '[2/3]' in out and '[3/3]' in out
        assert 'Batch complete' in out
        assert '3 updated' in out or 'updated: 3' in out.lower()

    def test_counts_skipped_files(self, capsys, batch_run):
        files = ['/m/a.mp3', '/m/b.mp3']
        calls = batch_run(files, {'/m/a.mp3': True, '/m/b.mp3': False})

        module.run_batch('/m')
        out = capsys.readouterr().out

        assert 'skipped' in out.lower()
        # both a success and a failure appear as counts
        digits = [token for token in out.split() if token.isdigit()]
        assert '2' in digits  # total processed line mentions counts


class TestCliFlag:
    def test_flag_present_in_argparser(self):
        import subprocess, sys
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / 'update-mp3-metadata.py'), '--help'],
            capture_output=True, text=True)
        assert '--batch' in result.stdout
