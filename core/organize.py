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

    Note: The filename only contains the track number and title (e.g., "01 - Title.mp3")
    because the artist/album directories already provide that information in the path.
    A file already inside its <Artist>/<Album> folder stays there rather than
    being nested again.
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

    artist_dir_name = sanitize_filename(str(artist))
    album_dir_name = sanitize_filename(str(album))
    base_dir = organized_base_dir(mp3_path, artist_dir_name, album_dir_name)
    return os.path.join(base_dir, artist_dir_name, album_dir_name, name)


def organized_base_dir(mp3_path, artist_dir_name, album_dir_name):
    """Directory to build <Artist>/<Album>/ under for mp3_path.

    Normally the file's own directory; when the file already sits in
    <artist_dir_name>/<album_dir_name>/, the directory above that pair.
    """
    album_dir = os.path.dirname(mp3_path)
    artist_dir = os.path.dirname(album_dir)
    if (os.path.basename(album_dir) == album_dir_name
            and os.path.basename(artist_dir) == artist_dir_name):
        return os.path.dirname(artist_dir)
    return album_dir


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
