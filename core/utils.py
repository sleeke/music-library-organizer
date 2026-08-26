"""Shared utility functions extracted from update-mp3-metadata.py."""
import hashlib
import os


def sanitize_filename(filename):
    """Replace invalid filename characters with safe alternatives.

    Replaces illegal filesystem characters, strips leading/trailing spaces and dots,
    and truncates to 240 characters (leaving room for path + .mp3).

    Args:
        filename: The original filename string.

    Returns:
        A sanitized filename string suitable for use on macOS/Unix.
    """
    # Dictionary of replacements
    replacements = {
        '/': '_',
        '\\': '_',
        ':': ' -',
        '*': '',
        '?': '',
        '"': "'",
        '<': '',
        '>': '',
        '|': '-'
    }

    for char, replacement in replacements.items():
        filename = filename.replace(char, replacement)

    # Remove leading/trailing spaces and dots (Windows doesn't like these)
    filename = filename.strip('. ')

    # Limit length (leave room for path and .mp3 extension)
    max_length = 240
    if len(filename) > max_length:
        # Try to truncate at a word boundary
        filename = filename[:max_length].rsplit(' ', 1)[0]

    return filename


def compute_checksum(file_path, algo='sha256'):
    """Compute a checksum for a file to help verify content retention.

    Reads the file in chunks to avoid large-memory usage. Returns the hex digest string.

    Args:
        file_path: Path to the file.
        algo: Hash algorithm name ('md5', 'sha1', 'sha256' etc.). Default: 'sha256'.

    Returns:
        Hexadecimal digest string of the file's contents.
    """
    h = hashlib.new(algo)
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def scan_mp3_files(folder):
    """Scan a folder recursively and collect all .mp3 file paths.

    Args:
        folder: Root directory to search (will be walked recursively).

    Returns:
        A list of absolute paths to MP3 files found under `folder`.
    """
    mp3_files = []
    for root, _, files in os.walk(folder):
        for file in files:
            if file.lower().endswith('.mp3'):
                mp3_files.append(os.path.join(root, file))
    return mp3_files


def parse_filename(filename):
    """Parse an MP3 filename into metadata components.

    Handles these formats:
      - "Artist - Album - NN - Title.mp3" → albumartist=Artist, album=Album,
        tracknumber=NN (when third part numeric), title=Title
      - "NN - Title.mp3"  → tracknumber=NN, title=Title
      - "Artist - Album - Title.mp3" → albumartist=Artist, album=Album, title=Title
      - "Artist - Title.mp3"         → albumartist=Artist, title=Title

    Args:
        filename: The MP3 file path or name.

    Returns:
        A dict with recognized fields set (tracknumber, title, albumartist, album).
        Unknown/missing fields are omitted from the result.
    """
    base = os.path.splitext(os.path.basename(filename))[0]
    parts = base.split(' - ')

    # Check if first part is a track number (1-3 digits)
    result = {}
    if len(parts) >= 1 and parts[0].strip().isdigit() and len(parts[0].strip()) <= 3:
        result['tracknumber'] = parts[0].strip()
        if len(parts) >= 2:
            result['title'] = parts[1]
        return result

    if len(parts) == 4:
        # "Artist - Album - NN - Title": third part may be a track number
        parsed = {'albumartist': parts[0], 'album': parts[1]}
        if parts[2].strip().isdigit() and len(parts[2].strip()) <= 3:
            parsed['tracknumber'] = parts[2].strip()
        else:
            parsed['title'] = f"{parts[2]} - {parts[3]}"
            return parsed
        parsed['title'] = parts[3]
        return parsed
    elif len(parts) == 3:
        # Use the first part as albumartist (keeps albums together)
        return {'albumartist': parts[0], 'album': parts[1], 'title': parts[2]}
    elif len(parts) == 2:
        return {'albumartist': parts[0], 'title': parts[1]}
    return {}
