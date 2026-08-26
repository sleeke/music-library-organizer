"""Compute the organized destination path and perform safe moves."""
import errno
import os
import shutil

from .utils import sanitize_filename

UNKNOWN_ALBUM_DIR = 'Unknown Album'

_EFFECTIVELY_EMPTY = {None, '', 'unknown'}


def _usable(value):
    return value is not None and str(value).strip().lower() not in _EFFECTIVELY_EMPTY


def compute_target_path(mp3_path, tags):
    """Organized path <parent>/<Artist>/<Album>/<NN - Title>.mp3 for tags.

    Returns mp3_path unchanged when renaming is not possible (missing artist
    or title). Album falls back to UNKNOWN_ALBUM_DIR. The display artist
    prefers albumartist and falls back to artist.
    """
    title = tags.get('title')
    artist_tag = tags.get('artist')
    if not _usable(artist_tag) or not _usable(title):
        return mp3_path
    artist = tags.get('albumartist') if _usable(tags.get('albumartist')) else artist_tag

    album = tags.get('album') if _usable(tags.get('album')) else UNKNOWN_ALBUM_DIR
    tracknumber = tags.get('tracknumber')

    if _usable(tracknumber):
        try:
            track_str = f'{int(str(tracknumber).strip()):02d}'
        except (ValueError, TypeError):
            track_str = str(tracknumber).strip()
        name = f'{track_str} - {sanitize_filename(str(title))}.mp3'
    else:
        name = f'{sanitize_filename(str(title))}.mp3'

    artist_dir = os.path.join(os.path.dirname(mp3_path),
                              sanitize_filename(str(artist)))
    return os.path.join(artist_dir, sanitize_filename(str(album)), name)


def move_file(src, dst):
    """Create dst's parent dirs and move src there. Returns dst."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        os.rename(src, dst)
    except OSError as e:
        if e.errno != errno.EXDEV:
            raise
        # src and dst on different filesystems (USB drive, network share):
        # shutil.move copies + unlinks instead of failing.
        shutil.move(src, dst)
    return dst
