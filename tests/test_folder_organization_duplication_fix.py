"""Regression tests for path duplication when organizing.

Filenames are <Artist>/<Album>/NN - Title.mp3 (artist/album live only in the
directories), and a file already inside its <Artist>/<Album> folder must not
be nested again as <Artist>/<Album>/<Artist>/<Album>/.
"""

from core.organize import compute_target_path


def tags(**kw):
    base = {'artist': 'Band', 'albumartist': 'Band', 'album': 'Album',
            'title': 'Track Title', 'tracknumber': '5'}
    base.update(kw)
    return base


def test_filename_omits_artist_and_album():
    assert compute_target_path('/music/Fake.mp3', tags()) == \
        '/music/Band/Album/05 - Track Title.mp3'


def test_already_organized_file_is_not_nested_again():
    path = '/music/Band/Album/Fake.mp3'
    assert compute_target_path(path, tags()) == '/music/Band/Album/05 - Track Title.mp3'


def test_already_organized_without_tracknumber():
    path = '/music/Miles Davis/Kind of Blue/old.mp3'
    got = compute_target_path(path, tags(artist='Miles Davis', albumartist='Miles Davis',
                                         album='Kind of Blue', title='So What',
                                         tracknumber=None))
    assert got == '/music/Miles Davis/Kind of Blue/So What.mp3'


def test_organizing_is_idempotent():
    first = compute_target_path('/music/Fake.mp3', tags())
    assert compute_target_path(first, tags()) == first


def test_folder_named_like_album_but_wrong_artist_still_nests():
    # Only a matching <Artist>/<Album> pair counts as already organized.
    assert compute_target_path('/music/Other/Album/Fake.mp3', tags()) == \
        '/music/Other/Album/Band/Album/05 - Track Title.mp3'
