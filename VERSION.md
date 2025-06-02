# PlaySched Version History

## 0.1.1 - 2 Jun 2025 - Enhanced CLI Functionality

* **Playlist & Track Sync:** Added `--sync-playlists` command to `play_spotify_playlist.py` to fetch all user playlists (created and followed) and their tracks, storing them in new local database tables (`synced_playlists`, `synced_playlist_tracks`). Includes logic to mark items as "removed" if no longer found on Spotify, without deleting records.
* **Data Export:** Introduced `--export-data FILENAME` command to `play_spotify_playlist.py` allowing export of synced playlist and track data to Excel (`.xlsx`), CSV (two files), or JSON (`.json`) formats. Requires `pandas` and `openpyxl`.
* **Documentation:** Updated `README.md` to reflect new commands and added clarification on Spotify Developer App setup regarding the "Website" URL. Updated `requirements.txt` to include `pandas` and `openpyxl`. Updated `ROADMAP.md` to split spotify + non-spotify related features.

## 0.1.0 - 18 Apr 2025 - Initial Release

Initial release with basic functionality, including command line tool and web server connecting to database to store schedule, linking to Spotify API, find and selecting playlists for scheduling, and scheduling and editing / tracking playlists.