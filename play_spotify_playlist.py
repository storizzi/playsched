#!/usr/bin/env python
# -*- coding: utf-8 -*-
# play_spotify_playlist.py

import spotipy
from spotipy.oauth2 import SpotifyOAuth
import os
import sys
import argparse
import sqlite3 # For database
import datetime # For timestamps
import pytz # For timezone conversion
from dotenv import load_dotenv
import json # For JSON export

# Try to import pandas, as it's needed for export; provide guidance if missing
try:
    import pandas as pd
except ImportError:
    # Pandas will be checked for specifically in the export function later
    # to provide a more context-specific message if the user tries to export.
    pass


# Load environment variables from .env file
# Ensure this is called early, before accessing os.getenv for credentials/market
load_dotenv()

# --- Configuration ---
DB_FILE = os.getenv('HISTORY_DB_FILE',os.getenv('SCHEDULE_DB_FILE','playsched.db')) # SQLite database file name for history and synced playlists
# *** Use the SAME cache path as playsched.py/scheduler.py ***
CACHE_PATH = os.getenv('SPOTIPY_CACHE_PATH', '.spotify_token_cache.json')

# Define the required scopes
SCOPES = "user-read-playback-state user-modify-playback-state playlist-read-private playlist-read-collaborative user-read-recently-played"

# --- Database Functions ---

def create_tables_if_not_exist(conn):
    """Creates the necessary database tables if they don't already exist."""
    cursor = conn.cursor()
    try:
        # Playback history table (existing)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS playback_history (
                played_at TEXT PRIMARY KEY,
                track_id TEXT NOT NULL,
                track_name TEXT,
                track_uri TEXT,
                artist_names TEXT,
                album_name TEXT,
                context_type TEXT,
                context_uri TEXT
            )
        ''')

        # Synced Playlists table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS synced_playlists (
                id TEXT PRIMARY KEY,
                name TEXT,
                uri TEXT,
                owner_display_name TEXT,
                api_total_tracks INTEGER,
                retrieved_at TEXT NOT NULL,
                is_removed_from_spotify BOOLEAN DEFAULT 0
            )
        ''')

        # Synced Playlist Tracks table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS synced_playlist_tracks (
                playlist_id TEXT NOT NULL,
                track_id TEXT NOT NULL,
                track_name TEXT,
                artist_names TEXT,
                track_uri TEXT,
                position INTEGER,
                added_to_playlist_at_spotify TEXT,
                last_seen_in_api_sync_at TEXT NOT NULL,
                is_removed_from_playlist BOOLEAN DEFAULT 0,
                PRIMARY KEY (playlist_id, track_id),
                FOREIGN KEY (playlist_id) REFERENCES synced_playlists(id) ON DELETE CASCADE
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_synced_playlist_tracks_playlist_id
            ON synced_playlist_tracks (playlist_id);
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_synced_playlists_is_removed
            ON synced_playlists (is_removed_from_spotify);
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_synced_playlist_tracks_is_removed
            ON synced_playlist_tracks (is_removed_from_playlist);
        ''')

        conn.commit()
        print("Database tables (including playback_history, synced_playlists, synced_playlist_tracks) checked/created.")
    except sqlite3.Error as e:
        print(f"Database error during table creation: {e}")
        raise

# --- (update_history_db, show_recent_playlists, sync_all_playlists_and_tracks functions remain the same) ---
def update_history_db(sp, conn):
    """Fetches recent playback history from Spotify and stores new entries in the DB."""
    print("\nFetching recent playback history from Spotify...")
    cursor = conn.cursor()
    added_count = 0
    skipped_count = 0
    try:
        results = sp.current_user_recently_played(limit=50)
        if not results or not results.get('items'):
            print("Could not retrieve recent playback history (or no history available).")
            return

        print(f"Retrieved {len(results['items'])} recent tracks. Processing...")

        for item in results['items']:
            played_at = item.get('played_at')
            track = item.get('track')
            context = item.get('context')

            if not played_at or not track:
                # Reduced verbosity
                # print(f"Skipping item due to missing played_at or track data: {item}")
                continue

            track_id = track.get('id')
            track_name = track.get('name')
            track_uri = track.get('uri')
            album_name = track['album']['name'] if track.get('album') else None
            artist_names = ", ".join([a['name'] for a in track.get('artists', []) if a.get('name')])
            context_type = context.get('type') if context else None
            context_uri = context.get('uri') if context else None

            sql = '''
                INSERT OR IGNORE INTO playback_history
                (played_at, track_id, track_name, track_uri, artist_names, album_name, context_type, context_uri)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            '''
            try:
                 cursor.execute(sql, (
                    played_at, track_id, track_name, track_uri, artist_names,
                    album_name, context_type, context_uri
                ))
                 if cursor.rowcount > 0: added_count += 1
                 else: skipped_count += 1
            except sqlite3.Error as e:
                print(f"Database error inserting row for track '{track_name}' at {played_at}: {e}")

        conn.commit()
        print(f"History update complete. Added: {added_count} new entries. Skipped (already present): {skipped_count} entries.")
        print("Note: Spotify API only provides the most recent ~50 played tracks per request.")

    except spotipy.exceptions.SpotifyException as e:
         print(f"Spotify API error fetching history: {e.msg} (HTTP Status: {e.http_status})")
    except Exception as e:
        print(f"An unexpected error occurred during history update: {e}")

def show_recent_playlists(sp, conn, market_code):
    """Queries the DB for recently played playlists and displays them."""
    print("\nQuerying database for recently played playlists...")
    cursor = conn.cursor()
    playlist_cache = {}
    try:
        sql = """
            SELECT context_uri, MAX(played_at) as last_played
            FROM playback_history
            WHERE context_type = 'playlist' AND context_uri IS NOT NULL
            GROUP BY context_uri ORDER BY last_played DESC LIMIT 50
        """
        cursor.execute(sql)
        results = cursor.fetchall()

        if not results:
            print("No playlist history found in the database.")
            print("Hint: Run the script with --update-history first.")
            return

        print("\n--- Recently Played Playlists (from stored history) ---")
        local_tz = pytz.timezone('Europe/Paris') # Assuming this is desired locale
        print(f"(Displaying times in {local_tz.zone} timezone)")

        for row in results:
            playlist_uri = row[0]
            last_played_utc_str = row[1]
            playlist_name = "Unknown Playlist"

            if playlist_uri in playlist_cache:
                 playlist_name = playlist_cache[playlist_uri]
            else:
                 try:
                      api_params = {'fields': 'name'}
                      if market_code: api_params['market'] = market_code
                      playlist_info = sp.playlist(playlist_uri, **api_params)
                      if playlist_info and playlist_info.get('name'):
                          playlist_name = playlist_info['name']
                          playlist_cache[playlist_uri] = playlist_name
                 except spotipy.exceptions.SpotifyException as e:
                      print(f"  Warning: Could not fetch name for {playlist_uri} (Market: {market_code}): {e.msg}")
                      playlist_name = f"Playlist (URI: {playlist_uri})"
                 except Exception as e:
                      print(f"  Warning: Error processing/fetching name for {playlist_uri}: {e}")
                      playlist_name = f"Playlist (URI: {playlist_uri})"

            try:
                if last_played_utc_str.endswith('Z'): ts_part = last_played_utc_str[:-1]
                else: ts_part = last_played_utc_str
                if '.' in ts_part:
                     base, micro = ts_part.split('.')
                     ts_part = f"{base}.{micro:<06}"
                dt_utc = datetime.datetime.fromisoformat(ts_part).replace(tzinfo=pytz.utc)
                dt_local = dt_utc.astimezone(local_tz)
                local_time_str = dt_local.strftime('%d/%m/%Y %H:%M:%S')
                print(f"- Name: {playlist_name}")
                print(f"  Last Played ({local_tz.zone} Time): {local_time_str}")
                print("-" * 10)
            except Exception as e:
                 print(f"  Error formatting time for {playlist_uri} ({last_played_utc_str}): {e}")
                 print(f"- Name: {playlist_name}")
                 print(f"  Last Played (UTC): {last_played_utc_str}")
                 print("-" * 10)
    except sqlite3.Error as e:
        print(f"Database error querying recent playlists: {e}")
    except Exception as e:
        print(f"An unexpected error occurred in show_recent_playlists: {e}")

def sync_all_playlists_and_tracks(sp, conn):
    """
    Fetches all user's playlists and their tracks from Spotify,
    and upserts them into the local database. Marks items as 'removed'
    if they are no longer found on Spotify, instead of deleting them.
    """
    print("\n--- Starting Full Playlist and Track Sync ---")
    cursor = conn.cursor()
    now_utc = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)
    now_utc_iso = now_utc.isoformat()

    cursor.execute("SELECT id FROM synced_playlists WHERE is_removed_from_spotify = 0")
    db_playlist_ids_active_before_sync = {row[0] for row in cursor.fetchall()}
    print(f"Found {len(db_playlist_ids_active_before_sync)} active playlists in DB before sync.")

    print("Fetching all user playlists from Spotify...")
    spotify_playlists_api_items = []
    offset = 0
    limit = 50
    while True:
        try:
            results = sp.current_user_playlists(limit=limit, offset=offset)
            if not results or not results.get('items'):
                break
            spotify_playlists_api_items.extend(results['items'])
            if results['next']:
                offset += limit
            else:
                break
        except spotipy.exceptions.SpotifyException as e:
            print(f"Spotify API error fetching user playlists: {e.msg}. Aborting sync.")
            return
        except Exception as e:
            print(f"Unexpected error fetching user playlists: {e}. Aborting sync.")
            return
    print(f"Retrieved {len(spotify_playlists_api_items)} playlists from Spotify API.")

    api_playlist_ids_this_sync = set()
    playlists_processed_count = 0

    for sp_playlist_item in spotify_playlists_api_items:
        if not sp_playlist_item or not sp_playlist_item.get('id'):
            print(f"Skipping a playlist item due to missing data or ID: {sp_playlist_item}")
            continue

        playlist_id = sp_playlist_item['id']
        api_playlist_ids_this_sync.add(playlist_id)
        playlist_name = sp_playlist_item.get('name', 'Unnamed Playlist')
        playlist_uri = sp_playlist_item.get('uri')
        owner_name = sp_playlist_item.get('owner', {}).get('display_name', 'N/A')
        api_total_tracks = sp_playlist_item.get('tracks', {}).get('total', 0)

        print(f"\nProcessing playlist: '{playlist_name}' (ID: {playlist_id})")

        try:
            cursor.execute("""
                INSERT INTO synced_playlists (id, name, uri, owner_display_name, api_total_tracks, retrieved_at, is_removed_from_spotify)
                VALUES (?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    uri = excluded.uri,
                    owner_display_name = excluded.owner_display_name,
                    api_total_tracks = excluded.api_total_tracks,
                    retrieved_at = excluded.retrieved_at,
                    is_removed_from_spotify = 0
            """, (playlist_id, playlist_name, playlist_uri, owner_name, api_total_tracks, now_utc_iso))
        except sqlite3.Error as e:
            print(f"  DB error upserting playlist '{playlist_name}': {e}")
            continue

        try:
            cursor.execute("""
                UPDATE synced_playlist_tracks
                SET is_removed_from_playlist = 1
                WHERE playlist_id = ?
            """, (playlist_id,))
        except sqlite3.Error as e:
            print(f"  DB error marking old tracks for playlist '{playlist_name}': {e}")
            continue

        print(f"  Fetching tracks for playlist '{playlist_name}'...")
        spotify_playlist_track_items = []
        track_offset = 0
        track_limit = 100
        current_position_in_playlist = 0
        while True:
            try:
                fields_param = "items(added_at,track(id,name,uri,artists(name))),next"
                track_results = sp.playlist_items(playlist_id, limit=track_limit, offset=track_offset, fields=fields_param)

                if not track_results or not track_results.get('items'):
                    break

                for item in track_results['items']:
                    if item and item.get('track') and item['track'].get('id'):
                        item['current_position_in_playlist'] = current_position_in_playlist
                        spotify_playlist_track_items.append(item)
                        current_position_in_playlist += 1
                if track_results['next']:
                    track_offset += track_limit
                else:
                    break
            except spotipy.exceptions.SpotifyException as e:
                print(f"  Spotify API error fetching tracks for playlist '{playlist_name}': {e.msg}. Skipping tracks for this playlist.")
                spotify_playlist_track_items = []
                break
            except Exception as e:
                print(f"  Unexpected error fetching tracks for playlist '{playlist_name}': {e}. Skipping tracks for this playlist.")
                spotify_playlist_track_items = []
                break
        print(f"  Retrieved {len(spotify_playlist_track_items)} valid tracks from Spotify API for playlist '{playlist_name}'.")

        tracks_synced_count_for_this_playlist = 0
        for item_data in spotify_playlist_track_items:
            track_info = item_data['track']
            track_id = track_info['id']
            track_name = track_info.get('name', 'N/A')
            track_uri = track_info.get('uri')
            artist_names = ", ".join([a['name'] for a in track_info.get('artists', []) if a.get('name')])
            added_at_spotify_ts = item_data.get('added_at')
            position = item_data['current_position_in_playlist']

            try:
                cursor.execute("""
                    INSERT INTO synced_playlist_tracks (
                        playlist_id, track_id, track_name, artist_names, track_uri,
                        position, added_to_playlist_at_spotify, last_seen_in_api_sync_at, is_removed_from_playlist
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                    ON CONFLICT(playlist_id, track_id) DO UPDATE SET
                        track_name = excluded.track_name,
                        artist_names = excluded.artist_names,
                        track_uri = excluded.track_uri,
                        position = excluded.position,
                        added_to_playlist_at_spotify = excluded.added_to_playlist_at_spotify,
                        last_seen_in_api_sync_at = excluded.last_seen_in_api_sync_at,
                        is_removed_from_playlist = 0
                """, (
                    playlist_id, track_id, track_name, artist_names, track_uri,
                    position, added_at_spotify_ts, now_utc_iso
                ))
                tracks_synced_count_for_this_playlist += 1
            except sqlite3.Error as e:
                print(f"  DB error upserting track ID {track_id} for playlist '{playlist_name}': {e}")
        print(f"  Upserted {tracks_synced_count_for_this_playlist} tracks for playlist '{playlist_name}' into DB.")
        playlists_processed_count += 1

    print(f"\nProcessed {playlists_processed_count} playlists from Spotify API.")

    removed_playlist_count = 0
    playlists_to_mark_as_globally_removed = db_playlist_ids_active_before_sync - api_playlist_ids_this_sync

    if playlists_to_mark_as_globally_removed:
        print(f"\nFound {len(playlists_to_mark_as_globally_removed)} playlists in DB that are no longer in Spotify. Marking them as removed...")
        for removed_playlist_id in playlists_to_mark_as_globally_removed:
            try:
                cursor.execute("""
                    UPDATE synced_playlists
                    SET is_removed_from_spotify = 1, retrieved_at = ?
                    WHERE id = ?
                """, (now_utc_iso, removed_playlist_id))
                cursor.execute("""
                    UPDATE synced_playlist_tracks
                    SET is_removed_from_playlist = 1, last_seen_in_api_sync_at = ?
                    WHERE playlist_id = ?
                """, (now_utc_iso, removed_playlist_id))
                removed_playlist_count +=1
                print(f"  Marked playlist ID {removed_playlist_id} and its tracks as removed.")
            except sqlite3.Error as e:
                print(f"  DB error marking playlist ID {removed_playlist_id} (and its tracks) as removed: {e}")
        print(f"Marked {removed_playlist_count} playlists (and their tracks) as removed because they are no longer on Spotify.")

    try:
        conn.commit()
        print("\n--- Full Playlist and Track Sync COMPLETED ---")
    except sqlite3.Error as e:
        print(f"Database commit error at the end of sync: {e}")
        print("WARNING: Some changes might not have been saved.")

# --- NEW EXPORT FUNCTION ---
def export_data_to_file(conn, filename):
    """Exports synced playlists and tracks from the database to the specified file."""
    print(f"\nAttempting to export data to '{filename}'...")
    
    try:
        # Ensure pandas is available (and openpyxl for .xlsx)
        pd_module = __import__('pandas')
    except ImportError:
        print("\nError: The 'pandas' library is required for the export functionality.")
        print("Please install it by running: pip install pandas")
        if filename.lower().endswith(".xlsx"):
            print("For Excel export, 'openpyxl' is also required: pip install openpyxl")
        return

    base_filename, extension = os.path.splitext(filename)
    extension = extension.lower()

    try:
        # Fetch data from synced_playlists
        playlists_df = pd_module.read_sql_query("SELECT * FROM synced_playlists", conn)
        # Fetch data from synced_playlist_tracks
        tracks_df = pd_module.read_sql_query("SELECT * FROM synced_playlist_tracks", conn)

        # Convert boolean (0/1) fields to True/False for better readability in export
        if 'is_removed_from_spotify' in playlists_df.columns:
            playlists_df['is_removed_from_spotify'] = playlists_df['is_removed_from_spotify'].astype(bool)
        if 'is_removed_from_playlist' in tracks_df.columns:
            tracks_df['is_removed_from_playlist'] = tracks_df['is_removed_from_playlist'].astype(bool)

        if extension == ".xlsx":
            try:
                __import__('openpyxl')
            except ImportError:
                print("\nError: The 'openpyxl' library is required for Excel (.xlsx) export.")
                print("Please install it by running: pip install openpyxl")
                return
            with pd_module.ExcelWriter(filename, engine='openpyxl') as writer:
                playlists_df.to_excel(writer, sheet_name='Playlists', index=False)
                tracks_df.to_excel(writer, sheet_name='Tracks', index=False)
            print(f"Data successfully exported to Excel file: {filename}")
        elif extension == ".csv":
            playlist_csv_filename = f"{base_filename}_playlists.csv"
            track_csv_filename = f"{base_filename}_tracks.csv"
            playlists_df.to_csv(playlist_csv_filename, index=False, encoding='utf-8')
            tracks_df.to_csv(track_csv_filename, index=False, encoding='utf-8')
            print(f"Data successfully exported to CSV files: {playlist_csv_filename} and {track_csv_filename}")
        elif extension == ".json":
            data_to_export = {
                "playlists": playlists_df.to_dict(orient='records'),
                "tracks": tracks_df.to_dict(orient='records')
            }
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data_to_export, f, ensure_ascii=False, indent=4)
            print(f"Data successfully exported to JSON file: {filename}")
        else:
            print(f"Error: Unsupported file extension '{extension}'. Please use .xlsx, .csv, or .json.")
            return

    except pd_module.io.sql.DatabaseError as e:
        print(f"Database error during export: {e}.")
        print("This might happen if the tables 'synced_playlists' or 'synced_playlist_tracks' do not exist.")
        print("Please run the --sync-playlists command first to populate these tables.")
    except Exception as e:
        print(f"An unexpected error occurred during export: {e}")


# --- (Spotify Client & Device/Playlist Finders remain the same) ---
def get_spotify_client():
    """Authenticates and returns a Spotipy client instance, using shared cache."""
    try:
        client_id = os.getenv("SPOTIPY_CLIENT_ID")
        client_secret = os.getenv("SPOTIPY_CLIENT_SECRET")
        redirect_uri = os.getenv("SPOTIPY_REDIRECT_URI")

        if not all([client_id, client_secret, redirect_uri]):
             print("\nError: SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET, and SPOTIPY_REDIRECT_URI")
             print("       must be set in your environment or .env file.")
             sys.exit(1)

        print(f"Using token cache path: {CACHE_PATH}")
        if not os.path.exists(CACHE_PATH):
             print(f"Cache file {CACHE_PATH} does not exist. Attempting first-time auth via browser.")
             print("Hint: Log in via the web application first to populate the cache.")

        print("Attempting authentication (will use cache first)...")
        auth_manager = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=SCOPES,
            cache_path=CACHE_PATH,
            open_browser=True
        )

        sp = spotipy.Spotify(auth_manager=auth_manager)
        user = sp.current_user()
        print(f"Authentication successful for user: {user.get('display_name', user.get('id'))}")
        print("(Likely using cached token if previously logged in via web app)")
        return sp

    except Exception as e:
        print(f"\nError during authentication/token retrieval: {e}")
        print("\nPlease ensure:")
        print(" 1. You have logged in successfully via the Web Application at least once.")
        print(" 2. Your Spotify credentials and Redirect URI environment variables are correct.")
        print(f" 3. The cache file '{CACHE_PATH}' exists and is accessible (if logged in before).")
        print(" 4. If a browser window opened, the auth flow may have failed (check Redirect URI in Spotify Dashboard matches .env EXACTLY, including https://).")
        sys.exit(1)

def list_devices(sp):
    """Lists available Spotify playback devices."""
    print("\nFetching available devices...")
    try:
        devices = sp.devices()
        if not devices or not devices.get('devices'):
            print("No active Spotify devices found.")
            print("Hint: Ensure Spotify is open and active on at least one device.")
            return

        available_devices = devices['devices']
        print("--- Available Devices ---")
        if not available_devices:
             print("(None found or active)")
        else:
            for i, device in enumerate(available_devices):
                active_status = " (Currently Active)" if device['is_active'] else ""
                volume = f" - Vol: {device.get('volume_percent', 'N/A')}%"
                print(f"- Name: {device['name']}")
                print(f"  Type: {device['type']}{active_status}{volume}")
                print(f"  ID:   {device['id']}")
                print("-" * 10)
    except Exception as e:
        print(f"Error fetching devices: {e}")

def list_playlists(sp):
    """Lists the current user's playlists (from Spotify API directly)."""
    print("\nFetching your playlists from Spotify API...")
    all_playlists = []
    try:
        offset = 0
        limit = 50
        while True:
            results = sp.current_user_playlists(limit=limit, offset=offset)
            if not results or not results.get('items'):
                break
            all_playlists.extend(results['items'])
            if results['next']:
                offset += limit
            else:
                break

        print(f"--- Your Playlists ({len(all_playlists)} found on Spotify) ---")
        if not all_playlists:
             print("(None found)")
        else:
            for i, playlist in enumerate(all_playlists):
                 owner = playlist['owner']['display_name']
                 collab = " (Collaborative)" if playlist['collaborative'] else ""
                 public = " (Public)" if playlist['public'] else " (Private)"
                 print(f"- Name: {playlist['name']}{collab}{public}")
                 print(f"  Owner: {owner}")
                 print(f"  Tracks: {playlist['tracks']['total']}")
                 print(f"  ID:   {playlist['id']}")
                 print(f"  URI:  {playlist['uri']}")
                 print("-" * 10)

    except Exception as e:
        print(f"Error fetching playlists: {e}")

def find_device(sp, device_name_query):
    """Finds an active device by name."""
    print(f"\nSearching for device containing '{device_name_query}'...")
    try:
        devices = sp.devices()
        if not devices or not devices.get('devices'):
            print("Error: No active Spotify devices found during search.")
            print("Hint: Ensure Spotify is open and active on the device.")
            return None

        available_devices = devices['devices']
        found_device = None

        for device in available_devices:
            if device_name_query.lower() == device['name'].lower():
                found_device = device
                print(f"Found exact match: {found_device['name']}")
                break

        if not found_device:
            partial_matches = []
            for device in available_devices:
                if device_name_query.lower() in device['name'].lower():
                    partial_matches.append(device)

            if len(partial_matches) == 1:
                 found_device = partial_matches[0]
                 print(f"Found unique partial match: {found_device['name']}")
            elif len(partial_matches) > 1:
                 print(f"Multiple devices found matching '{device_name_query}':")
                 for i, dev in enumerate(partial_matches):
                      print(f"  {i+1}: {dev['name']} ({dev['type']})")
                 while True:
                      try:
                          choice_str = input(f"  Enter number (1-{len(partial_matches)}): ")
                          choice = int(choice_str) - 1
                          if 0 <= choice < len(partial_matches):
                              found_device = partial_matches[choice]
                              break
                          else:
                              print("  Invalid choice number.")
                      except ValueError:
                          print("  Please enter a number.")

        if found_device:
            print(f"Selected device: {found_device['name']} (ID: {found_device['id']})")
            return found_device['id']
        else:
            print(f"\nError: Device containing '{device_name_query}' not found among active devices.")
            print("Available active devices listed below:")
            _list_devices_internal(available_devices)
            return None
    except Exception as e:
        print(f"Error searching for devices: {e}")
        return None

def _list_devices_internal(available_devices):
    """Helper to print devices from an existing list."""
    print("--- Currently Active Devices ---")
    if not available_devices:
         print("(None found or active)")
    else:
        for i, device in enumerate(available_devices):
            active_status = " (Currently Active)" if device['is_active'] else ""
            volume = f" - Vol: {device.get('volume_percent', 'N/A')}%"
            print(f"- Name: {device['name']}")
            print(f"  Type: {device['type']}{active_status}{volume}")
            print(f"  ID:   {device['id']}")
            print("-" * 10)

def find_playlist(sp, playlist_query):
    """Finds a playlist by name or URI/ID."""
    if playlist_query.startswith("spotify:playlist:") or len(playlist_query) == 22:
        playlist_uri = playlist_query
        if not playlist_uri.startswith("spotify:playlist:"):
             playlist_uri = f"spotify:playlist:{playlist_query}"
        print(f"\nVerifying playlist by URI/ID: {playlist_uri}")
        try:
            playlist = sp.playlist(playlist_uri, fields='name,uri,owner.display_name')
            owner_display = playlist.get('owner', {}).get('display_name', 'Unknown Owner')
            print(f"Found playlist: {playlist.get('name','Unnamed Playlist')} (Owner: {owner_display})")
            return playlist.get('uri')
        except spotipy.exceptions.SpotifyException as e:
            print(f"Error accessing playlist by URI/ID: {e.msg}")
            return None
        except Exception as e:
            print(f"An unexpected error occurred when fetching playlist by URI/ID: {e}")
            return None

    print(f"\nSearching for playlist matching '{playlist_query}'...")
    try:
        results = sp.search(q=playlist_query, type='playlist', limit=15)
        if not results or not results.get('playlists') or not isinstance(results['playlists'].get('items'), list):
             print(f"Error: Unexpected response structure from Spotify search for '{playlist_query}'.")
             return None
        playlists = results['playlists']['items']
        if not playlists:
            print(f"Error: No playlist found matching '{playlist_query}'.")
            return None
        valid_playlists = [p for p in playlists if p is not None]
        if not valid_playlists:
             print(f"Error: No valid playlist data found matching '{playlist_query}' after filtering.")
             return None
        if len(valid_playlists) == 1:
            selected_playlist = valid_playlists[0]
            owner_display = selected_playlist.get('owner', {}).get('display_name', 'Unknown Owner')
            print(f"Found unique playlist: {selected_playlist.get('name','Unnamed Playlist')} (Owner: {owner_display})")
            return selected_playlist.get('uri')
        else:
            print("\nMultiple playlists found. Please choose one:")
            for i, item in enumerate(valid_playlists):
                owner_name = "Unknown Owner"
                owner_info = item.get('owner')
                if owner_info and isinstance(owner_info, dict):
                    owner_name = owner_info.get('display_name', owner_name)
                playlist_name = item.get('name', 'Unnamed Playlist')
                print(f"{i + 1}: {playlist_name} (Owner: {owner_name})")
            while True:
                try:
                    choice_str = input(f"Enter number (1-{len(valid_playlists)}): ")
                    choice = int(choice_str) - 1
                    if 0 <= choice < len(valid_playlists):
                        selected_playlist = valid_playlists[choice]
                        selected_uri = selected_playlist.get('uri')
                        if selected_uri:
                             print(f"Selected: {selected_playlist.get('name', 'Unnamed Playlist')}")
                             return selected_uri
                        else:
                             print("Error: Selected playlist data is missing URI.")
                             return None
                    else:
                        print("Invalid choice number.")
                except ValueError:
                    print("Please enter a number.")
    except Exception as e:
        print(f"Error searching for playlists: {e}")
        return None

# --- Main Execution ---
if __name__ == "__main__":
    print("Note: For export functionality (--export-data), 'pandas' and 'openpyxl' (for Excel) libraries are required.")
    print("You can install them using: pip install pandas openpyxl\n")

    parser = argparse.ArgumentParser(
        description="Control Spotify playback, list items, manage history/playlists, or export synced data.",
        formatter_class=argparse.RawTextHelpFormatter
        )

    action_group = parser.add_mutually_exclusive_group()
    action_group.add_argument("--list-devices", action="store_true", help="List available playback devices.")
    action_group.add_argument("--list-playlists", action="store_true", help="List your playlists (direct from Spotify API).")
    action_group.add_argument("--update-history", action="store_true", help="Fetch recent plays and add to DB.")
    action_group.add_argument("--recent-playlists", action="store_true", help="Show recently played playlists from DB.")
    action_group.add_argument("--sync-playlists", action="store_true",
                              help="Sync all user playlists and tracks to local DB.")

    parser.add_argument("--device", type=str, help="Name of the device to play on (requires --playlist).")
    parser.add_argument("--playlist", type=str, help="Name, ID, or URI of the playlist to play (requires --device).")
    parser.add_argument("--export-data", type=str, metavar="FILENAME",
                        help="Export synced playlists and tracks to the specified file. \n"
                             "File type (xlsx, csv, json) determined by filename extension. \n"
                             "For CSV, two files: '<FILENAME>_playlists.csv' & '<FILENAME>_tracks.csv'.")
    args = parser.parse_args()

    # Determine primary intended action category
    is_playback_action = bool(args.device and args.playlist) # <--- CORRECTED LINE
    is_action_flag_present = any([
        args.list_devices, args.list_playlists, args.update_history,
        args.recent_playlists, args.sync_playlists
    ])
    is_export_action = args.export_data is not None

    # Mutual Exclusivity Checks for major action categories
    num_major_actions = sum([is_playback_action, is_action_flag_present, is_export_action])

    if num_major_actions > 1:
        parser.error("Error: Please specify only one major action category: \n"
                     "  1. Playback (using --device and --playlist together).\n"
                     "  2. An action flag (--list-devices, --sync-playlists, etc.).\n"
                     "  3. Data export (using --export-data FILENAME).\n"
                     "These categories cannot be combined.")
    
    if (args.device or args.playlist) and not is_playback_action:
        parser.error("Error: --device and --playlist must be used together for playback.")

    market_code = os.getenv('SPOTIPY_MARKET')
    if market_code: print(f"Using market code '{market_code}' from environment.")
    else: print("Market code not set (SPOTIPY_MARKET), API calls use default behavior.")

    needs_auth = is_action_flag_present or is_playback_action # Export doesn't need auth for Spotify API
    needs_db = args.update_history or args.recent_playlists or args.sync_playlists or is_export_action

    sp = None
    conn = None
    action_taken_or_attempted = False # To track if any primary action block was entered

    try:
        if needs_auth:
            sp = get_spotify_client()
            if not sp: sys.exit(1)

        if needs_db:
            print(f"Connecting to database: {DB_FILE}")
            conn = sqlite3.connect(DB_FILE)
            create_tables_if_not_exist(conn)

        # --- Action Handling ---
        if is_export_action:
            action_taken_or_attempted = True
            if conn:
                export_data_to_file(conn, args.export_data)
            else:
                # This case should ideally be prevented by needs_db logic or earlier checks
                print("Error: Database connection not available for export. Please ensure DB_FILE is configured.")
        
        elif is_action_flag_present:
            action_taken_or_attempted = True
            # Dispatch based on which flag from the action_group is True
            if args.list_devices: list_devices(sp)
            elif args.list_playlists: list_playlists(sp)
            elif args.update_history: update_history_db(sp, conn)
            elif args.recent_playlists: show_recent_playlists(sp, conn, market_code)
            elif args.sync_playlists: sync_all_playlists_and_tracks(sp, conn)
        
        elif is_playback_action:
            action_taken_or_attempted = True
            device_id = find_device(sp, args.device)
            playlist_uri = None
            if device_id: playlist_uri = find_playlist(sp, args.playlist)

            if device_id and playlist_uri:
                try:
                    print(f"\nAttempting to start playlist on device '{args.device}'...")
                    sp.start_playback(device_id=device_id, context_uri=playlist_uri)
                    print("Playback command sent successfully!")
                except spotipy.exceptions.SpotifyException as e:
                    print(f"\nError starting playback: {e.msg} (HTTP Status: {e.http_status})")
                    if "Restriction violated" in str(e.msg): print("Hint: Check device status/Premium.")
                except Exception as e: print(f"\nAn unexpected error occurred during playback: {e}")
            else: print("\nPlayback aborted: device or playlist not identified.")

        # If no major action category was specified by the user
        if num_major_actions == 0: # Implies no relevant args were given
             print("\nNo action specified.")
             parser.print_help()
        # If a major action was specified, but the internal logic didn't mark action_taken_or_attempted
        # (this scenario should be rare given the current structure but acts as a fallback)
        elif num_major_actions > 0 and not action_taken_or_attempted:
            print("\nAn action was specified, but it could not be dispatched. Please check arguments.")
            parser.print_help()

    finally:
        if conn:
            conn.close()
            print("\nDatabase connection closed.")