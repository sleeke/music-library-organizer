"""Online metadata lookups: AcoustID fingerprinting + iTunes Search API.

Extracted verbatim from update-mp3-metadata.py so both the CLI and the web
app share one implementation. Includes the MusicBrainz artist lookup that
AcoustID results are enriched with.
"""
import logging
import os
import time

import requests
import acoustid

logger = logging.getLogger(__name__)

# MusicBrainz web-service base URL (ws/2, JSON responses).
MUSICBRAINZ_API = 'https://musicbrainz.org/ws/2'

# Minimum seconds between MusicBrainz requests (their policy is 1 req/s).
MUSICBRAINZ_MIN_INTERVAL = 1.0

# AcoustID API key: ACOUSTID_KEY env var if set, else the shared public demo
# key (rate-limited — set your own for real workloads).
DEFAULT_ACOUSTID_KEY = os.environ.get('ACOUSTID_KEY', 'cSpUJKpD')

if not os.environ.get('ACOUSTID_KEY'):
    logger.warning(
        'ACOUSTID_KEY env var is unset — falling back to the shared public '
        'demo key, which is rate-limited and may be revoked. Set your own '
        'key for production use.')


def query_musicbrainz_artist(mbid):
    """Resolve an artist MBID via the MusicBrainz ws/2 API.

    Fetches the artist record including aliases; the first English
    "Legal name" alias becomes `real_name` (stage -> real name resolution).

    Returns:
        A dict with keys `mb_artist_id`, `name`, and `real_name` (None when
        no legal-name alias exists), plus `_error` on failure.
    """
    url = f"{MUSICBRAINZ_API}/artist/{mbid}"
    params = {'fmt': 'json', 'inc': 'aliases'}
    try:
        resp = requests.get(url, params=params,
                            headers={"User-Agent": "mp3-metadata-poc/1.0"},
                            timeout=10)
        time.sleep(MUSICBRAINZ_MIN_INTERVAL)  # honor 1 req/s policy
        if resp.status_code != 200:
            return {'_error': f"HTTP {resp.status_code}"}
        data = resp.json()
    except Exception as e:
        return {'_error': str(e)}

    real_name = None
    for alias in data.get('aliases', []):
        if alias.get('type') == 'Legal name' and alias.get('locale') in (None, 'en'):
            real_name = alias.get('name')
            break

    return {
        'mb_artist_id': data.get('id'),
        'name': data.get('name'),
        'real_name': real_name,
    }


def query_acoustid(mp3_path, api_key=None):
    """Use audio fingerprinting to identify a song from its audio data.

    Args:
        mp3_path: Path to the audio file to fingerprint.
        api_key: AcoustID API key. Falls back to DEFAULT_ACOUSTID_KEY
            (ACOUSTID_KEY env var, then the public demo key).
    """
    if not api_key:
        api_key = DEFAULT_ACOUSTID_KEY

    try:
        # Generate fingerprint and query AcoustID
        results = acoustid.match(api_key, mp3_path, meta='recordings releasegroups')

        for score, recording_id, title, artist in results:
            # Return the first result with a decent confidence score
            if score > 0.5:  # 50% confidence threshold
                # Try to get album and album artist information
                album = None
                albumartist = None
                try:
                    # Query MusicBrainz for more details
                    mb_url = f"https://musicbrainz.org/ws/2/recording/{recording_id}"
                    params = {'fmt': 'json', 'inc': 'releases+artist-credits'}
                    resp = requests.get(mb_url, params=params,
                                      headers={"User-Agent": "mp3-metadata-poc/1.0"},
                                      timeout=10)
                    time.sleep(MUSICBRAINZ_MIN_INTERVAL)  # honor 1 req/s policy
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get('releases') and len(data['releases']) > 0:
                            release = data['releases'][0]
                            album = release.get('title')
                            # Get album artist from release
                            if release.get('artist-credit'):
                                albumartist = release['artist-credit'][0]['name']

                        # Try to get track number from the recording
                        tracknumber = None
                        if data.get('releases') and len(data['releases']) > 0:
                            release = data['releases'][0]
                            if release.get('media') and len(release['media']) > 0:
                                tracks = release['media'][0].get('tracks', [])
                                for track in tracks:
                                    if track.get('recording', {}).get('id') == recording_id:
                                        tracknumber = track.get('position')
                                        break
                except Exception:
                    pass

                result = {
                    'artist': artist,
                    'albumartist': albumartist or artist,  # Fall back to track artist
                    'title': title,
                    'album': album,
                    'tracknumber': tracknumber,
                    'confidence': score
                }

                # Feature B: when the recording's artist credit carries an MBID,
                # enrich results with the MusicBrainz artist record (real name etc.)
                try:
                    mb_artist_id = None
                    if data.get('artist-credit'):
                        mb_artist_id = data['artist-credit'][0].get('artist', {}).get('id')
                except Exception:
                    mb_artist_id = None

                if mb_artist_id:
                    time.sleep(MUSICBRAINZ_MIN_INTERVAL)  # stay under 1 req/s
                    artist_info = query_musicbrainz_artist(mb_artist_id)
                    if '_error' not in artist_info:
                        result['mb_artist_id'] = artist_info['mb_artist_id']
                        if artist_info.get('real_name'):
                            logger.info("%s performs as '%s', real name: %s",
                                        artist_info['name'], artist, artist_info['real_name'])
                            result['real_name'] = artist_info['real_name']

                return result
    except acoustid.NoBackendError:
        logger.error("chromaprint/fpcalc not found. Install with: brew install chromaprint")
        return {'_error': 'No backend'}
    except acoustid.FingerprintGenerationError:
        logger.warning("Could not generate fingerprint for %s", mp3_path)
        return {'_error': 'Fingerprint failed'}
    except Exception as e:
        logger.warning("AcoustID lookup failed for %s: %s", mp3_path, e)
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
            logger.warning("iTunes API returned status code %d for search: %s",
                           resp.status_code, params['term'])
            return {'_error': f"HTTP {resp.status_code}"}
        data = resp.json()
        if data.get('results') and len(data['results']) > 0:
            result = data['results'][0]
            artist_name = result.get('artistName')
            album_artist = result.get('collectionArtistName') or artist_name
            return {
                'artist': artist_name,
                'albumartist': album_artist,
                'album': result.get('collectionName'),
                'title': result.get('trackName'),
                'tracknumber': str(result.get('trackNumber')) if result.get('trackNumber') else None
            }
        else:
            logger.warning("No results from iTunes API for search: %s", params['term'])
            return {'_error': "No results"}
    except Exception as e:
        logger.warning("iTunes API lookup failed for search '%s': %s",
                       params['term'], e)
        return {'_error': str(e)}
