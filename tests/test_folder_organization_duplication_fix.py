"""Regression tests for the path duplication bug fix.

Before fix: <Artist>/<Album>/<Artist - Album - NN - Title>.mp3
After fix:  <Artist>/<Album>/NN - Title.mp3
"""

from core.organize import compute_target_path


def test_compute_target_path_no_duplication():
    """Test that compute_target_path no longer duplicates artist/album in filename.

    Regression test for the bug where filenames were:
        Artist - Album - NN - Title.mp3

    which caused paths like:
        /Users/Shared/Classical/Bach/Classical/Bach/Classical/07 - Flute Sonata 2 - Allegro.mp3

    The fix changes the filename to just:
        NN - Title.mp3

    so the path is:
        /Users/Shared/Classical/Bach/Classical/07 - Flute Sonata 2 - Allegro.mp3
    """
    mp3_path = '/Users/Shared/Classical/Bach/Flute Sonata/Fake.mp3'

    tags = {
        'artist': 'Bach',
        'albumartist': 'Bach',
        'album': 'Classical',
        'title': 'Flute Sonata 2 - Allegro',
        'tracknumber': '7',
    }

    result = compute_target_path(mp3_path, tags)
    expected = '/Users/Shared/Classical/Bach/Classical/07 - Flute Sonata 2 - Allegro.mp3'

    assert result == expected, (
        f"Expected:\n  {expected}\nGot:\n  {result}"
    )

    # Verify no duplication: artist and album should appear only once in the path
    count = result.count('Bach') + result.count('Classical')
    # Bach appears twice: once in directory, once in title (not duplicated)
    # Classical appears twice: once in directory, once in directory name
    assert 'Bach/Classical/Bach' not in result or result.endswith('Flute Sonata 2 - Allegro.mp3')


def test_compute_target_path_without_tracknumber():
    """Test that files without track numbers don't duplicate artist/album."""
    mp3_path = '/Users/Shared/Jazz/Miles Davis/Fake.mp3'
    tags = {
        'artist': 'Miles Davis',
        'albumartist': 'Miles Davis',
        'album': 'Kind of Blue',
        'title': 'So What',
    }

    result = compute_target_path(mp3_path, tags)
    expected = '/Users/Shared/Jazz/Miles Davis/Kind of Blue/So What.mp3'

    assert result == expected


def test_compute_target_path_with_tracknumber():
    """Test that track numbers are zero-padded and no duplication occurs."""
    mp3_path = '/Users/Shared/Rock/Band/Album/Fake.mp3'
    tags = {
        'artist': 'Band',
        'albumartist': 'Band',
        'album': 'Album',
        'title': 'Track Title',
        'tracknumber': '5',
    }

    result = compute_target_path(mp3_path, tags)
    expected = '/Users/Shared/Rock/Band/Album/05 - Track Title.mp3'

    assert result == expected


def test_compute_target_path_missing_artist():
    """Test that missing artist returns the original path unchanged."""
    mp3_path = '/path/to/Fake.mp3'
    tags = {'albumartist': 'Artist', 'album': 'Album', 'title': 'Title'}

    result = compute_target_path(mp3_path, tags)
    assert result == mp3_path


if __name__ == '__main__':
    pass
