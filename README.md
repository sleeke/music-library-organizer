# MP3 Metadata Sync Script

## Overview

This script automatically syncs MP3 file metadata by:
1. Extracting information from filenames
2. **Using audio fingerprinting (AcoustID) to identify songs from their audio data**
3. Querying online music databases (iTunes API) as fallback for missing metadata
4. Updating ID3 tags in MP3 files
5. Renaming files to match the metadata

## Filename Format

The script uses the following filename convention:
```
Artist - Album - Song.mp3
```

Examples:
- `Depeche Mode - Ultra (Deluxe) - It's no good.mp3`
- `Billy Club Sandwich - Superheroes At Leisure - Sandwiches.mp3`
- `Damien Rice - O - Cannonball.mp3`
- `Rock Master Scott & The Dynamic Three - Old School Rap 80s - Old School Rap 80s - The Roof Is On Fire.mp3`

## How It Works

### 1. **File Scanning** (`scan_mp3_files`)
- Recursively walks through the specified folder
- Identifies all files with `.mp3` extension
- Returns a list of absolute file paths

### 2. **Filename Parsing** (`parse_filename`)
- Extracts artist, album, and title from filenames using the `Artist - Album - Song.mp3` format
- Splits the filename on `" - "` (space-dash-space)
- Returns a dictionary with `artist`, `album`, and `title` keys
- Falls back to 2-part format (`Artist - Song.mp3`) if album is not present

### 3. **Audio Fingerprinting** (`query_acoustid`)
- Analyzes the actual audio data to identify songs (most accurate method)
- Uses AcoustID/Chromaprint to generate audio fingerprints
- Queries the AcoustID database (linked to MusicBrainz)
- Works even when files have completely wrong or missing metadata
- Returns artist, title, album, and confidence score
- Requires `chromaprint` (fpcalc) to be installed

### 4. **Text-Based Metadata Lookup** (`query_itunes_api`)
- Queries the iTunes Search API when metadata is missing or insufficient
- Searches using available artist, album, and/or title information
- Returns the best match from iTunes database including album information
- Includes a 0.5-second delay to respect API rate limits- Used as fallback when audio fingerprinting doesn't find a match
**Why iTunes API?**
The script originally used MusicBrainz but switched to iTunes API due to SSL/TLS compatibility issues between the Python SSL library and MusicBrainz servers.

### 4. **Metadata Sync and Rename** (`sync_metadata_and_rename`)

This is the main processing function that:

#### Step 1: Fill from Filename
- If metadata fields (artist/album/title) are missing in the MP3 file
- Attempts to populate them from the parsed filename

#### Step 2: Audio Fingerprint Identification
- If fields are still missing or contain invalid values ("Unknown", "-", empty)
- Uses audio fingerprinting to analyze the actual audio data
- Identifies the song with high accuracy (typically >90% confidence)
- Updates metadata with results from AcoustID/MusicBrainz

#### Step 3: Text-Based Online Lookup (Fallback)
- If audio fingerprinting doesn't find a match
- Queries iTunes API using available text information
- Updates any remaining missing fields

#### Step 4: Save Changes
- Saves updated metadata to the MP3 file

#### Step 4: Rename File
- Generates a new filename based on the final metadata: `{artist} - {album} - {title}.mp3`
- Renames the file if the current name doesn't match- Checks if target file already exists to prevent overwriting
- Skips rename if metadata is insufficient (no artist and no title)- Uses "Unknown" as fallback for missing values

## Technical Details

### Requirements
- Python 3.14 (with OpenSSL support)
- `mutagen` library for MP3 metadata handling
- `requests` library for API calls
- `pyacoustid` library for audio fingerprinting
- `chromaprint` (fpcalc) for generating audio fingerprints

### Installation
```bash
# Install chromaprint (required for audio fingerprinting)
brew install chromaprint

# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Install Python dependencies
pip install mutagen requests pyacoustid
```

### Usage

#### Process Default Folder
```bash
# Activate virtual environment
source venv/bin/activate

# Run the script (processes ~/mp3-metadata-poc by default)
python "import os.py"
```

#### Target a Specific Folder
```bash
# Activate virtual environment
source venv/bin/activate

# Process a specific folder
python "import os.py" /path/to/your/music/folder

# Examples:
python "import os.py" ~/Music/iTunes
python "import os.py" "/Users/username/My Music Collection"
python "import os.py" .
```

The script will:
- Recursively scan the specified folder for all `.mp3` files
- Display the total number of files found
- Process each file and show progress
- Display a completion message when done

## Workflow Example

### Before:
```
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
6. Query MusicBrainz for album: "O"
7. Update ID3 tags with all fields
8. Rename file

### After:
```
Damien Rice - O - Cannonball.mp3
```
- ID3 tags: Artist = "Damien Rice", Album = "O", Title = "Cannonball"

## Limitations

- Audio fingerprinting requires songs to be in the AcoustID/MusicBrainz database
  - Very obscure, rare, or brand new releases may not be identified
  - Live recordings or heavily remixed versions may not match
- Files with generic titles may not find correct matches with text-based search
- iTunes API may not have all songs, especially rare or independent releases
- Filename format should follow `Artist - Album - Song.mp3` convention for best results
  - Falls back to `Artist - Song.mp3` format if only 2 parts detected
- Rate limiting: delays between API requests
- Album information may not always be accurate for compilations or special editions
- Files will not be renamed if metadata is insufficient to prevent file loss

## Future Enhancements

Possible improvements:
- Support for additional metadata fields (year, genre, track number)
- Multiple API fallbacks (Last.fm, AcoustID, etc.)
- Audio fingerprinting for more accurate matching
- Interactive mode to confirm changes before applying
- Dry-run mode to preview changes without modifying files
- Configuration file for default folder paths and API preferences
- Resume capability for interrupted processing
- Detailed logging to file
