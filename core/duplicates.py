"""Duplicate detection: normalization + transitive clustering (pure functions)."""
import hashlib
import os
import re
import unicodedata

_STRIP_SUFFIX = re.compile(
    r'\((?:radio edit|remaster(?:ed)?[^)]*|feat\.?[^)]*)\)', re.I)
_FEAT_TAIL = re.compile(r'\bfeat\.?\b.*$', re.I)
# Leading track numbers in filenames ("01 - Song.mp3" -> "Song").
_LEADING_TRACKNUM = re.compile(r'^\d{1,3}[\s._-]+')


def normalize_text(value):
    """Lowercase, strip accents/punctuation, drop '(radio edit)'/'feat.' noise."""
    if not value:
        return ''
    text = unicodedata.normalize('NFKD', str(value))
    text = ''.join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = _STRIP_SUFFIX.sub('', text)
    text = _FEAT_TAIL.sub('', text)
    return re.sub(r'[^a-z0-9]+', '', text)


def _match_keys(f):
    keys = []
    artist, title = f.get('artist'), f.get('title')
    if artist and title:
        keys.append(('meta', normalize_text(artist) + ':' + normalize_text(title)))
    aa, album, tn = f.get('albumartist'), f.get('album'), f.get('tracknumber')
    if aa and album and tn:
        keys.append(('album', ':'.join([normalize_text(aa), normalize_text(album),
                                        normalize_text(tn)])))
    stem = os.path.splitext(os.path.basename(f['path']))[0]
    stem = _LEADING_TRACKNUM.sub('', stem.strip())
    parent = os.path.basename(os.path.dirname(os.path.normpath(f['path'])))
    keys.append(('fname', normalize_text(stem) + '@' + normalize_text(parent)))
    if f.get('checksum'):
        keys.append(('sum', f['checksum']))
    return keys


class _DSU:
    """Disjoint-set union for transitive merging of match groups."""

    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def find_duplicate_clusters(files):
    groups = {}
    for i, item in enumerate(files):
        for kind, key in _match_keys(item):
            groups.setdefault((kind, key), []).append(i)

    dsu = _DSU(len(files))
    for indexes in groups.values():
        for other in indexes[1:]:
            dsu.union(indexes[0], other)

    components = {}
    for i in range(len(files)):
        components.setdefault(dsu.find(i), []).append(files[i])

    clusters = []
    for members in components.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda m: m['path'])
        digest = hashlib.sha1(
            ','.join(sorted(m['path'] for m in members)).encode()).hexdigest()
        clusters.append({'key': digest[:16], 'members': members})
    clusters.sort(key=lambda c: c['key'])
    return clusters
