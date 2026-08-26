"""Tests for duplicate detection: normalization + clustering."""

from core.duplicates import find_duplicate_clusters, normalize_text


def f(path, **kw):
    base = {'path': path, 'artist': None, 'albumartist': None, 'album': None,
            'title': None, 'tracknumber': None, 'checksum': None}
    base.update(kw)
    return base


def test_normalize_strips_case_accents_punct():
    assert normalize_text('Beyoncé! (Radio Edit)') == 'beyonce'


def test_normalize_drops_feat_suffix():
    assert normalize_text('Sunrise feat. Someone') == 'sunrise'
    assert normalize_text('Sunrise (feat. Someone)') == 'sunrise'


def test_normalize_of_empty_is_empty():
    assert normalize_text(None) == ''


def test_metadata_match_groups_same_song():
    clusters = find_duplicate_clusters([
        f('/a/Artist - Song.mp3', artist='Artist', title='Song'),
        f('/b/artist - song.mp3', artist='ARTIST', title='song'),
    ])
    assert len(clusters) == 1
    assert [m['path'] for m in clusters[0]['members']] == \
        ['/a/Artist - Song.mp3', '/b/artist - song.mp3']


def test_album_key_matches_case_insensitively():
    clusters = find_duplicate_clusters([
        f('/a/x.mp3', albumartist='AA', album='AL', tracknumber='3'),
        f('/b/y.mp3', albumartist='aa', album='al', tracknumber='3'),
    ])
    assert len(clusters) == 1


def test_different_tracks_same_album_do_not_match():
    assert find_duplicate_clusters([
        f('/a/x.mp3', albumartist='AA', album='AL', tracknumber='3'),
        f('/b/y.mp3', albumartist='AA', album='AL', tracknumber='4'),
    ]) == []


def test_filename_match_within_same_folder_only():
    clusters = find_duplicate_clusters([
        f('/music/01 - Song.mp3'),
        f('/music/Song.mp3'),
        f('/other/Song.mp3'),
    ])
    members = {m['path'] for m in clusters[0]['members']}
    assert members == {'/music/01 - Song.mp3', '/music/Song.mp3'}


def test_checksum_match_regardless_of_names():
    clusters = find_duplicate_clusters([
        f('/a/completely-different.mp3', checksum='deadbeef'),
        f('/b/totally-other-name.mp3', checksum='deadbeef'),
    ])
    assert len(clusters) == 1


def test_transitive_merge_across_match_types():
    # A~B by metadata, B~C by checksum => one cluster of three
    clusters = find_duplicate_clusters([
        f('/a.mp3', artist='X', title='Y', checksum='s1'),
        f('/b.mp3', artist='x', title='y', checksum='s1'),
        f('/c.mp3', artist='Zzz', title='Qqq', checksum='s1'),
    ])
    assert len(clusters) == 1 and len(clusters[0]['members']) == 3


def test_unique_files_produce_no_clusters():
    assert find_duplicate_clusters([
        f('/a.mp3', artist='A', title='T', checksum='1'),
        f('/b.mp3', artist='B', title='U', checksum='2'),
    ]) == []


def test_cluster_key_is_stable_hash_of_members():
    files = [
        f('/a/A.mp3', artist='X', title='Y'),
        f('/b/B.mp3', artist='x', title='y'),
    ]
    c1 = find_duplicate_clusters(files)
    c2 = find_duplicate_clusters(list(reversed(files)))
    assert c1[0]['key'] == c2[0]['key']
