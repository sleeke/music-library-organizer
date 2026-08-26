"""Metadata suggestion engine: filename parse -> AcoustID -> iTunes.

Generates proposals only; nothing is written to files here. The CLI's
'not found' stamping behavior intentionally does not exist in the web app.
"""
from .lookups import query_acoustid, query_itunes_api
from .utils import parse_filename

FIELDS = ('artist', 'albumartist', 'album', 'title', 'tracknumber')
_INVALID = {None, '', 'unknown', '-', ' ', 'not found'}
_DIGIT_ONLY_FIELDS = ('artist', 'albumartist', 'title')


def _invalid(value):
    if value is None:
        return True
    return str(value).strip().lower() in {v for v in _INVALID if v is not None} or \
        str(value).strip() == ''


def _digit_only(value):
    text = str(value).strip() if value is not None else ''
    return text.isdigit() and len(text) <= 2


def needs_suggestion(tags):
    if any(_invalid(tags.get(k)) for k in FIELDS[:4]):
        return True
    return any(_digit_only(tags.get(k)) for k in _DIGIT_ONLY_FIELDS)


def _effective(tags, fields, key):
    """Best-known value for searching: proposed wins over current tag."""
    if key in fields:
        return fields[key]
    value = tags.get(key)
    return None if _invalid(value) else value


def generate_for_file(path, tags):
    fields, sources, confidence = {}, {}, None

    for key, value in parse_filename(path).items():
        if key in FIELDS and _invalid(tags.get(key)) and value:
            fields[key] = str(value)
            sources[key] = 'filename'

    if any(_invalid(tags.get(k)) and k not in fields for k in FIELDS):
        result = query_acoustid(path)
        if result and '_error' not in result:
            confidence = result.get('confidence')
            for key in FIELDS:
                value = result.get(key)
                if value and _invalid(tags.get(key)) and key not in fields:
                    fields[key] = str(value)
                    sources[key] = 'acoustid'

    if any(_invalid(tags.get(k)) and k not in fields for k in FIELDS):
        result = query_itunes_api(
            artist=_effective(tags, fields, 'artist'),
            title=_effective(tags, fields, 'title'),
            album=_effective(tags, fields, 'album'))
        if result and '_error' not in result:
            for key in FIELDS:
                value = result.get(key)
                if value and _invalid(tags.get(key)) and key not in fields:
                    fields[key] = str(value)
                    sources[key] = 'itunes'

    return fields, sources, confidence


def run_suggest_pass(db, progress_cb=None):
    files = [f for f in db.all_files() if not f.get('error')]
    stats = {'considered': 0, 'suggested': 0}
    for i, f in enumerate(files, start=1):
        # A file already decided (approved/applied) keeps its verdict;
        # re-running lookups would only duplicate the pending suggestion.
        if db.has_non_pending_suggestion(f['id']):
            continue
        stats['considered'] += 1
        fields, sources, confidence = generate_for_file(f['path'], f)
        if fields:
            db.replace_suggestion(f['id'], fields, sources, confidence)
            stats['suggested'] += 1
        if progress_cb:
            progress_cb(i, len(files), 'suggest')
    return stats
