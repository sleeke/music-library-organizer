"""All destructive/persistent mutations flow through here.

Every action appends to the shared JSON change-log format so the CLI's
--rollback keeps working. Deletions go to the OS Trash, never permanent.
"""
import json
import os
from datetime import datetime

from send2trash import send2trash

from .changelog import ChangeLogger  # noqa: F401 (re-exported convenience)
from .organize import compute_target_path, move_file
from .tags import write_tags

TAG_FIELDS = ('artist', 'albumartist', 'album', 'title', 'tracknumber')


def default_log_path(project_dir):
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return os.path.join(project_dir, f'changes_{stamp}.json')


def apply_batch(db, logger):
    applied, conflicts, errors = [], [], []
    for sug in db.list_suggestions(status='approved'):
        f = db.get_file_by_id(sug['file_id'])
        if f is None or not os.path.exists(f['path']):
            label = f['path'] if f else f'<deleted file #{sug["file_id"]}>'
            errors.append({'file': label, 'error': 'file missing from disk'})
            continue

        fields = json.loads(sug['fields_json'])
        old_meta = {k: f.get(k) for k in TAG_FIELDS}
        new_meta = {**old_meta, **fields}

        if not write_tags(f['path'], fields):
            errors.append({'file': f['path'], 'error': 'tag write failed'})
            continue

        target = compute_target_path(f['path'], new_meta)
        moved = target != f['path']
        if moved and os.path.exists(target):
            # Refuse to overwrite: tags are written but the file stays put;
            # the suggestion stays approved so the user can fix and re-apply.
            conflicts.append({'file': f['path'], 'target': target})
            continue

        if moved:
            move_file(f['path'], target)

        logger.log_change(f['path'], target, old_meta, new_meta,
                          operation='metadata+rename' if moved else 'metadata')
        db.update_file_tags(f['id'], new_meta)
        if moved:
            db.update_file_path(f['id'], target)
        db.set_suggestion_status(sug['id'], 'applied')
        applied.append({'file': target, 'old_path': f['path'], 'new_path': target})

    logger.save()
    return {'applied': applied, 'conflicts': conflicts, 'errors': errors}


def trash_files(db, paths, logger):
    results = []
    for path in paths:
        try:
            destination = send2trash(path)
            logger.log_delete(path, str(destination) if destination else 'system trash')
            db.remove_file(path)
            results.append({'path': path, 'ok': True})
        except Exception as exc:  # report per-file; never abort the batch
            results.append({'path': path, 'ok': False, 'error': str(exc)})
    logger.save()
    return results
