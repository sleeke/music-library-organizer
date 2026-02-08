import os
import sys
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3
import requests
import time
import acoustid

def scan_mp3_files(folder):
    mp3_files = []
    for root, _, files in os.walk(folder):
        for file in files:
            if file.lower().endswith('.mp3'):
                mp3_files.append(os.path.join(root, file))
    return mp3_files

def parse_filename(filename):
    # Example: "Artist - Album - Song.mp3"
    base = os.path.splitext(os.path.basename(filename))[0]
    parts = base.split(' - ')
    if len(parts) == 3:
        return {'artist': parts[0], 'album': parts[1], 'title': parts[2]}
    elif len(parts) == 2:
        return {'artist': parts[0], 'title': parts[1]}
    return {}

def query_acoustid(mp3_path):
    """Use audio fingerprinting to identify a song from its audio data."""
    # AcoustID API key (public test key - replace with your own for production)
    api_key = 'cSpUJKpD'
    
    try:
        # Generate fingerprint and query AcoustID
        results = acoustid.match(api_key, mp3_path, meta='recordings releasegroups')
        
        for score, recording_id, title, artist in results:
            # Return the first result with a decent confidence score
            if score > 0.5:  # 50% confidence threshold
                # Try to get album information
                album = None
                try:
                    # Query MusicBrainz for more details
                    mb_url = f"https://musicbrainz.org/ws/2/recording/{recording_id}"
                    params = {'fmt': 'json', 'inc': 'releases+artist-credits'}
                    resp = requests.get(mb_url, params=params, 
                                      headers={"User-Agent": "mp3-metadata-poc/1.0"},
                                      timeout=10)
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get('releases') and len(data['releases']) > 0:
                            album = data['releases'][0].get('title')
                except:
                    pass
                
                return {
                    'artist': artist,
                    'title': title,
                    'album': album,
                    'confidence': score
                }
    except acoustid.NoBackendError:
        print(f"Error: chromaprint/fpcalc not found. Install with: brew install chromaprint")
        return {'_error': 'No backend'}
    except acoustid.FingerprintGenerationError:
        print(f"Warning: Could not generate fingerprint for {os.path.basename(mp3_path)}")
        return {'_error': 'Fingerprint failed'}
    except Exception as e:
        print(f"Warning: AcoustID lookup failed for {os.path.basename(mp3_path)}: {e}")
        return {'_error': str(e)}
    
    return {}

def query_itunes_api(artist=None, title=None, album=None):
    """Query iTunes Search API for metadata using artist, title, and/or album."""
    url = "https://itunes.apple.com/search"
    
    # Build search term
    search_terms = []
    if artist:
        search_terms.append(artist)
    if album:
        search_terms.append(album)
    if title:
        search_terms.append(title)
    
    if not search_terms:
        return {}
    
    params = {
        'term': ' '.join(search_terms),
        'media': 'music',
        'entity': 'song',
        'limit': 1
    }
    
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            print(f"Warning: iTunes API returned status code {resp.status_code} for search: {params['term']}")
            return {'_error': f"HTTP {resp.status_code}"}
        data = resp.json()
        if data.get('results') and len(data['results']) > 0:
            result = data['results'][0]
            return {
                'artist': result.get('artistName'),
                'album': result.get('collectionName'),
                'title': result.get('trackName')
            }
        else:
            print(f"Warning: No results from iTunes API for search: {params['term']}")
            return {'_error': "No results"}
    except Exception as e:
        print(f"Warning: iTunes API lookup failed for search '{params['term']}': {e}")
        return {'_error': str(e)}

def sync_metadata_and_rename(mp3_path):
    try:
        audio = MP3(mp3_path, ID3=EasyID3)
    except Exception:
        print(f"Skipping {mp3_path}: not a valid MP3 or missing ID3 tags.")
        return False

    filename_info = parse_filename(mp3_path)
    changed = False

    # Fill missing metadata from filename
    for key in ['artist', 'album', 'title']:
        if key in filename_info and (key not in audio or not audio[key]):
            audio[key] = filename_info[key]
            changed = True

    # If still missing, try audio fingerprinting first (most accurate)
    needs_lookup = False
    for key in ['artist', 'album', 'title']:
        current_value = audio.get(key, [None])[0]
        if not current_value or current_value in ['Unknown', '-', '', ' ']:
            needs_lookup = True
            break
    
    if needs_lookup:
        print(f"Attempting audio fingerprint identification for {os.path.basename(mp3_path)}...")
        acoustid_result = query_acoustid(mp3_path)
        
        if acoustid_result and '_error' not in acoustid_result:
            # Apply results from audio fingerprinting
            for key in ['artist', 'album', 'title']:
                if key in acoustid_result and acoustid_result[key]:
                    current_value = audio.get(key, [None])[0]
                    if not current_value or current_value in ['Unknown', '-', '', ' ']:
                        audio[key] = acoustid_result[key]
                        changed = True
            
            confidence = acoustid_result.get('confidence', 0)
            print(f"  ✓ Identified with {int(confidence * 100)}% confidence")
            time.sleep(1)  # Be respectful with API rate
    
    # If still missing after fingerprinting, try text-based iTunes lookup
    for key in ['artist', 'album', 'title']:
        current_value = audio.get(key, [None])[0]
        # Skip if field is present and not generic/invalid
        if current_value and current_value not in ['Unknown', '-', '', ' ']:
            continue
            
        # Get current metadata for search
        search_artist = audio.get('artist', [None])[0]
        search_title = audio.get('title', [None])[0]
        search_album = audio.get('album', [None])[0]
        
        # Clean up invalid values for searching
        if search_artist in ['Unknown', '-', '', ' ', None]:
            search_artist = None
        if search_title in ['Unknown', '-', '', ' ', None]:
            search_title = None
        if search_album in ['Unknown', '-', '', ' ', None]:
            search_album = None
        
        # Skip API lookup if we don't have at least artist or title to search with
        if not search_artist and not search_title:
            print(f"Warning: Skipping online lookup for {os.path.basename(mp3_path)} - no artist or title to search")
            break
            
        itunes_result = query_itunes_api(
            artist=search_artist,
            title=search_title,
            album=search_album
        )
        if '_error' in itunes_result:
            # API failed but continue to mark remaining fields as "not found"
            break
        if key in itunes_result and itunes_result[key]:
            audio[key] = itunes_result[key]
            changed = True
        time.sleep(0.5)  # Be respectful with API rate
    
    # Mark any remaining missing/invalid fields as "not found"
    for key in ['artist', 'album', 'title']:
        current_value = audio.get(key, [None])[0]
        # Check if value is missing or invalid
        if not current_value or current_value in ['Unknown', '-', '', ' ']:
            audio[key] = 'not found'
            changed = True
        # Also check for single digit or double digit numbers (likely track numbers mistakenly set as metadata)
        elif key in ['artist', 'title'] and current_value and current_value.isdigit() and len(current_value) <= 2:
            audio[key] = 'not found'
            changed = True

    if changed:
        audio.save()
        print(f"Updated metadata for: {mp3_path}")

    # Rename file to match metadata
    artist = audio.get('artist', ['not found'])[0]
    album = audio.get('album', ['not found'])[0]
    title = audio.get('title', ['not found'])[0]
    
    # Skip renaming if all metadata is empty or not found to prevent file loss
    if not artist or artist in ['Unknown', 'not found']:
        if not title or title in ['Unknown', 'not found']:
            print(f"Warning: Skipping rename for {mp3_path} - insufficient metadata (no artist or title)")
            return True
    
    new_name = f"{artist} - {album} - {title}.mp3"
    new_path = os.path.join(os.path.dirname(mp3_path), new_name)

    if mp3_path != new_path:
        # Check if target file already exists to prevent overwriting
        if os.path.exists(new_path):
            print(f"Warning: Cannot rename {mp3_path}")
            print(f"  Target file already exists: {new_path}")
            print(f"  Skipping rename to prevent file loss.")
            return False
        try:
            os.rename(mp3_path, new_path)
            print(f"Renamed: {os.path.basename(mp3_path)} -> {new_name}")
        except Exception as e:
            print(f"Error: Failed to rename {mp3_path}: {e}")
            return False
    return True

if __name__ == "__main__":
    # Get folder from command-line argument or use default
    if len(sys.argv) > 1:
        folder = os.path.expanduser(sys.argv[1])
    else:
        folder = os.path.expanduser("~/mp3-metadata-poc")

    if not os.path.isdir(folder):
        print(f"Error: '{folder}' is not a valid directory")
        sys.exit(1)

    print(f"Processing MP3 files in: {folder}")
    mp3_files = scan_mp3_files(folder)
    print(f"Found {len(mp3_files)} MP3 file(s)\n")

    error_count = 0
    for mp3_file in mp3_files:
        success = sync_metadata_and_rename(mp3_file)
        if not success:
            error_count += 1

    print(f"\nProcessing complete! {error_count} file(s) had errors or could not be updated.")