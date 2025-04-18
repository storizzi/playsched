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

# Load environment variables from .env file
# Ensure this is called early, before accessing os.getenv for credentials/market
load_dotenv()

# --- Configuration ---
DB_FILE = os.getenv('HISTORY_DB_FILE',os.getenv('SCHEDULE_DB_FILE','playsched.db')) # SQLite database file name for history
# *** Use the SAME cache path as playsched.py/scheduler.py ***
CACHE_PATH = os.getenv('SPOTIPY_CACHE_PATH', '.spotify_token_cache.json')

# Define the required scopes
# Ensure user-read-recently-played is present for history features
SCOPES = "user-read-playback-state user-modify-playback-state playlist-read-private playlist-read-collaborative user-read-recently-played"

# --- Database Functions ---

def create_tables_if_not_exist(conn):
    """Creates the necessary database tables if they don't already exist."""
    cursor = conn.cursor()
    try:
        # Playback history table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS playback_history (
                played_at TEXT PRIMARY KEY,      -- ISO 8601 timestamp from Spotify (UTC), unique identifier
                track_id TEXT NOT NULL,
                track_name TEXT,
                track_uri TEXT,
                artist_names TEXT,               -- Comma-separated artist names
                album_name TEXT,
                context_type TEXT,               -- e.g., 'playlist', 'album', 'artist' (can be NULL)
                context_uri TEXT                 -- URI of the context (can be NULL)
            )
        ''')
        conn.commit()
        print("Database tables checked/created.")
    except sqlite3.Error as e:
        print(f"Database error during table creation: {e}")
        raise

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

# --- Spotify Client & Device/Playlist Finders ---

# *** MODIFIED FUNCTION ***
def get_spotify_client():
    """Authenticates and returns a Spotipy client instance, using shared cache."""
    try:
        client_id = os.getenv("SPOTIPY_CLIENT_ID")
        client_secret = os.getenv("SPOTIPY_CLIENT_SECRET")
        redirect_uri = os.getenv("SPOTIPY_REDIRECT_URI") # Still needed for potential browser flow

        if not all([client_id, client_secret, redirect_uri]):
             print("\nError: SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET, and SPOTIPY_REDIRECT_URI")
             print("       must be set in your environment or .env file.")
             sys.exit(1)

        # Ensure cache path exists for logging/debugging
        print(f"Using token cache path: {CACHE_PATH}")
        if not os.path.exists(CACHE_PATH):
             print(f"Cache file {CACHE_PATH} does not exist. Attempting first-time auth via browser.")
             print("Hint: Log in via the web application first to populate the cache.")

        print("Attempting authentication (will use cache first)...")
        auth_manager = SpotifyOAuth(
            client_id=client_id,             # Pass explicitly
            client_secret=client_secret,     # Pass explicitly
            redirect_uri=redirect_uri,       # Pass explicitly (for browser fallback)
            scope=SCOPES,
            cache_path=CACHE_PATH,           # *** Use the shared cache file ***
            open_browser=True                # Allow browser for first time / if cache fails
        )

        # This will try cache first, then browser flow if needed/possible
        sp = spotipy.Spotify(auth_manager=auth_manager)

        # Verify authentication by making a simple call
        user = sp.current_user()
        print(f"Authentication successful for user: {user.get('display_name', user.get('id'))}")
        print("(Likely using cached token if previously logged in via web app)")
        return sp

    except Exception as e:
        # Catch potential errors during cache read or auth flow
        print(f"\nError during authentication/token retrieval: {e}")
        print("\nPlease ensure:")
        print(" 1. You have logged in successfully via the Web Application at least once.")
        print(" 2. Your Spotify credentials and Redirect URI environment variables are correct.")
        print(f" 3. The cache file '{CACHE_PATH}' exists and is accessible (if logged in before).")
        print(" 4. If a browser window opened, the auth flow may have failed (check Redirect URI in Spotify Dashboard matches .env EXACTLY, including https://).")
        sys.exit(1) # Exit if authentication fails

# --- (list_devices, list_playlists, find_device, _list_devices_internal, find_playlist functions remain the same as user provided) ---
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
                print("-" * 10) # Separator
    except Exception as e:
        print(f"Error fetching devices: {e}")

def list_playlists(sp):
    """Lists the current user's playlists."""
    print("\nFetching your playlists...")
    all_playlists = []
    try:
        offset = 0
        limit = 50 # Max limit per request
        while True:
            results = sp.current_user_playlists(limit=limit, offset=offset)
            if not results or not results.get('items'):
                break # No more playlists
            all_playlists.extend(results['items'])
            # Check if there's a next page URL provided by Spotify
            if results['next']:
                offset += limit # Prepare for the next page offset
            else:
                break # No more pages

        print(f"--- Your Playlists ({len(all_playlists)} found) ---")
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
                 print("-" * 10) # Separator

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

        # Try exact match first (case-insensitive)
        for device in available_devices:
            if device_name_query.lower() == device['name'].lower():
                found_device = device
                print(f"Found exact match: {found_device['name']}")
                break

        # If no exact match, try partial match (case-insensitive)
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
            # Call list_devices directly here to show options immediately
            _list_devices_internal(available_devices) # Use a helper to avoid redundant API call
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
    # Check if it's a Spotify URI or ID (logic remains the same)
    if playlist_query.startswith("spotify:playlist:") or len(playlist_query) == 22:
        # ... (keep the existing URI/ID checking logic here) ...
        playlist_uri = playlist_query
        if not playlist_uri.startswith("spotify:playlist:"):
             playlist_uri = f"spotify:playlist:{playlist_query}"
        print(f"\nVerifying playlist by URI/ID: {playlist_uri}")
        try:
            playlist = sp.playlist(playlist_uri, fields='name,uri,owner.display_name')
            # Add safe gets here too for consistency
            owner_display = playlist.get('owner', {}).get('display_name', 'Unknown Owner')
            print(f"Found playlist: {playlist.get('name','Unnamed Playlist')} (Owner: {owner_display})")
            return playlist.get('uri') # Return None if URI is missing
        except spotipy.exceptions.SpotifyException as e:
            print(f"Error accessing playlist by URI/ID: {e.msg}")
            return None
        except Exception as e:
            print(f"An unexpected error occurred when fetching playlist by URI/ID: {e}")
            return None

    # If not URI/ID, search by name
    print(f"\nSearching for playlist matching '{playlist_query}'...")
    try:
        results = sp.search(q=playlist_query, type='playlist', limit=15)

        # Check if results structure is valid before accessing items
        if not results or not results.get('playlists') or not isinstance(results['playlists'].get('items'), list):
             print(f"Error: Unexpected response structure from Spotify search for '{playlist_query}'.")
             return None

        playlists = results['playlists']['items']

        if not playlists: # Check if the items list is empty
            print(f"Error: No playlist found matching '{playlist_query}'.")
            return None

        # Filter out potential None items from the list first
        valid_playlists = [p for p in playlists if p is not None]

        if not valid_playlists:
             print(f"Error: No valid playlist data found matching '{playlist_query}' after filtering.")
             return None

        if len(valid_playlists) == 1:
            selected_playlist = valid_playlists[0]
            owner_display = selected_playlist.get('owner', {}).get('display_name', 'Unknown Owner')
            print(f"Found unique playlist: {selected_playlist.get('name','Unnamed Playlist')} (Owner: {owner_display})")
            return selected_playlist.get('uri') # Return None if URI missing
        else:
            # Handle multiple matches using the filtered list
            print("\nMultiple playlists found. Please choose one:")
            for i, item in enumerate(valid_playlists):
                # Now 'item' is guaranteed not to be None
                owner_name = "Unknown Owner"
                owner_info = item.get('owner')
                # Check owner_info is a dictionary before calling get
                if owner_info and isinstance(owner_info, dict):
                    owner_name = owner_info.get('display_name', owner_name)

                playlist_name = item.get('name', 'Unnamed Playlist')
                # Display using 1-based index for user
                print(f"{i + 1}: {playlist_name} (Owner: {owner_name})")

            # Input loop using the length of the valid list
            while True:
                try:
                    choice_str = input(f"Enter number (1-{len(valid_playlists)}): ")
                    # Convert user input (1-based) to 0-based index
                    choice = int(choice_str) - 1
                    if 0 <= choice < len(valid_playlists):
                        selected_playlist = valid_playlists[choice]
                        # Final check for URI before returning
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
    # Set up argument parser
    parser = argparse.ArgumentParser(
        description="Control Spotify playback, list items, or manage playback history.",
        formatter_class=argparse.RawTextHelpFormatter
        )

    # ... (argument parsing and validation logic remains the same) ...
    action_group = parser.add_mutually_exclusive_group()
    action_group.add_argument("--list-devices", action="store_true", help="List available playback devices.")
    action_group.add_argument("--list-playlists", action="store_true", help="List your playlists.")
    action_group.add_argument("--update-history", action="store_true", help="Fetch recent plays from Spotify and add new entries to the database.")
    action_group.add_argument("--recent-playlists", action="store_true", help="Show recently played playlists based on stored history (local time).")
    parser.add_argument("--device", type=str, help="Name (or partial name) of the device to play on.\n(Requires --playlist)")
    parser.add_argument("--playlist", type=str, help="Name, ID, or URI of the playlist to play.\n(Requires --device)")
    args = parser.parse_args()
    if (args.device or args.playlist) and not (args.device and args.playlist):
        parser.error("--device and --playlist must be used together for playback.")
    is_playback_action = args.device and args.playlist
    is_list_or_db_action = args.list_devices or args.list_playlists or args.update_history or args.recent_playlists
    if is_playback_action and is_list_or_db_action:
         parser.error("Playback arguments (--device, --playlist) cannot be used with action flags like --list-*, --update-history, etc.")


    market_code = os.getenv('SPOTIPY_MARKET')
    if market_code: print(f"Using market code '{market_code}' from environment.")
    else: print("Market code not set in environment (SPOTIPY_MARKET), API calls will use default behavior.")

    needs_auth = is_list_or_db_action or is_playback_action
    needs_db = args.update_history or args.recent_playlists

    sp = None
    conn = None
    action_taken = False

    try:
        if needs_auth:
            sp = get_spotify_client() # This now uses the cache path
            if not sp: sys.exit(1) # get_spotify_client now handles exit on failure

        if needs_db:
            print(f"Connecting to database: {DB_FILE}")
            conn = sqlite3.connect(DB_FILE)
            create_tables_if_not_exist(conn)

        # --- Action Handling (remains the same) ---
        if args.list_devices:
            list_devices(sp); action_taken = True
        elif args.list_playlists:
            list_playlists(sp); action_taken = True
        elif args.update_history:
            update_history_db(sp, conn); action_taken = True
        elif args.recent_playlists:
            show_recent_playlists(sp, conn, market_code); action_taken = True
        elif args.device and args.playlist:
            action_taken = True
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

        if not action_taken and not is_playback_action:
             print("\nNo action specified.")
             parser.print_help()

    finally:
        if conn:
            conn.close()
            print("\nDatabase connection closed.")