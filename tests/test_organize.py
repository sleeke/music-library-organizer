"""Tests for computing the organized target path and moving files."""

from core.organize import UNKNOWN_ALBUM_DIR, compute_target_path, move_file


def tags(**kw):
    base = {'artist': 'Artist', 'albumartist': 'Artist', 'album': 'Album',
            'title': 'Song', 'tracknumber': '7'}
    base.update(kw)
    return base


def test_basic_target_path():
    assert compute_target_path('/music/junk.mp3', tags()) == \
        '/music/Artist/Album/07 - Song.mp3'


def test_single_digit_track_padded_two_digits():
    assert compute_target_path('/music/x.mp3', tags(tracknumber='3')) \
        .endswith('/03 - Song.mp3')


def test_non_numeric_track_kept_verbatim():
    got = compute_target_path('/music/x.mp3', tags(tracknumber='A2'))
    assert got.endswith('/A2 - Song.mp3')


def test_no_track_number_title_only():
    assert compute_target_path('/music/x.mp3', tags(tracknumber=None)) == \
        '/music/Artist/Album/Song.mp3'


def test_missing_album_uses_unknown_album_dir():
    got = compute_target_path('/music/x.mp3', tags(album=None))
    assert got == f'/music/Artist/{UNKNOWN_ALBUM_DIR}/07 - Song.mp3'


def test_artist_falls_back_when_albumartist_missing():
    got = compute_target_path('/music/x.mp3', tags(albumartist=None))
    assert got == '/music/Artist/Album/07 - Song.mp3'


def test_no_rename_when_artist_or_title_effectively_missing():
    same = '/music/x.mp3'
    assert compute_target_path(same, tags(artist=None, albumartist=None)) == same
    assert compute_target_path(same, tags(title='')) == same
    assert compute_target_path(same, tags(artist='UNKNOWN')) == same


def test_special_characters_sanitized():
    got = compute_target_path('/music/x.mp3', tags(albumartist='AC/DC'))
    assert '/AC_DC/' in got


def test_move_file_creates_dirs_and_moves(tmp_path):
    src = tmp_path / 'a.mp3'
    src.write_bytes(b'data')
    dst = tmp_path / 'nested' / 'dir' / 'b.mp3'
    assert move_file(str(src), str(dst)) == str(dst)
    assert dst.read_bytes() == b'data'
    assert not src.exists()
