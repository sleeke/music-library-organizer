# Known Issues

## 1. Multiple Artists on Same Album - ✅ **RESOLVED**

**Previous Issue:** The filename format `Artist - Album - Song.mp3` caused problems when organizing by artist as the top-level differentiator, especially with compilation albums or albums featuring multiple artists.

**Solution Implemented (Feb 2026):**
The script now creates a hierarchical folder structure:
```
<Artist>/<Album>/Artist - Album - <Track Number> - <Track Name>.mp3
```

For compilation albums:
- Uses `albumartist` = "Various Artists" for the folder
- Individual track artists are preserved in metadata
- All tracks from the same album stay together

Example:
```
Various Artists/
  Now That's What I Call Music! 50/
    Various Artists - Now That's What I Call Music! 50 - 01 - Rolling in the Deep.mp3    (Adele)
    Various Artists - Now That's What I Call Music! 50 - 02 - Just the Way You Are.mp3   (Bruno Mars)
    Various Artists - Now That's What I Call Music! 50 - 03 - Firework.mp3               (Katy Perry)
```

**Benefits:**
- Keeps compilation albums together physically
- Standard approach used by most music players
- Individual track artists preserved in ID3 tags
- Track numbers maintain proper ordering

**Status:** ✅ **RESOLVED** - Folder organization implemented

**Issue:** Audio fingerprinting only works for songs in the AcoustID/MusicBrainz database.

**Workaround:** Falls back to text-based iTunes API search

---

## 3. iTunes API Rate Limiting

- Script may fail on large batch operations
- No official documentation on limits

**Current Mitigation:**
- 0.5 second delay between API requests
- Respectful usage to avoid blocks

**Workaround:** Process large libraries in smaller batches

---

## 4. Album Metadata Accuracy
- Special editions
- Reissues
- Region-specific releases

**Impact:** Files may be named with incorrect or generic album names

**Status:** Known limitation of source data
**Workaround:** Manual review and correction of album fields

---

## 5. Folder Organization Considerations

**Note:** The script now organizes files into `Artist/Album/Track - Title.mp3` structure.

**Considerations:**

### Empty Folders
- After moving files, original folders may be left empty
- The script does not automatically clean up empty folders
- Manual cleanup may be needed after processing

### Existing Folder Structures
- If you already have files organized in folders, they will be reorganized
- The script uses the base directory (containing the MP3s) as the root
- All files will be moved to `Artist/Album/` structure under that root

### Flat vs Hierarchical
- The script now creates hierarchical organization by default
- Not currently configurable (future enhancement)
- Better for large collections with many albums

### Track Number Availability
- Track numbers may not always be found in metadata
- Files without track numbers are named with just the title
- This can cause sorting issues for albums with missing track info

**Workaround:** Review albums without track numbers and add them manually if needed.

---

## 6. Risks When Running on Large Music Collections

**Critical Risks:**
- **Very long filenames:** Combined artist + album + title exceeding OS limits (255 chars on most systems)
- **Unicode/emoji:** Some filesystems may not handle certain characters properly
- **Case sensitivity:** macOS is case-insensitive by default; watch for conflicts
- **Power loss:** Files being written when interrupted could be corrupted

### C. Organizational Issues
- **False matches:** Wrong identification leads to incorrect metadata and filenames
- **Duplicate names:** Multiple files could end up with same name (prevented but skipped)
- **Lost originals:** No undo functionality - renamed files lose original names

### D. Performance Issues
- **Rate limiting:** iTunes API may throttle or block after many requests
- **Time:** Large collections take hours (0.5s delay per file + API time)
- **Memory:** Processing thousands of files could consume significant memory

---

## Safe Testing Strategy

### Phase 1: Backup Everything
```bash
# Create a complete backup of your music folder
cp -R ~/Music/YourMusicFolder ~/Music/YourMusicFolder_BACKUP_$(date +%Y%m%d)

### Phase 2: Test on Copy
```bash
# Test on a small subset copy (10-20 files)
mkdir ~/Music/TEST_BATCH
cp ~/Music/YourMusicFolder/*.mp3 ~/Music/TEST_BATCH/ | head -20
cd ~/mp3-metadata-poc && source venv/bin/activate
python "update-mp3-metadata.py" ~/Music/TEST_BATCH
```

### Phase 3: Manual Verification
- Check renamed files are correct
- Verify metadata with: `python -c "from mutagen.easyid3 import EasyID3; ..."`
- Look for files with "not found" - these need manual review
- Check for any error messages

### Phase 4: Test Edge Cases
Create test copies with:
- Very long artist/album/title names
- Files with no metadata at all
- Files already perfectly tagged
- Compilation albums with multiple artists
- Unicode/international characters

### Phase 5: Gradual Rollout
Process in batches:
```bash
# Process one artist folder at a time
python "update-mp3-metadata.py" ~/Music/YourMusicFolder/Artist1
# Verify, then continue
python "update-mp3-metadata.py" ~/Music/YourMusicFolder/Artist2
```

---

## Recommended Improvements Before Large-Scale Use

### 1. **Dry-Run Mode** (HIGH PRIORITY)
Add a `--dry-run` flag to preview changes without modifying files:
```bash
python "update-mp3-metadata.py" --dry-run ~/Music
```
Shows what would happen without actually changing anything.

### 2. **Filename Sanitization**
Automatically replace invalid characters:
- `/` → `_`
- `:` → `-`
- `*`, `?`, `"`, `<`, `>`, `|` → remove or replace

### 3. **Length Checking**
Warn or truncate filenames exceeding limits:
```python
if len(new_name) > 240:  # Leave buffer for path
    # Truncate or warn
```

### 4. **Backup/Undo Log**
Create a log of all changes:
```
original_path | new_path | timestamp | old_metadata | new_metadata
```
Enables reverting changes if needed.

### 5. **Progress Tracking**
- Save progress periodically
- Allow resuming from interruption
- Show estimated time remaining

### 6. **Batch Size Limiting**
Process max N files per run to avoid:
- API rate limits
- Memory issues
- Long-running processes

---

## Current Safeguards in Place

✅ **Prevents file overwrites** - Checks if target filename exists  
✅ **Skips insufficient metadata** - Won't rename if no artist/title  
✅ **Error handling** - Catches and reports API failures  
✅ **Marks unfound** - Uses "not found" for failed lookups  
✅ **Preserves originals on error** - Returns False, keeps file unchanged  
✅ **Dry-run mode** - Preview changes without modifying files  
✅ **Change logging** - JSON log of all changes for rollback  
✅ **Filename sanitization** - Replaces invalid characters automatically  
✅ **Content verification** - SHA256 checksums ensure audio data unchanged  
✅ **Test framework** - Automated tests protect against regressions (with comprehensive documentation)

## Missing Safeguards

❌ **No length checking** (though 240 char limit is enforced)  
❌ **No batch limiting**  
❌ **No progress saving/resuming**

---

## Recommendation

**DO NOT run on your entire collection yet.** 

Instead:
1. **Back up everything first** (non-negotiable)
2. **Test on 20-50 files** in a copy folder
3. **Manually verify results** - check 10+ files thoroughly
4. **Request dry-run mode implementation** (or implement yourself)
5. **Process one folder at a time** initially
6. **Keep backups** until confident all is correct

**Remaining priority improvements:**
1. Length validation (with warnings)
2. Batch size limiting
3. Progress saving/resuming

---

## Future Improvements

### Completed ✅
1. ~~Add support for `albumartist` metadata field~~ ✅ **IMPLEMENTED** (Feb 2026)
2. ~~Dry-run mode to preview changes~~ ✅ **IMPLEMENTED** (Feb 2026)
3. ~~Detailed logging to file~~ ✅ **IMPLEMENTED** (Feb 2026)
4. ~~Undo/rollback capability~~ ✅ **IMPLEMENTED** (Feb 2026)
5. ~~Filename sanitization~~ ✅ **IMPLEMENTED** (Feb 2026)
6. ~~Content verification (checksums)~~ ✅ **IMPLEMENTED** (Feb 2026)
7. ~~Test framework~~ ✅ **IMPLEMENTED** (Feb 2026)
8. ~~Folder organization (Artist/Album/ structure)~~ ✅ **IMPLEMENTED** (Feb 2026)
9. ~~Track number metadata support~~ ✅ **IMPLEMENTED** (Feb 2026)
10. ~~Test documentation~~ ✅ **IMPLEMENTED** (Feb 2026)

### Remaining
1. Implement configurable folder/filename formats
2. Add compilation album detection (auto-detect Various Artists)
3. Support for additional metadata fields (year, genre, disc number)
4. Interactive mode for user confirmation
5. Batch size limiting for API requests ⚠️ **HIGH PRIORITY**
6. Resume capability for interrupted processing
7. Multiple API source fallbacks
8. Length validation with warnings
9. Automatic cleanup of empty folders
