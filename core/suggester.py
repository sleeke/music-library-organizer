"""Metadata suggestion engine: filename parse -> AcoustID -> iTunes.

Generates proposals only; nothing is written to files here. The CLI's
'not found' stamping behavior intentionally does not exist in the web app.
"""
import re
from .lookups import query_acoustid, query_itunes_api
from .utils import parse_filename

FIELDS = ('artist', 'albumartist', 'album', 'title', 'tracknumber')
_INVALID = {None, '', 'unknown', '-', ' ', 'not found'}
_DIGIT_ONLY_FIELDS = ('artist', 'albumartist', 'title')


def _invalid(value):
    if value is None:
        return True
    text = str(value).strip()
    lower = text.lower()
    return lower in {v.lower() for v in _INVALID if v is not None} or \
           text == ''


def _digit_only(value):
    text = str(value).strip() if value is not None else ''
    return text.isdigit() and len(text) <= 2


def needs_suggestion(tags):
    """Does this file need any metadata suggestion?

    Returns True if at least one of: artist, albumartist, album, title, tracknumber
    is missing/invalid or looks like a digit-only placeholder.
    """
    for key in FIELDS[:4]:  # skip tracknumber (it's already numeric by nature)
        if _invalid(tags.get(key)):
            return True
    for key in _DIGIT_ONLY_FIELDS:
        if _digit_only(tags.get(key)):
            return True
    return False


def _effective(tags, fields, key):
    """Best-known value for searching: proposed wins over current tag."""
    if key in fields:
        return fields[key]
    value = tags.get(key)
    return None if _invalid(value) else value


def _is_valid(value: object) -> bool:
    """Return True if a tag value is considered 'valid' (not missing/invalid)."""
    return not _invalid(value)


def generate_for_file(path, tags):
    fields, sources, confidence = {}, {}, None

    # --- 1. filename parse (only fills missing/invalid) ---
    for key, value in parse_filename(path).items():
        if key in FIELDS and _invalid(tags.get(key)) and value:
            fields[key] = str(value)
            sources[key] = 'filename'

    # --- 2. AcoustID lookup (only when something else is missing/invalid) ---
    if any(_invalid(tags.get(k)) and k not in fields for k in FIELDS):
        result = query_acoustid(path)
        if result and '_error' not in result:
            confidence = result.get('confidence')
            for key in FIELDS:
                value = result.get(key)
                if value:
                    current = tags.get(key)

                    # For 'album': even if already present, propose a CHANGE
                    # when the lookup is confident and differs beyond trivial edits.
                    if key == 'album' and _is_valid(current):
                        proposed = str(value)
                        # Only propose if: confident AND not a trivial edit (case/whitespace/punctuation)
                        if confidence is not None and confidence >= 0.5 \
                                and not _is_trivial_edit(current, proposed):
                            fields[key] = proposed
                            sources[key] = 'acoustid'

                    # For other fields (or missing current value), propose normally
                    elif key not in fields:
                        fields[key] = str(value)
                        sources[key] = 'acoustid'

    # --- 3. iTunes lookup (same logic as AcoustID, same album-change gate) ---
    if any(_invalid(tags.get(k)) and k not in fields for k in FIELDS):
        result = query_itunes_api(
            artist=_effective(tags, fields, 'artist'),
            title=_effective(tags, fields, 'title'),
            album=_effective(tags, fields, 'album'))
        if result and '_error' not in result:
            for key in FIELDS:
                value = result.get(key)
                if value:
                    current = tags.get(key)

                    if key == 'album' and _is_valid(current):
                        proposed = str(value)
                        # iTunes match is treated as confident;
                        # only propose a CHANGE when it differs beyond trivial edits.
                        if not _is_trivial_edit(current, proposed):
                            fields[key] = proposed
                            sources[key] = 'itunes'

                    elif key not in fields:
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


def _normalize(value):
    """Normalize a string for trivial-edit comparison.

    Lowercase, collapse whitespace, strip punctuation and common album-title noise
    (e.g. '—', ':', '/', '\\', '*', '?', '"'). Returns normalized form or '' if empty.
    """
    text = str(value).strip()
    # lowercase + collapse spaces/tabs/newlines into single space
    text = re.sub(r'\s+', ' ', text)
    # strip trailing punctuation that commonly appears at end of titles/albums
    text = re.sub(r'[.,;:!?]+$', '', text)
    # strip common album-title noise characters (common separators, special chars)
    text = re.sub(r'[\-\—\(\)\[\]\{\}\*\'\"\\]', '', text)
    return text


def _is_trivial_edit(current: str, proposed: str) -> bool:
    """Are current and proposed the same up to case/whitespace/punctuation?

    Returns True if they differ only by formatting (case folding, extra spaces,
    trailing punctuation, common separators), meaning no real "correction" happened.
    Returns False if they are genuinely different albums.
    """
    if not current or not proposed:
        return False
    return _normalize(current).lower() == _normalize(proposed).lower()
