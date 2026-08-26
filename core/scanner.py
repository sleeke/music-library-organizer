"""Incremental library scanning: walk MP3s, cache tags/checksum in SQLite."""
import os

from .tags import read_audio_info, read_tags
from .utils import compute_checksum, scan_mp3_files


def scan_folder(db, folder, progress_cb=None, checksum=True):
    folder = os.path.abspath(folder)
    if db.get_meta('root') != folder:
        db.reset_library()
        db.set_meta('root', folder)

    mp3_paths = scan_mp3_files(folder)
    stats = {'total': len(mp3_paths), 'updated': 0,
             'unchanged': 0, 'errors': 0}

    for i, path in enumerate(mp3_paths, start=1):
        try:
            st = os.stat(path)
        except OSError:
            stats['errors'] += 1
            if progress_cb:
                progress_cb(i, stats['total'], 'scan')
            continue
        existing = db.get_file(path)
        # Rows missing duration/bitrate (e.g. from a scan before those columns
        # were populated) are treated as stale so the next scan fills them in.
        fresh = (existing is not None and not existing.get('error')
                 and existing['size'] == st.st_size
                 and existing['mtime'] == st.st_mtime
                 and existing['duration'] is not None
                 and existing['bitrate'] is not None)
        if fresh:
            stats['unchanged'] += 1
        else:
            tags = read_tags(path)
            if tags is None:
                db.mark_error(path, 'not a valid MP3 or missing ID3 tags')
                stats['errors'] += 1
            else:
                duration, bitrate = read_audio_info(path)
                record = {'path': path, 'filename': os.path.basename(path),
                          'size': st.st_size, 'mtime': st.st_mtime,
                          'duration': duration, 'bitrate': bitrate, **tags}
                if checksum:
                    record['checksum'] = compute_checksum(path)
                elif existing:
                    record['checksum'] = existing['checksum']
                db.upsert_file(record)
                stats['updated'] += 1
        if progress_cb:
            progress_cb(i, stats['total'], 'scan')

    stats['removed'] = db.prune_missing(folder)
    return stats
