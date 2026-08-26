"""Tests for the shared ChangeLogger: delete entries + rollback skipping."""
import json

import pytest

from core.changelog import ChangeLogger


@pytest.fixture
def cli():
    """Load update-mp3-metadata.py under a module name that isn't shadowed
    by any installed package."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "mp3_cli", "update-mp3-metadata.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestChangeLoggerDeleteEntries:
    def test_log_delete_records_trash_destination(self, tmp_path):
        logger = ChangeLogger(tmp_path / "changes.json")
        logger.log_delete("/music/dup.mp3", "/FakeTrash/dup.mp3")

        assert len(logger.changes) == 1
        change = logger.changes[0]
        # Delete entries carry the same shape as rename entries, incl. timestamp.
        assert change['timestamp']
        assert change['operation'] == 'delete'
        assert change['original_path'] == '/music/dup.mp3'
        assert change['trash_destination'] == '/FakeTrash/dup.mp3'

    def test_saved_log_is_valid_json_with_mixed_operations(self, tmp_path):
        log_file = tmp_path / "changes.json"
        logger = ChangeLogger(log_file)
        logger.log_change(
            "/music/song.mp3", "/music/Artist/Album/01 - song.mp3",
            {'title': None}, {'title': 'song'})
        logger.log_delete("/music/dup.mp3", "/FakeTrash/dup.mp3")
        logger.save()

        data = json.loads(log_file.read_text())
        assert [e['operation'] for e in data] == ['rename', 'delete']


class TestRollbackSkipsDeletes:
    def test_rollback_skips_delete_entries_without_crashing(self, tmp_path,
                                                            cli, capsys,
                                                            monkeypatch):
        log_file = tmp_path / "changes.json"
        log_file.write_text(json.dumps([{
            'operation': 'delete',
            'original_path': '/music/gone.mp3',
            'trash_destination': '/FakeTrash/gone.mp3',
        }]))
        monkeypatch.setattr('builtins.input', lambda: 'yes')

        result = cli.rollback_changes(str(log_file))

        out = capsys.readouterr().out.lower()
        assert result is True
        assert 'delete' in out or 'skip' in out
