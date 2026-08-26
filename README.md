# MP3 Metadata Sync Script

## Overview

This script automatically syncs MP3 file metadata by:
1. Extracting information from filenames
2. **Using audio fingerprinting (AcoustID) to identify songs from their audio data**
3. Querying online music databases (iTunes API) as fallback for missing metadata
4. Enriching artist data via **MusicBrainz** (stage-name → real-name resolution)
5. **Optionally fetching and embedding cover art** via Discogs
6. Updating ID3 tags in MP3 files
7. **Organizing files into a folder structure: `<Artist>/<Album>/Artist - Album - <Track Number> - <Track Name>.mp3`**

## Filename Format

The script organizes files into a hierarchical folder structure where each filename carries its full context (self-describing and portable if files are ever moved out of the folder hierarchy):
```
<Artist>/<Album>/<Artist> - <Album> - <Track Number> - <Track Name>.mp3
```

Examples:
```
Coldplay/
  Parachutes/
    Coldplay - Parachutes - 01 - Don't Panic.mp3
    Coldplay - Parachutes - 02 - Shiver.mp3
    ...
    Coldplay - Parachutes - 05 - Yellow.mp3
    ...

The Beatles/
  Abbey Road/
    The Beatles - Abbey Road - 01 - Come Together.mp3
    The Beatles - Abbey Road - 02 - Something.mp3
    ...
```

Track numbers are automatically zero-padded to 2 digits (01, 02, etc.). If a track number is not available, the file is named `<Artist> - <Album> - <Track Name>.mp3`.

### Input Filename Recognition

The script can also parse metadata from input filenames in these formats:
- `AlbumArtist - Album - TrackNumber - Song.mp3` (e.g., `Coldplay - Parachutes - 05 - Yellow.mp3`)
- `AlbumArtist - Album - Song.mp3`
- `AlbumArtist - Song.mp3`
- `TrackNumber - Song.mp3` (e.g., `01 - Yellow.mp3`)

**Album Artist vs Artist:**
- **Album Artist** keeps albums together (used for folder organization)
- **Artist** is the individual track performer (preserved in metadata)
- For compilations, Album Artist is typically "Various Artists"
- For regular albums, Album Artist usually matches the main artist

Examples:
- `Coldplay/Parachutes/Coldplay - Parachutes - 05 - Yellow.mp3` (regular album)
- `Various Artists/8 Mile Soundtrack/Various Artists - 8 Mile Soundtrack - 01 - Lose Yourself.mp3` (compilation)
- `Linkin Park/Collision Course/Linkin Park - Collision Course - 06 - Numb_Encore.mp3` (collaboration album)

## How It Works

### 1. **File Scanning** (`scan_mp3_files`)
- Recursively walks through the specified folder
- Identifies all files with `.mp3` extension
- Returns a list of absolute file paths

### 2. **Filename Parsing** (`parse_filename`)
- Extracts metadata from filenames in multiple formats:
  - `AlbumArtist - Album - TrackNumber - Song.mp3` format (e.g., `Coldplay - Parachutes - 05 - Yellow.mp3`)
  - `AlbumArtist - Album - Song.mp3` format
  - `AlbumArtist - Song.mp3` format (when album is not present)
  - `TrackNumber - Song.mp3` format (e.g., `01 - Yellow.mp3`)
- Splits the filename on `" - "` (space-dash-space)
- Returns a dictionary with `albumartist`, `album`, `title`, and/or `tracknumber` keys
- The first part is treated as album artist to keep albums together when in 3/4-part format

### 3. **Audio Fingerprinting** (`query_acoustid`)
- Analyzes the actual audio data to identify songs (most accurate method)
- Uses AcoustID/Chromaprint to generate audio fingerprints
- Queries the AcoustID database (linked to MusicBrainz)
- Works even when files have completely wrong or missing metadata
- Returns artist, album artist, title, album, track number, and confidence score
- Album artist and track number are extracted from the album/release data in MusicBrainz
- Requires `chromaprint` (fpcalc) to be installed
- API key resolution: `--acoustid-key` CLI arg → `ACOUSTID_KEY` env var → shared public demo key (rate-limited; set your own for real workloads)
- **Production use requires your own key**: the built-in fallback is the public pyacoustid demo key — it is shared, rate-limited, and could be revoked at any time. A warning is logged at startup when it is in use. Get a free key at <https://acoustid.org/new-application> and set `ACOUSTID_KEY`.

### 4. **Text-Based Metadata Lookup** (`query_itunes_api`)
- Queries the iTunes Search API when metadata is missing or insufficient
- Searches using available artist, album, and/or title information
- Returns the best match from iTunes database including album and track number information
- Includes a 0.5-second delay to respect API rate limits
- Used as fallback when audio fingerprinting doesn't find a match

**Why iTunes API?**
The script originally used MusicBrainz but switched to iTunes API due to SSL/TLS compatibility issues between the Python SSL library and MusicBrainz servers.

### 4b. **Artist Enrichment** (`query_musicbrainz_artist`, `extract_mbid`)
- When a recording carries an artist MBID (from AcoustID's MusicBrainz link), the script enriches results with the MusicBrainz artist record.
- `extract_mbid()` pulls an artist MBID from tag values shaped like `MBID: <uuid>` or a bare UUID.
- `query_musicbrainz_artist()` fetches the artist via the MusicBrainz ws/2 API and resolves **stage names → real names** using the artist's "Legal name" alias (e.g. Elton John → Elton Hercules John).
- Honors MusicBrainz's 1 request/second policy (a `time.sleep(1)` after every request) and sends the required `User-Agent` header.

### 4c. **Cover Art** (`query_discogs_cover`, `download_image`, `embed_cover_art`)
- **Opt-in** via `--fetch-cover` so default behavior is unchanged.
- `query_discogs_cover()` searches Discogs for the highest-resolution cover using a Discogs token (`--discogs-token` or `DISCOGS_TOKEN` env var).
- `download_image()` fetches the artwork with a ~1 MB size cap to avoid pulling huge scans.
- `embed_cover_art()` writes the image as a front-cover `APIC` ID3 frame, replacing any existing cover while preserving other tags.

### 4. **Metadata Sync and Rename** (`sync_metadata_and_rename`)

This is the main processing function that:

#### Step 1: Fill from Filename
- If metadata fields (albumartist/album/title/tracknumber) are missing in the MP3 file
- Attempts to populate them from the parsed filename
- Also sets artist field if missing, using albumartist as fallback

#### Step 2: Audio Fingerprint Identification
- If fields are still missing or contain invalid values ("Unknown", "-", empty)
- Uses audio fingerprinting to analyze the actual audio data
- Identifies the song with high accuracy (typically >90% confidence)
- Updates metadata with results from AcoustID/MusicBrainz including track numbers

#### Step 3: Text-Based Online Lookup (Fallback)
- If audio fingerprinting doesn't find a match
- Queries iTunes API using available text information
- Updates any remaining missing fields including track numbers

#### Step 4: Save Changes
- Saves updated metadata to the MP3 file

#### Step 5: Organize into Folder Structure
- Creates directory structure: `Artist/Album/`
- Generates new filename: `<Artist> - <Album> - <Track Number> - <Track Name>.mp3`
- Track numbers are zero-padded to 2 digits (01, 02, etc.)
- If no track number available, uses `<Artist> - <Album> - <Track Name>.mp3`
- Moves file to the organized location
- Uses "not found" to mark metadata that couldn't be identified

## Technical Details

### Requirements
- Python 3.9+ (with OpenSSL support)
- `mutagen` library for MP3 metadata handling
- `requests` library for API calls
- `pyacoustid` library for audio fingerprinting
- `chromaprint` (fpcalc) for generating audio fingerprints
- `pytest` for running tests (development)
- A Discogs personal-access token (only for `--fetch-cover`)

### Content Verification
The script includes a `compute_checksum()` function that uses SHA256 hashing to verify file content is preserved during operations. This ensures audio data remains unchanged when metadata is updated or files are renamed.

### Installation
```bash
# Install chromaprint (required for audio fingerprinting)
brew install chromaprint

# Install Python dependencies
pip3 install --user mutagen requests pyacoustid

# (Optional) set your Discogs token for --fetch-cover
export DISCOGS_TOKEN="your-token-here"

# (Optional) set your AcoustID key for fingerprinting at higher rate limits
export ACOUSTID_KEY="your-key-here"
```

### Usage

#### Process Default Folder
```bash
# Run the script (processes ~/mp3-metadata-poc by default)
python3 update-mp3-metadata.py
```

#### Target a Specific Folder
```bash
# Process a specific folder
python3 update-mp3-metadata.py /path/to/your/music/folder

# Examples:
python3 update-mp3-metadata.py ~/Music/iTunes
python3 update-mp3-metadata.py "/Users/username/My Music Collection"
python3 update-mp3-metadata.py .
```

The script will:
- Recursively scan the specified folder for all `.mp3` files
- Display the total number of files found
- Process each file and show progress
- Display a completion message when done

#### Preview Changes (Dry Run)
```bash
python3 update-mp3-metadata.py ~/Music --dry-run
```

#### Inspect Existing Tags
```bash
# Fixed-width audit table (read-only)
python3 update-mp3-metadata.py ~/Music --inspect

# CSV output
python3 update-mp3-metadata.py ~/Music --inspect --csv
```

#### Skip Audio Fingerprinting
```bash
# Use filename parsing + iTunes text lookup only
python3 update-mp3-metadata.py ~/Music --skip-fingerprint
```

#### Use Your Own AcoustID Key
```bash
# Via CLI arg or ACOUSTID_KEY env var (demo key used otherwise)
python3 update-mp3-metadata.py ~/Music --acoustid-key "your-key"
```

#### Batch Mode
```bash
# Per-file progress counter + end-of-run summary
python3 update-mp3-metadata.py ~/Music --batch
```

#### Fetch & Embed Cover Art (Opt-in)
```bash
# Requires a Discogs token (--discogs-token or DISCOGS_TOKEN env var)
python3 update-mp3-metadata.py ~/Music --fetch-cover --discogs-token "your-token"
```

#### Verbose + Change History
```bash
# Detailed progress output
python3 update-mp3-metadata.py ~/Music --verbose

# Write a JSONL change-history in addition to the default JSON changelog
python3 update-mp3-metadata.py ~/Music --history-dir ./history
```

### Run Tests
```bash
# Run the full test suite
python3 -m pytest -q
```

The suite mocks all network access (MusicBrainz, Discogs, iTunes, AcoustID) so it runs offline and does not require API tokens.

The test suite verifies:
- File content preservation (checksum verification)
- Metadata parsing from filenames
- Filename sanitization
- Rename operations with logging
- Rollback capability
- Folder organization structure
- Track number formatting

Each test file includes comprehensive documentation describing:
- What features are being tested
- Testing approach (unit vs integration)
- Expected behavior and edge cases

## Web App

A local web app wraps the same engine with a SQLite-backed library index,
duplicate cleanup, and a **review-first** suggestion queue. Nothing is ever
applied without your explicit approval.

```bash
# Start the server (binds to 127.0.0.1:8000 only — never exposed beyond localhost)
source venv/bin/activate
python app.py
# then open http://127.0.0.1:8000
```

Three tabs:

- **Library** — scan a folder into the index (`library.db`), browse/search with
  pagination, play files inline.
- **Duplicates** — clusters candidates by tags, filename, and checksum; pick a
  keeper per cluster ("Delete others" → OS Trash) or "Keep all / dismiss".
- **Suggestions** — pending metadata proposals (filename parse → AcoustID →
  iTunes) shown as editable cards with source badges and confidence; edit,
  approve/reject individually or in batch, then "Apply approved".

Safety model:

- Every tag write / rename / delete appends to the same `changes_*.json`
  format the CLI uses — `python update-mp3-metadata.py --rollback <log>` keeps
  working on web-app batches.
- Deletions always go to the OS Trash via `send2trash`; nothing is permanently
  deleted, and nothing is auto-deleted.
- Applying renames refuses to overwrite existing target paths (reported as
  conflicts; the file stays put and the suggestion stays approved).
- The CLI continues to work unchanged off the shared `core/` package.

## Workflow Example

### Before:
```
/Music/
  track01.mp3
```
- Filename: Generic track name
- ID3 tags: All empty or corrupted

### Processing:
1. Parse filename: no useful information
2. Detect missing metadata
3. **Generate audio fingerprint from the actual audio data**
4. **Query AcoustID database**
5. **Match found: "Cannonball" by Damien Rice (97% confidence)**
6. Query MusicBrainz for album: "O", album artist: "Damien Rice", track: 2
7. Update ID3 tags with all fields (artist, albumartist, album, title, tracknumber)
8. Create folder structure and move file

### After:
```
/Music/
  Damien Rice/
    O/
      Damien Rice - O - 01 - Blower's Daughter.mp3
      Damien Rice - O - 02 - Cannonball.mp3
      Damien Rice - O - 03 - Volcano.mp3
      ...
```
- Folder: `Damien Rice/O/`
- Filename: `Damien Rice - O - 02 - Cannonball.mp3`
- ID3 tags: Artist = "Damien Rice", Album Artist = "Damien Rice", Album = "O", Title = "Cannonball", Track = "2"

## Limitations

- Audio fingerprinting requires songs to be in the AcoustID/MusicBrainz database
  - Very obscure, rare, or brand new releases may not be identified
  - Live recordings or heavily remixed versions may not match
- Files with generic titles may not find correct matches with text-based search
- iTunes API may not have all songs, especially rare or independent releases
- Track numbers may not always be accurate or available for all releases
- Rate limiting: delays between API requests
- Album information may not always be accurate for compilations or special editions
- Files will not be renamed/moved if metadata is insufficient to prevent file loss
- Metadata marked as "not found" indicates unsuccessful lookup through all methods
- Folder structure is always `Artist/Album/`; not configurable yet

## Future Enhancements

Possible improvements:
- Support for additional metadata fields (year, genre, track number)
- Multiple API fallbacks (Last.fm, etc.)
- Interactive mode to confirm changes before applying
- Configuration file for default folder paths and API preferences
- Resume capability for interrupted processing
- Batch size limiting

**Completed:**
- ✅ Audio fingerprinting for accurate matching (AcoustID/MusicBrainz)
- ✅ Dry-run mode to preview changes without modifying files
- ✅ Detailed logging to file with rollback capability
- ✅ Filename sanitization for invalid characters
- ✅ Content verification via checksums
- ✅ Test framework for protecting features
- ✅ `--inspect` read-only ID3 tag audit (table + CSV)
- ✅ `--skip-fingerprint` to skip AcoustID and use text lookup only
- ✅ JSONL change history (`--history-dir`) + verbose output (`--verbose`)
- ✅ `--batch` mode with per-file progress and summary
- ✅ MusicBrainz artist lookup with stage-name → real-name resolution
- ✅ Cover-art fetch & embed via Discogs (`--fetch-cover`, APIC frame)
