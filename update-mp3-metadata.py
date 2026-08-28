import os
import sys
import argparse
import csv
import json
import re
from datetime import datetime
from pathlib import Path
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, TCON, TBPM, APIC
from mutagen.mp3 import MP3
import requests
import time
import acoustid
from core.utils import sanitize_filename, parse_filename, compute_checksum, scan_mp3_files
from core.lookups import query_acoustid, query_itunes_api, query_musicbrainz_artist
from core.changelog import ChangeLogger

# =============================================================================
# Changelog
# -----------------------------------------------------------------------------
# - Audio fingerprinting via AcoustID/Chromaprint, with iTunes text lookup as a
#   fallback for missing metadata; metadata + file reorganization into
#   Artist/Album/<track> - <title>.mp3.
# - --dry-run: preview all changes without touching files.
# - --rollback <log>: undo renames/moves recorded by the JSON changelog.
# - --inspect [--csv]: read-only audit of ID3 tags (no modifications).
# - --skip-fingerprint: skip AcoustID, use filename parsing + iTunes only.
# - --history-dir <dir> + --verbose: JSONL change-history (one change/line)
#   alongside the default JSON changelog, plus detailed progress output.
# - --batch: process a whole folder with per-file progress and a summary.
# - MusicBrainz artist lookup (extract_mbid / query_musicbrainz_artist):
#   stage-name -> real-name resolution via the "Legal name" alias; honors the
#   1 req/s policy and required User-Agent. Wired into AcoustID results.
# - Cover art (--fetch-cover): Discogs search (query_discogs_cover), capped
#   download (download_image, ~1 MB), embedded as a front-cover APIC frame
#   (embed_cover_art). Opt-in so default behavior is unchanged.
# All new features respect --dry-run; default behavior is unchanged when flags
# are absent.
# =============================================================================


def normalize_genre_list(genres):
    """Normalize a list of genre values: strip whitespace, dedupe, keep order."""
    seen = set()
    result = []
    for genre in genres:
        genre = genre.strip()
        if genre and genre not in seen:
            seen.add(genre)
            result.append(genre)
    return result


def extract_genre(mp3_path):
    """Extract the genre from a file's ID3 TCON frame.

    Handles numeric genre references ("17", "(17)") — mutagen resolves these
    to their ID3v1 names automatically — as well as plain textual genres.

    Returns the primary genre, or multiple genres joined with "; " if several
    distinct values are present. Returns None when no TCON frame exists.
    """
    try:
        tags = ID3(mp3_path)
    except Exception:
        return None

    tcon_frames = tags.getall('TCON')
    if not tcon_frames:
        return None

    genres = normalize_genre_list(tcon_frames[0].genres)
    if not genres:
        return None
    return '; '.join(genres)


def extract_bpm(mp3_path):
    """Extract the BPM from a file's ID3 TBPM frame.

    Returns an int (float values are rounded), or None when the frame is
    missing or its value is non-numeric.
    """
    try:
        tags = ID3(mp3_path)
    except Exception:
        return None

    tbpm_frames = tags.getall('TBPM')
    if not tbpm_frames:
        return None

    text = ''.join(tbpm_frames[0].text).strip()
    try:
        return round(float(text))
    except (ValueError, TypeError):
        return None


# Fields shown by --inspect, in column order.
INSPECT_FIELDS = ['TIT2', 'TPE1', 'TPE2', 'TDRC', 'TRCK', 'TCON', 'TBPM', 'TCOM']

# Placeholder printed for missing/empty frames in inspect output.
MISSING_TAG = '---'


def _first_frame_text(tags, frame_id):
    """Return the joined text of the first frame with the given id, else None."""
    frames = tags.getall(frame_id)
    if not frames:
        return None
    return ''.join(str(t) for t in frames[0].text) or None


def inspect_mp3_tags(mp3_path):
    """Read raw ID3 frames from a file and return a dict of audited fields.

    Returns a dict keyed by the frame ids in INSPECT_FIELDS; each value is
    the frame's text, or None if the frame is absent. Unreadable files
    (corrupt tags, non-MP3) yield all-None dicts rather than raising.
    """
    result = {field: None for field in INSPECT_FIELDS}
    try:
        tags = ID3(mp3_path)
    except Exception:
        return result

    for field in INSPECT_FIELDS:
        result[field] = _first_frame_text(tags, field)
    return result


def format_inspect_table(rows, fmt='table'):
    """Render inspect results as a fixed-width table or CSV.

    Args:
        rows: List of dicts, each with a 'file' key plus one entry per
            field in INSPECT_FIELDS (values may be None).
        fmt: 'table' for aligned columns, 'csv' for comma-separated output.

    Returns:
        The formatted output as a string (no trailing newline).
    """
    header = ['file'] + INSPECT_FIELDS

    def render(row):
        return [row['file']] + [
            row[f] if row[f] is not None else MISSING_TAG for f in INSPECT_FIELDS
        ]

    rendered = [render(r) for r in rows]

    if fmt == 'csv':
        lines = [','.join(header)]
        lines.extend(','.join(str(c) for c in r) for r in rendered)
        return '\n'.join(lines)

    widths = [max(len(str(c)) for c in col) for col in zip(header, *rendered)]
    lines = ['  '.join(str(c).ljust(w) for c, w in zip(header, widths))]
    lines.extend('  '.join(str(c).ljust(w) for c, w in zip(r, widths)) for r in rendered)
    return '\n'.join(lines)


def run_inspect(folder, fmt='table'):
    """Scan `folder` and print an ID3 tag audit table for every MP3 found."""
    mp3_files = scan_mp3_files(folder)
    print(f"Inspecting {len(mp3_files)} MP3 file(s)\n")
    rows = []
    for mp3_file in mp3_files:
        row = inspect_mp3_tags(mp3_file)
        row['file'] = os.path.relpath(mp3_file, folder)
        rows.append(row)
    print(format_inspect_table(rows, fmt=fmt))


def run_batch(folder, **sync_kwargs):
    """Process every MP3 under `folder` sequentially with progress output.

    Prints a [n/total] counter per file and an end-of-run summary of
    updated vs. skipped counts. Extra keyword arguments are forwarded to
    sync_metadata_and_rename() unchanged.
    """
    mp3_files = scan_mp3_files(folder)
    total = len(mp3_files)
    updated = skipped = 0

    for index, mp3_file in enumerate(mp3_files, start=1):
        print(f"[{index}/{total}] {os.path.basename(mp3_file)}")
        success = sync_metadata_and_rename(mp3_file, **sync_kwargs)
        if success:
            updated += 1
        else:
            skipped += 1

    print(f"\nBatch complete: {updated} updated, {skipped} skipped, {total} total.")
    return {'updated': updated, 'skipped': skipped, 'total': total}


# Matches canonical UUIDs used for MusicBrainz IDs.
_MBID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)


def extract_mbid(tag_values):
    """Pull an artist MBID out of raw tag values.

    Args:
        tag_values: Mapping of tag name -> list of string values (e.g. a
            TXXX frame dict or ID3 comment). Values carrying an explicit
            "MBID:" prefix are trusted as-is; bare values are only
            accepted when they look like a UUID (avoids false positives).

    Returns:
        The MBID string, or None when absent/invalid.
    """
    for values in tag_values.values():
        for value in values or []:
            value = value.strip()
            if value.upper().startswith('MBID:'):
                return value.split(':', 1)[1].strip() or None
            if _MBID_RE.match(value):
                return value.lower()
    return None


# Discogs web-service base URL (JSON responses).
DISCOGS_API = 'https://api.discogs.com'

# Cap on downloaded artwork size (~1MB) to avoid pulling huge scans.
MAX_IMAGE_BYTES = 1024 * 1024


def query_discogs_cover(artist, album, token=None):
    """Find the highest-resolution cover-art URL for an album on Discogs.

    Args:
        artist: Album artist name to search for.
        album: Album title to search for.
        token: Discogs personal-access token (required by their API).

    Returns:
        The best cover_image URL, or None when nothing found / on error.
    """
    if not artist or not album or not token:
        return None

    url = f"{DISCOGS_API}/database/search"
    params = {'artist': artist, 'title': album, 'type': 'release',
              'per_page': 5}
    headers = {
        "User-Agent": "mp3-metadata-poc/1.0",
        "Authorization": f"Discogs token={token}",
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        if resp.status_code != 200:
            print(f"Warning: Discogs search failed with HTTP {resp.status_code}")
            return None
        results = resp.json().get('results', [])
    except Exception as e:
        print(f"Warning: Discogs search failed: {e}")
        return None

    # Prefer the largest available image across the top few matches.
    def image_area(result):
        image = result.get('cover_image') or {}
        return (image.get('width') or 0) * (image.get('height') or 0)

    best_url = None
    for result in sorted(results, key=image_area, reverse=True):
        image = result.get('cover_image') or {}
        if image.get('resource_url'):
            best_url = image['resource_url']
            break
    return best_url


def download_image(url, max_bytes=MAX_IMAGE_BYTES):
    """Download raw image bytes from `url`, enforcing a size cap.

    Returns:
        Image bytes, or None when oversized / on error.
    """
    try:
        resp = requests.get(url, headers={"User-Agent": "mp3-metadata-poc/1.0"},
                            timeout=30)
        if resp.status_code != 200:
            print(f"Warning: image download failed with HTTP {resp.status_code}")
            return None
        if len(resp.content) > max_bytes:
            print(f"Warning: skipping image ({len(resp.content)} bytes "
                  f"exceeds {max_bytes}-byte cap)")
            return None
        return resp.content
    except Exception as e:
        print(f"Warning: image download failed: {e}")
        return None


def embed_cover_art(mp3_path, image_data):
    """Embed `image_data` as the front-cover APIC frame of an MP3.

    Replaces any existing front-cover frame so stale art is not kept.
    Other tags are preserved.

    Returns:
        True when saved successfully, False otherwise.
    """
    try:
        tags = ID3(mp3_path)
        tags.delall('APIC')
        tags.add(APIC(encoding=3, mime='image/jpeg', type=3,
                      desc='Cover', data=image_data))
        tags.save(mp3_path, v1=0, v2_version=3)
        return True
    except Exception as e:
        print(f"Warning: could not embed cover art in {os.path.basename(mp3_path)}: {e}")
        return False


def fetch_cover_and_embed(mp3_path, artist=None, album=None, dry_run=False,
                          discogs_token=None, enabled=False):
    """Look up and embed cover art for one MP3 (Feature C orchestrator).

    Disabled unless explicitly requested (`enabled=True`, wired to
    --fetch-cover), so default behavior stays unchanged. Never writes in
    dry-run mode.

    Returns:
        True when art was fetched and embedded, False when a lookup/download
        failed while enabled, None when disabled/skipped (no album, etc.).
    """
    if not enabled:
        return None
    if not album or album in ['Unknown', 'not found']:
        return None
    if not artist or artist in ['Unknown', 'not found']:
        artist = None

    url = query_discogs_cover(artist, album, token=discogs_token)
    if not url:
        return False

    image_data = download_image(url)
    if not image_data:
        return False

    if dry_run:
        print(f"[DRY RUN] Would embed cover art in: {os.path.basename(mp3_path)}")
        return None
    return embed_cover_art(mp3_path, image_data)


def resolve_log_path(history_dir=None, explicit=None, timestamp=None, prefix='changes'):
    """Decide where a run's change log should be written.

    Precedence: explicit --log path > --history-dir directory > script dir.

    Args:
        history_dir: Optional directory from --history-dir; the generated
            filename lands here instead of the script's directory.
        explicit: Explicit log file path from --log; returned as-is.
        timestamp: Timestamp string for generated names ('%Y%m%d_%H%M%S');
            defaults to the current time.
        prefix: Filename prefix for generated names.

    Returns:
        A Path to the log file.
    """
    if explicit:
        return Path(explicit)

    stamp = timestamp or datetime.now().strftime('%Y%m%d_%H%M%S')
    name = f"{prefix}_{stamp}.json"
    base = Path(history_dir) if history_dir else Path(__file__).resolve().parent
    return base / name

def rollback_changes(log_file):
    """Rollback changes from a log file."""
    if not os.path.exists(log_file):
        print(f"Error: Log file not found: {log_file}")
        return False
    
    with open(log_file, 'r', encoding='utf-8') as f:
        changes = json.load(f)
    
    if not changes:
        print("No changes to rollback.")
        return True
    
    print(f"Found {len(changes)} changes to rollback.")
    print("\nWARNING: This will:")
    print("  1. Rename files back to their original names")
    print("  2. Restore original metadata")
    print("\nProceed? (yes/no): ", end='')
    
    response = input().strip().lower()
    if response != 'yes':
        print("Rollback cancelled.")
        return False
    
    success_count = 0
    error_count = 0
    
    # Process in reverse order
    for change in reversed(changes):
        operation = change.get('operation', 'rename')
        if operation == 'delete':
            print(f"Skipping delete entry (restore manually from trash): "
                  f"{change.get('original_path', 'unknown')}")
            continue
        try:
            new_path = change['new_path']
            original_path = change['original_path']
            old_metadata = change['old_metadata']
            
            # Check if file exists at new location
            if not os.path.exists(new_path):
                print(f"Warning: File not found at new location: {new_path}")
                # Try original location
                if os.path.exists(original_path):
                    print(f"  File still at original location, skipping.")
                    continue
                else:
                    print(f"  File not found anywhere, skipping.")
                    error_count += 1
                    continue
            
            # Restore metadata
            try:
                audio = MP3(new_path, ID3=EasyID3)
                for key, value in old_metadata.items():
                    if value:
                        audio[key] = value
                    elif key in audio:
                        del audio[key]
                audio.save()
            except Exception as e:
                print(f"Warning: Could not restore metadata for {new_path}: {e}")
            
            # Rename back to original
            if new_path != original_path:
                # Check if original path is available
                if os.path.exists(original_path):
                    print(f"Error: Original path already exists: {original_path}")
                    error_count += 1
                    continue
                
                os.rename(new_path, original_path)
                print(f"Restored: {os.path.basename(original_path)}")
            
            success_count += 1
            
        except Exception as e:
            print(f"Error rolling back {change.get('new_path', 'unknown')}: {e}")
            error_count += 1
    
    print(f"\nRollback complete!")
    print(f"  Successfully restored: {success_count}")
    print(f"  Errors: {error_count}")
    
    return error_count == 0

def sync_metadata_and_rename(mp3_path, dry_run=False, logger=None, skip_fingerprint=False,
                              fetch_cover=False, discogs_token=None, acoustid_key=None):
    try:
        audio = MP3(mp3_path, ID3=EasyID3)
    except Exception:
        print(f"Skipping {mp3_path}: not a valid MP3 or missing ID3 tags.")
        return False
    
    # Store original metadata for logging
    original_metadata = {
        'artist': audio.get('artist', [None])[0],
        'albumartist': audio.get('albumartist', [None])[0],
        'album': audio.get('album', [None])[0],
        'title': audio.get('title', [None])[0],
        'tracknumber': audio.get('tracknumber', [None])[0]
    }

    filename_info = parse_filename(mp3_path)
    changed = False

    # Fill missing metadata from filename
    for key in ['albumartist', 'album', 'title', 'tracknumber']:
        if key in filename_info and (key not in audio or not audio[key]):
            audio[key] = filename_info[key]
            changed = True
    
    # If albumartist was set but artist wasn't, copy albumartist to artist
    if 'albumartist' in filename_info and (not audio.get('artist') or not audio['artist'][0]):
        audio['artist'] = filename_info['albumartist']
        changed = True

    # If still missing, try audio fingerprinting first (most accurate)
    needs_lookup = False
    for key in ['artist', 'albumartist', 'album', 'title', 'tracknumber']:
        current_value = audio.get(key, [None])[0]
        if not current_value or current_value in ['Unknown', '-', '', ' ']:
            needs_lookup = True
            break
    
    if needs_lookup and not skip_fingerprint:
        print(f"Attempting audio fingerprint identification for {os.path.basename(mp3_path)}...")
        acoustid_result = query_acoustid(mp3_path, api_key=acoustid_key)
        
        if acoustid_result and '_error' not in acoustid_result:
            # Apply results from audio fingerprinting
            for key in ['artist', 'albumartist', 'album', 'title', 'tracknumber']:
                if key in acoustid_result and acoustid_result[key]:
                    current_value = audio.get(key, [None])[0]
                    if not current_value or current_value in ['Unknown', '-', '', ' ']:
                        audio[key] = acoustid_result[key]
                        changed = True
            
            confidence = acoustid_result.get('confidence', 0)
            print(f"  ✓ Identified with {int(confidence * 100)}% confidence")
            time.sleep(1)  # Be respectful with API rate
    
    # If still missing after fingerprinting, do ONE text-based iTunes lookup
    # for the whole track, then fill whatever fields it returned.
    def _clean(value):
        return None if value in (None, 'Unknown', '-', '', ' ') else value

    search_artist = _clean(audio.get('artist', [None])[0])
    search_title = _clean(audio.get('title', [None])[0])
    search_album = _clean(audio.get('album', [None])[0])

    if not search_artist and not search_title:
        print(f"Warning: Skipping online lookup for {os.path.basename(mp3_path)} - no artist or title to search")
    else:
        itunes_result = query_itunes_api(
            artist=search_artist,
            title=search_title,
            album=search_album,
        )
        if '_error' in itunes_result:
            print(f"Warning: iTunes lookup failed for {os.path.basename(mp3_path)}: {itunes_result['_error']}")
        else:
            for key in ['artist', 'albumartist', 'album', 'title', 'tracknumber']:
                current_value = audio.get(key, [None])[0]
                if key in itunes_result and itunes_result[key] and (
                    not current_value or current_value in ['Unknown', '-', '', ' ']
                ):
                    audio[key] = itunes_result[key]
                    changed = True
        time.sleep(0.5)  # Be respectful with API rate
    
    # Mark any remaining missing/invalid fields as "not found"
    for key in ['artist', 'albumartist', 'album', 'title']:
        current_value = audio.get(key, [None])[0]
        # Check if value is missing or invalid
        if not current_value or current_value in ['Unknown', '-', '', ' ']:
            audio[key] = 'not found'
            changed = True
        # Also check for single digit or double digit numbers (likely track numbers mistakenly set as metadata)
        elif key in ['artist', 'albumartist', 'title'] and current_value and current_value.isdigit() and len(current_value) <= 2:
            audio[key] = 'not found'
            changed = True
    
    # Track number is optional - mark as "not found" only if invalid
    tracknumber = audio.get('tracknumber', [None])[0]
    if tracknumber and tracknumber in ['Unknown', '-', '', ' ']:
        audio['tracknumber'] = 'not found'
        changed = True
    
    # If albumartist is not found but artist is, use artist as albumartist
    if audio.get('albumartist', [None])[0] == 'not found' and audio.get('artist', [None])[0] not in ['not found', None]:
        audio['albumartist'] = audio.get('artist', ['not found'])[0]
        changed = True
    # If artist is not found but albumartist is, use albumartist as artist
    elif audio.get('artist', [None])[0] == 'not found' and audio.get('albumartist', [None])[0] not in ['not found', None]:
        audio['artist'] = audio.get('albumartist', ['not found'])[0]
        changed = True

    if changed:
        if dry_run:
            print(f"[DRY RUN] Would update metadata for: {mp3_path}")
        else:
            audio.save()
            print(f"Updated metadata for: {mp3_path}")

    # Organize file into folder structure: Artist/Album/Track Number - Track Name.mp3
    # Use albumartist for folder (keeps albums together)
    albumartist = audio.get('albumartist', ['not found'])[0]
    # Fall back to artist if albumartist is not available
    if not albumartist or albumartist in ['Unknown', 'not found']:
        albumartist = audio.get('artist', ['not found'])[0]
    
    album = audio.get('album', ['not found'])[0]
    title = audio.get('title', ['not found'])[0]
    tracknumber = audio.get('tracknumber', [None])[0]
    
    # Skip renaming if essential metadata is missing
    if not albumartist or albumartist in ['Unknown', 'not found']:
        if not title or title in ['Unknown', 'not found']:
            print(f"Warning: Skipping rename for {mp3_path} - insufficient metadata (no album artist or title)")
            return True
    
    # Sanitize folder and filename components
    albumartist = sanitize_filename(albumartist)
    album = sanitize_filename(album)
    title = sanitize_filename(title)

    # Build new filename — artist/album are already in the directory path,
    # so the filename only includes track number and title to avoid duplication.
    # e.g. <Artist>/<Album>/01 - Title.mp3  (not Artist - Album - 01 - Title.mp3)
    if tracknumber and tracknumber not in ['not found', None]:
        # Pad track number to 2 digits
        try:
            track_num = int(tracknumber)
            track_str = f"{track_num:02d}"
        except (ValueError, TypeError):
            track_str = str(tracknumber)
        new_name = f"{track_str} - {title}.mp3"
    else:
        new_name = f"{title}.mp3"
    
    # Create directory structure
    base_dir = os.path.dirname(mp3_path)
    artist_dir = os.path.join(base_dir, albumartist)
    album_dir = os.path.join(artist_dir, album)
    new_path = os.path.join(album_dir, new_name)

    if mp3_path != new_path:
        # Check if target file already exists to prevent overwriting
        if os.path.exists(new_path):
            print(f"Warning: Cannot rename {mp3_path}")
            print(f"  Target file already exists: {new_path}")
            print(f"  Skipping rename to prevent file loss.")
            return False
        try:
            if dry_run:
                print(f"[DRY RUN] Would move: {os.path.basename(mp3_path)} -> {albumartist}/{album}/{new_name}")
            else:
                # Create directory structure if it doesn't exist
                os.makedirs(album_dir, exist_ok=True)
                
                # Move file to new location
                os.rename(mp3_path, new_path)
                print(f"Moved: {os.path.basename(mp3_path)} -> {albumartist}/{album}/{new_name}")
                
                # Log the change
                if logger:
                    new_metadata = {
                        'artist': audio.get('artist', [None])[0],
                        'albumartist': audio.get('albumartist', [None])[0],
                        'album': audio.get('album', [None])[0],
                        'title': audio.get('title', [None])[0],
                        'tracknumber': audio.get('tracknumber', [None])[0]
                    }
                    logger.log_change(mp3_path, new_path, original_metadata, new_metadata)
        except Exception as e:
            print(f"Error: Failed to move {mp3_path}: {e}")
            return False

    # Feature C: fetch & embed cover art (opt-in via --fetch-cover so default
    # behavior is unchanged). Operates on the final file location.
    final_path = new_path if mp3_path != new_path else mp3_path
    if fetch_cover:
        cover_ok = fetch_cover_and_embed(
            final_path,
            artist=audio.get('albumartist', [None])[0] or audio.get('artist', [None])[0],
            album=audio.get('album', [None])[0],
            dry_run=dry_run,
            discogs_token=discogs_token,
            enabled=True,
        )
        if cover_ok is True:
            print(f"Embedded cover art in: {os.path.basename(final_path)}")
        elif cover_ok is False:
            print(f"Warning: cover art lookup failed for {os.path.basename(final_path)}")
        # None -> skipped (disabled/dry-run/no album); nothing to report.

    return True

if __name__ == "__main__":
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description='MP3 Metadata Sync Script - Identify and organize MP3 files using audio fingerprinting and online databases.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Normal operation - organizes files into Artist/Album/ folders
  python "update-mp3-metadata.py" ~/Music/MyAlbums
  
  # Dry-run (preview changes without modifying files)
  python "update-mp3-metadata.py" --dry-run ~/Music/MyAlbums
  
  # Rollback changes from a previous run
  python "update-mp3-metadata.py" --rollback changes_20260208_123456.json

File Organization:
  Files are organized into: <Artist>/<Album>/<Track Number> - <Track Name>.mp3
  Example: Coldplay/Parachutes/01 - Yellow.mp3
        '''
    )
    
    parser.add_argument('folder', nargs='?', help='Folder to process (default: ~/mp3-metadata-poc)')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes without modifying files')
    parser.add_argument('--rollback', metavar='LOG_FILE', help='Rollback changes from specified log file')
    parser.add_argument('--log', metavar='LOG_FILE', help='Custom log file path (default: auto-generated)')
    parser.add_argument('--inspect', action='store_true',
                        help='Print an audit table of ID3 tags in each MP3 (no modifications)')
    parser.add_argument('--csv', action='store_true',
                        help='With --inspect: output CSV instead of a fixed-width table')
    parser.add_argument('--skip-fingerprint', action='store_true',
                        help='Skip AcoustID audio fingerprinting and use text-based lookup only')
    parser.add_argument('--history-dir', metavar='DIR',
                        help='Directory for JSONL change-history files (one change per line)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Show detailed progress output')
    parser.add_argument('--batch', action='store_true',
                        help='Process the whole folder with per-file progress and a summary')
    parser.add_argument('--fetch-cover', action='store_true',
                        help='Fetch and embed cover art via Discogs (opt-in; requires DISCOGS_TOKEN)')
    parser.add_argument('--discogs-token', metavar='TOKEN',
                        help='Discogs personal-access token for --fetch-cover '
                             '(falls back to DISCOGS_TOKEN env var)')
    parser.add_argument('--acoustid-key', metavar='KEY',
                        help='AcoustID API key for audio fingerprinting '
                             '(falls back to ACOUSTID_KEY env var, then the '
                             'public demo key)')


    # If the script is run with no arguments, show help and exit.
    # This helps users discover available CLI options instead of running default behavior.
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()
    
    # Handle rollback mode
    if args.rollback:
        success = rollback_changes(args.rollback)
        sys.exit(0 if success else 1)

    # Get folder from argument or use default
    if args.folder:
        folder = os.path.expanduser(args.folder)
    else:
        folder = os.path.expanduser("~/mp3-metadata-poc")

    if not os.path.isdir(folder):
        print(f"Error: '{folder}' is not a valid directory")
        sys.exit(1)

    # Handle inspect mode (read-only audit of ID3 tags)
    if args.inspect:
        run_inspect(folder, fmt='csv' if args.csv else 'table')
        sys.exit(0)
    
    # Set up logging
    logger = None
    history_dir = os.path.expanduser(args.history_dir) if args.history_dir else None
    if not args.dry_run:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_file = resolve_log_path(history_dir=history_dir, explicit=args.log,
                                    timestamp=timestamp)
        logger = ChangeLogger(str(log_file))
        print(f"Change log will be saved to: {log_file}")

    discogs_token = args.discogs_token or os.environ.get('DISCOGS_TOKEN')
    acoustid_key = args.acoustid_key or os.environ.get('ACOUSTID_KEY')

    if args.dry_run:
        print("=" * 60)
        print("DRY RUN MODE - No files will be modified")
        print("=" * 60)

    print(f"Processing MP3 files in: {folder}")
    mp3_files = scan_mp3_files(folder)
    total = len(mp3_files)
    print(f"Found {total} MP3 file(s)\n")

    error_count = 0
    if args.batch:
        summary = run_batch(folder, dry_run=args.dry_run, logger=logger,
                            skip_fingerprint=args.skip_fingerprint,
                            fetch_cover=args.fetch_cover,
                            discogs_token=discogs_token,
                            acoustid_key=acoustid_key)
        error_count = summary['skipped']
    else:
        for index, mp3_file in enumerate(mp3_files, start=1):
            if args.verbose:
                print(f"[{index}/{total}] {os.path.basename(mp3_file)}")
            success = sync_metadata_and_rename(mp3_file, dry_run=args.dry_run, logger=logger,
                                               skip_fingerprint=args.skip_fingerprint,
                                               fetch_cover=args.fetch_cover,
                                               discogs_token=discogs_token,
                                               acoustid_key=acoustid_key)
            if not success:
                error_count += 1

    # Save change log (core save() is silent — print here so CLI output keeps
    # reporting where the rollback log landed)
    if logger and not args.dry_run:
        saved_path = logger.save()
        if saved_path:
            print(f"\nChange log saved to: {saved_path}")
            print(f"Total changes logged: {len(logger.changes)}")
        logger.save_jsonl(history_dir=history_dir)
    
    if args.dry_run:
        print("\n" + "=" * 60)
        print("DRY RUN COMPLETE - No files were modified")
        print("=" * 60)
        print("\nTo apply these changes, run without --dry-run flag")
        print(f"Processing complete! {error_count} file(s) had errors or could not be updated.")
    else:
        print(f"\nProcessing complete! {error_count} file(s) had errors or could not be updated.")
        if logger and logger.changes:
            print(f"\nTo undo these changes, run:")
            print(f"  python \"update-mp3-metadata.py\" --rollback {log_file}")
