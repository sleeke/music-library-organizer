## Status

- Attempted processing `'/Volumes/SWAP-1/Music/[-UNSORTED-]/No Folders'`

## Next

- Review changes
  - Change log saved to: /Users/selwyn.leeke/mp3-metadata-poc/changes_20260216_211150.json
  - Processing complete! 14 file(s) had errors or could not be updated.

  - To undo these changes, run:
      ```
      python "update-mp3-metadata.py" --rollback /Users/selwyn.leeke/mp3-metadata-poc/changes_20260216_211150.json
      ```

- Suggested improvements
  - Does/should Metadata override file names, e.g. `'/Volumes/SWAP-1/Music/[-UNSORTED-]/No Folders/Andre Popp/[-UNSORTED-]/Andre Popp - El amor es triste.mp3'`
    - It's possible the metadata was already set, but perhaps it should have been updated from the fingerprint system?
      - Perhaps this can be done for some keywords, e.g. `[-UNSORTED-]`?