import spotipy
from spotipy.oauth2 import SpotifyOAuth
import os
from dotenv import load_dotenv
from flask import session, url_for, current_app # Use Flask session for token storage
import time

load_dotenv()

# Use the same scopes defined elsewhere or define specifically for web
WEB_SCOPES = "user-read-playback-state user-modify-playback-state playlist-read-private playlist-read-collaborative user-read-private user-read-email user-read-currently-playing user-read-recently-played"
CACHE_PATH = os.getenv('SPOTIPY_CACHE_PATH', '.spotify_token_cache.json')

# Store auth manager globally or pass around - global makes routes easier
# Ensure redirect_uri matches the one in .env and Flask route
auth_manager = SpotifyOAuth(
    client_id=os.getenv("SPOTIPY_CLIENT_ID"),
    client_secret=os.getenv("SPOTIPY_CLIENT_SECRET"),
    redirect_uri=os.getenv("SPOTIPY_REDIRECT_URI"),
    scope=WEB_SCOPES,
    cache_path=CACHE_PATH # Don't use file cache for web app, rely on session
)

print(f"SpotifyOAuth initialized with redirect_uri: {os.getenv('SPOTIPY_REDIRECT_URI')}")

def get_auth_url():
    """Gets the Spotify authorization URL."""
    # Add show_dialog=True if you want user to always approve permissions
    return auth_manager.get_authorize_url()

def get_token_from_code(code):
    """Exchanges authorization code for tokens and stores them in session."""
    try:
        token_info = auth_manager.get_access_token(code, check_cache=False)
        session['spotify_token_info'] = token_info
        # Also get user profile to store ID
        sp = spotipy.Spotify(auth=token_info['access_token'])
        user_info = sp.current_user()
        session['spotify_user_id'] = user_info['id']
        session['spotify_user_display_name'] = user_info.get('display_name', user_info['id'])
        return True
    except Exception as e:
        current_app.logger.error(f"Error getting token from code: {e}")
        return False

def get_refreshed_token():
    """Checks if token needs refresh, refreshes if needed, returns token_info."""
    token_info = session.get('spotify_token_info')
    if not token_info:
        return None # User not authenticated

    now = int(time.time())
    is_expired = token_info['expires_at'] - now < 60 # Refresh if expires in < 60 seconds

    if is_expired:
        try:
            token_info = auth_manager.refresh_access_token(token_info['refresh_token'])
            session['spotify_token_info'] = token_info
            current_app.logger.info("Spotify token refreshed.")
        except Exception as e:
            current_app.logger.error(f"Error refreshing token: {e}")
            # Could potentially redirect to login here if refresh fails badly
            session.pop('spotify_token_info', None)
            session.pop('spotify_user_id', None)
            session.pop('spotify_user_display_name', None)
            return None
    return token_info

def get_spotify_client():
    """Returns an authenticated Spotipy client instance using session token."""
    token_info = get_refreshed_token()
    if not token_info:
        return None # Not authenticated or token refresh failed
    try:
        return spotipy.Spotify(auth=token_info['access_token'])
    except Exception as e:
        current_app.logger.error(f"Error creating spotipy client: {e}")
        return None

# --- Wrapper functions for API calls ---

# In spotify_client.py

# Keep this function (or rename the original one back)
def get_all_user_playlists(sp):
    """Gets ALL playlists for the current user using pagination internally."""
    if not sp: return None
    all_playlists = []
    offset = 0
    limit = 50 # Fetch 50 at a time (max)
    while True:
        try:
            results = sp.current_user_playlists(limit=limit, offset=offset)
            if not results or not results['items']:
                break # No more items
            all_playlists.extend(results['items'])
            if results['next']:
                # Prepare offset for next iteration
                # Note: sp.current_user_playlists uses limit/offset, so incrementing offset is correct
                offset += limit
            else:
                break # No more pages
        except spotipy.exceptions.SpotifyException as e:
             current_app.logger.error(f"Spotify API error fetching playlists page (offset={offset}): {e.msg}")
             return None # Indicate error if any page fails
        except Exception as e:
            current_app.logger.error(f"Error fetching user playlists page (offset={offset}): {e}")
            return None # Indicate error
    # Successfully fetched all pages
    current_app.logger.info(f"Fetched a total of {len(all_playlists)} playlists.")
    return all_playlists

def start_playback(sp, device_id, playlist_uri, volume=None):
    """Starts playlist playback on a device, optionally sets volume."""
    if not sp: return False
    try:
        context_uri = playlist_uri # Assuming URI is passed
        sp.start_playback(device_id=device_id, context_uri=context_uri)
        current_app.logger.info(f"Playback started: {playlist_uri} on {device_id}")
        # Set volume *after* starting playback
        if volume is not None and isinstance(volume, int) and 0 <= volume <= 100:
            time.sleep(1) # Short delay might help ensure playback has started
            try:
                sp.volume(volume, device_id=device_id)
                current_app.logger.info(f"Volume set to {volume} on {device_id}")
            except Exception as vol_e:
                current_app.logger.warning(f"Could not set volume after starting playback: {vol_e}")
        return True
    except Exception as e:
        current_app.logger.error(f"Error starting playback: {e}")
        return False

def stop_playback(sp, device_id):
    """Stops playback on a specific device."""
    # Note: Spotify API doesn't have a dedicated "stop". Pause is the standard way.
    if not sp: return False
    try:
        sp.pause_playback(device_id=device_id)
        current_app.logger.info(f"Playback paused (stopped) on device {device_id}")
        return True
    except Exception as e:
        # Handle specific errors e.g., if device not found or playback not active
        current_app.logger.error(f"Error pausing playback on {device_id}: {e}")
        return False

def get_user_devices(sp):
    """Gets available playback devices for the current user."""
    if not sp:
        current_app.logger.error("get_user_devices called without valid sp client")
        return None # Indicate error: No client
    try:
        # Call the spotipy method to get devices
        devices_info = sp.devices()

        # Check if the response structure is as expected
        if devices_info and isinstance(devices_info.get('devices'), list):
            return devices_info['devices'] # Return the list of device objects
        else:
            # Log if the structure is weird or if the 'devices' key is missing/not a list
            current_app.logger.warning(f"sp.devices() returned unexpected structure or no devices list: {devices_info}")
            return [] # Return empty list - consistent with no devices found
            
    except spotipy.exceptions.SpotifyException as e:
         # Log Spotify specific errors (like auth issues, rate limits, bad requests)
         current_app.logger.error(f"Spotify API error fetching devices: {e.msg} (HTTP Status: {e.http_status})")
         return None # Indicate error: API error
    except Exception as e:
        # Log other unexpected errors during the process
        current_app.logger.error(f"Unexpected error fetching user devices: {e}", exc_info=True) # Log traceback
        return None # Indicate error: Other error