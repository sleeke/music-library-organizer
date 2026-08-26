"""Change-log recording shared by the CLI and the web app.

Extracted from update-mp3-metadata.py so both frontends append to the same
JSON format that the CLI's --rollback consumes.
"""
import json
import os
from datetime import datetime
from pathlib import Path


class ChangeLogger:
    """Records metadata/rename/delete changes to a JSON changelog file.

    Delete entries record where send2trash moved each file so nothing is
    ever destroyed permanently and --rollback can skip them safely.
    """

    def __init__(self, log_file):
        self.log_file = log_file
        self.changes = []

    def log_change(self, original_path, new_path, old_metadata,
                   new_metadata, operation='rename'):
        """Record a metadata write and/or rename/move of a file."""
        change = {
            'timestamp': datetime.now().isoformat(),
            'operation': operation,
            'original_path': original_path,
            'new_path': new_path,
            'old_metadata': old_metadata,
            'new_metadata': new_metadata,
        }
        self.changes.append(change)

    def log_delete(self, original_path, trash_destination):
        """Record a file being sent to the OS Trash (never permanent)."""
        change = {
            'timestamp': datetime.now().isoformat(),
            'operation': 'delete',
            'original_path': original_path,
            'trash_destination': trash_destination,
        }
        self.changes.append(change)

    def save(self):
        """Write all recorded changes as a pretty-printed JSON list.

        Returns:
            The log file path, or None when there is nothing to save.
        """
        if not self.changes:
            return None

        log_path = Path(self.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        with open(log_path, 'w', encoding='utf-8') as f:
            json.dump(self.changes, f, indent=2, ensure_ascii=False)

        return str(log_path)

    def save_jsonl(self, history_dir=None):
        """Append one JSON object per change to <log>.jsonl.

        Args:
            history_dir: Optional directory overriding where the .jsonl
                file lives (the name always derives from the JSON log).

        Returns:
            The .jsonl path, or None when no changes were recorded.
        """
        if not self.changes:
            return None

        target = str(self.log_file) + '.jsonl'
        if history_dir:
            target = os.path.join(history_dir, os.path.basename(target))

        with open(target, 'a', encoding='utf-8') as f:
            for change in self.changes:
                f.write(json.dumps(change, ensure_ascii=False) + '\n')

        return target
