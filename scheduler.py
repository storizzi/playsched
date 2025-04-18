# scheduler.py
import os
import time
from datetime import datetime
import pytz # Required for timezone handling (pip install pytz)

from apscheduler.schedulers.background import BackgroundScheduler # Or BlockingScheduler
# from apscheduler.schedulers.blocking import BlockingScheduler
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotipy.exceptions import SpotifyException

# Import the database module to interact with schedules DB
import database

# --- Configuration ---
# Load credentials and settings from environment variables or a config file
CLIENT_ID = os.getenv('SPOTIPY_CLIENT_ID')
CLIENT_SECRET = os.getenv('SPOTIPY_CLIENT_SECRET')
REDIRECT_URI = os.getenv('SPOTIPY_REDIRECT_URI')
SCOPE = "user-modify-playback-state user-read-playback-state playlist-read-private user-read-currently-playing" # Match scopes needed
CACHE_PATH = os.getenv('SPOTIPY_CACHE_PATH', '.spotify_token_cache.json') # Ensure consistent cache path

# --- Spotify Client Retrieval ---
def get_scheduler_spotify_client(user_spotify_id, logger):
    """
    Gets an authenticated Spotipy client for the scheduler using the shared cache file.
    Manages token refresh automatically via SpotifyOAuth.
    user_spotify_id is mainly for clear log messages.
    """
    # Check if cache file exists before attempting auth
    if not os.path.exists(CACHE_PATH):
         logger.warning(f"Spotify cache file {CACHE_PATH} not found. Cannot authenticate for user {user_spotify_id}. User needs to log in via Flask app.")
         return None

    logger.info(f"Attempting to get Spotify client for user '{user_spotify_id}' using cache: {CACHE_PATH}")
    try:
        if not all([CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, SCOPE]):
             logger.error("Scheduler: Missing Spotify credentials/configuration in environment.")
             return None

        sp_oauth = SpotifyOAuth(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            redirect_uri=REDIRECT_URI,
            scope=SCOPE,
            cache_path=CACHE_PATH,
            open_browser=False
        )
        token_info = sp_oauth.get_cached_token()

        if token_info:
            logger.info(f"Scheduler: Successfully obtained token for user '{user_spotify_id}' via cache {CACHE_PATH}")
            sp = spotipy.Spotify(auth=token_info['access_token'])
            return sp
        else:
            logger.warning(f"Scheduler: Could not get token for user '{user_spotify_id}' from cache {CACHE_PATH}. Needs user re-authentication via main app.")
            return None
    except Exception as e:
        logger.error(f"Scheduler: Error getting Spotify client for user '{user_spotify_id}' via cache {CACHE_PATH}: {e}", exc_info=True)
        return None

# --- Database Interaction ---
def fetch_potentially_due_schedules_from_db(logger):
    """Fetches all active schedules from the database."""
    logger.debug("Fetching active schedules from database...")
    try:
        schedules = database.get_active_schedules_for_scheduler()
        logger.debug(f"Fetched {len(schedules)} active schedules.")
        return schedules
    except Exception as e:
        logger.error(f"Scheduler: Failed to fetch schedules from database: {e}", exc_info=True)
        return []

# --- Spotify Action Logic ---
def perform_spotify_action(sp, schedule, logger):
    """Execute the desired Spotify action based on schedule details."""
    # Assuming 'start_playback' is the primary action for now
    action = 'start_playback' # Can be extended based on DB field later if needed
    user_id = schedule.get('user_spotify_id')
    schedule_id = schedule.get('id')
    device_id = schedule.get('target_device_id')
    context_uri = schedule.get('playlist_uri')
    volume = schedule.get('volume') # Can be None
    shuffle_enabled = bool(schedule.get('shuffle_state', False))

    logger.info(f"Performing action '{action}' for schedule {schedule_id} (User: {user_id}), Shuffle: {shuffle_enabled}")

    try:
        playback_started = False
        if action == 'start_playback':
            if not context_uri:
                logger.warning(f"Schedule {schedule_id}: Cannot start playback, missing 'playlist_uri'.")
                return False # Indicate action failed
            logger.info(f"Starting playback of {context_uri}" + (f" on device {device_id}" if device_id else ""))

            # Set volume BEFORE starting playback if specified
            if volume is not None:
                    try:
                        logger.info(f"Setting volume to {volume}% for device {device_id}")
                        sp.volume(volume_percent=volume, device_id=device_id)
                        time.sleep(0.5)
                    except SpotifyException as vol_e:
                        logger.warning(f"Could not set volume for schedule {schedule_id}: {vol_e}")
                        if vol_e.http_status == 404: return False   # Device not found              

            # Start playback
            playback_params = {
                'device_id': device_id,
                'context_uri': context_uri
            }
            # *** ADD OFFSET if shuffle is OFF ***
            if not shuffle_enabled:
                playback_params['offset'] = {'position': 0} # Start at the first track (index 0)
                logger.info(f"Setting playback offset to track 0 for schedule {schedule_id} (Shuffle is OFF).")
            logger.debug(f"Attempting sp.start_playback for schedule {schedule_id} with params: {playback_params}")
            sp.start_playback(**playback_params)
            playback_started = True
            playback_command_sent_time = time.time()
            logger.info(f"Playback command sent for schedule {schedule_id}.")

            # --- Set Shuffle State Based on Schedule ---
            logger.info(f"Attempting to set shuffle state to {shuffle_enabled} for schedule {schedule_id}...")
            try:
                sleep_duration = 1.5 # Consistent delay
                time.sleep(sleep_duration)
                # Explicitly set shuffle state based on the boolean variable
                sp.shuffle(state=shuffle_enabled, device_id=device_id)
                shuffle_command_sent_time = time.time()
                logger.info(f"Shuffle state set to {shuffle_enabled} successfully for schedule {schedule_id} after {sleep_duration}s delay.")

                # Keep the state check for debugging/confirmation (optional but recommended)
                try:
                    check_delay = 0.5
                    time.sleep(check_delay)
                    current_state = sp.current_playback()
                    check_time = time.time()
                    if current_state and current_state.get('device') and current_state.get('device').get('id') == device_id:
                        api_shuffle_state = current_state.get('shuffle_state', 'N/A')
                        logger.info(f"Checked state {check_delay:.1f}s after shuffle command:")
                        logger.info(f"  API shuffle_state reported: {api_shuffle_state} (Expected: {shuffle_enabled})")
                        if api_shuffle_state != shuffle_enabled:
                             logger.warning(f"  --> Shuffle state mismatch: Command sent for {shuffle_enabled}, but API reports {api_shuffle_state}.")
                    # ... (rest of check logging) ...
                except Exception as check_e:
                     logger.warning(f"  Could not verify shuffle state after setting: {check_e}")

            except SpotifyException as shuffle_e:
                logger.warning(f"Could not set shuffle state to {shuffle_enabled} for schedule {schedule_id} (Device: {device_id}): {shuffle_e}")
            except Exception as general_shuffle_e:
                 logger.error(f"Unexpected error setting shuffle state for schedule {schedule_id}: {general_shuffle_e}", exc_info=True)
            # --- End Set Shuffle State ---

            return True # Playback was started

        else:
             logger.warning(f"Schedule {schedule_id}: Unknown action '{action}'.")
             return False

    except SpotifyException as e:
        logger.error(f"Spotify API error during action '{action}' for schedule {schedule_id} (User: {user_id}): {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during action '{action}' for schedule {schedule_id} (User: {user_id}): {e}", exc_info=True)
        return False

    except SpotifyException as e:
        logger.error(f"Spotify API error during action '{action}' for schedule {schedule_id} (User: {user_id}): {e}")
        if e.http_status == 404 and "Device not found" in str(e):
             logger.error(f"Device ID '{device_id}' not found or inactive.")
        elif e.http_status == 403:
             logger.error("Permission error (ensure device isn't private session, check scope).")
        # Handle other specific errors if needed
        return False
    except Exception as e:
        logger.error(f"Unexpected error during action '{action}' for schedule {schedule_id} (User: {user_id}): {e}", exc_info=True)
        return False

# --- Scheduler Job Definition ---
def check_schedules(logger):
    """Job run periodically to check for and execute OR stop due schedules."""
    logger.info("Scheduler: check_schedules job started.")
    now_utc = datetime.now(pytz.utc)
    all_active_schedules = fetch_potentially_due_schedules_from_db(logger)

    # --- Part 1: Check for Schedules to START ---
    due_to_start_schedules = []
    logger.debug("--- Checking schedules to START ---")
    for schedule in all_active_schedules:
        schedule_id = schedule['id']
        tz_str = schedule.get('timezone')
        start_time_str = schedule.get('start_time_local')
        days_of_week_str = schedule.get('days_of_week', "")

        # Ensure necessary fields exist
        if not tz_str or not start_time_str:
             logger.warning(f"[Start Check {schedule_id}]: Skipping - missing timezone or start_time.")
             continue

        try:
            schedule_tz = pytz.timezone(tz_str)
        except Exception as tz_e:
             logger.warning(f"[Start Check {schedule_id}]: Error processing timezone '{tz_str}': {tz_e}. Skipping.")
             continue

        now_local = now_utc.astimezone(schedule_tz)
        current_day_local = now_local.weekday()
        current_time_str = now_local.strftime("%H:%M")

        # 1. Check if the start time matches the current minute
        if start_time_str == current_time_str:
            is_due_today = False
            is_play_once = (days_of_week_str == "")

            # 2. Check if it's the right day or a valid play-once
            # ... (keep the existing day/play_once checking logic here) ...
            if is_play_once:
                if not schedule.get('play_once_triggered', False): is_due_today = True
                else: logger.debug(f"[Start Check {schedule_id}]: Skipping triggered play-once.")
            else:
                try:
                    scheduled_days = {int(day) for day in days_of_week_str.split(',') if day.strip()}
                    if current_day_local in scheduled_days: is_due_today = True
                except Exception as day_e:
                     logger.warning(f"[Start Check {schedule_id}]: Error processing days_of_week '{days_of_week_str}': {day_e}. Skipping.")
                     continue

            # 3. If it matches time/day/play_once, check if already triggered THIS minute
            if is_due_today:
                # ... (keep the existing last_triggered_utc check here to prevent re-triggering start) ...
                last_triggered_iso = schedule.get('last_triggered_utc')
                if last_triggered_iso:
                    try:
                        last_triggered_dt_utc = datetime.fromisoformat(last_triggered_iso.replace('Z', '+00:00'))
                        current_minute_start_local = now_local.replace(second=0, microsecond=0)
                        current_minute_start_utc = current_minute_start_local.astimezone(pytz.utc)
                        if last_triggered_dt_utc >= current_minute_start_utc:
                             logger.info(f"[Start Check {schedule_id}]: Skipping start, already triggered this minute.")
                             continue
                    except Exception as dt_e:
                         logger.warning(f"[Start Check {schedule_id}]: Error comparing last_triggered_utc: {dt_e}. Proceeding cautiously.")

                # Add to list if all checks pass
                logger.info(f"[Start Check {schedule_id}]: Determined DUE TO START.")
                due_to_start_schedules.append(schedule)

    # Process schedules due to START
    if not due_to_start_schedules:
        logger.info("Scheduler: No schedules due to START this cycle.")
    else:
        logger.info(f"Scheduler: Found {len(due_to_start_schedules)} schedule(s) to START.")

    for schedule in due_to_start_schedules:
        user_spotify_id = schedule['user_spotify_id']
        schedule_id = schedule['id']
        is_play_once = (schedule['days_of_week'] == "" or schedule['days_of_week'] is None)
        logger.info(f"Scheduler: Processing START for schedule ID {schedule_id} user {user_spotify_id}...")
        sp = get_scheduler_spotify_client(user_spotify_id, logger)
        if sp:
            action_success = perform_spotify_action(sp, schedule, logger)
            if action_success:
                try:
                    trigger_time_for_db = datetime.now(pytz.utc)
                    database.update_schedule_trigger_info(schedule_id, trigger_time_for_db.isoformat(), played_once=is_play_once)
                    logger.info(f"Updated trigger info for schedule {schedule_id} at {trigger_time_for_db.isoformat()}.")
                except Exception as db_e:
                    logger.error(f"Failed to update trigger info for schedule {schedule_id}: {db_e}")
            else:
                 logger.warning(f"Spotify start action failed for schedule {schedule_id}. Trigger info not updated.")
        else:
            logger.warning(f"Scheduler: Skipping START action for schedule {schedule_id} - could not get client.")


    # --- Part 2: Check for Schedules to STOP ---
    logger.debug("--- Checking schedules to STOP ---")
    due_to_stop_schedules_count = 0
    processed_stop_users = {} # Cache SP clients per user for this stop check run

    for schedule in all_active_schedules: # Iterate through all active schedules
        schedule_id = schedule['id']
        user_spotify_id = schedule['user_spotify_id']
        stop_time_str = schedule.get('stop_time_local')
        device_id = schedule.get('target_device_id')
        tz_str = schedule.get('timezone')
        playlist_uri_to_match = schedule.get('playlist_uri') # Get playlist URI for check

        # Only proceed if stop_time, device_id, tz_str exist
        if stop_time_str and device_id and tz_str:
            try:
                schedule_tz = pytz.timezone(tz_str)
                now_local = now_utc.astimezone(schedule_tz)
                current_time_str = now_local.strftime("%H:%M")

                # Check if current time matches the stop time
                if current_time_str == stop_time_str:
                    logger.info(f"[Stop Check {schedule_id}]: Stop time matches current time ({current_time_str} in {tz_str}). Checking playback state...")
                    due_to_stop_schedules_count += 1 # Increment potential count

                    # Get SP client (use cache if already fetched for this user in this run)
                    sp_stop = processed_stop_users.get(user_spotify_id)
                    if not sp_stop:
                        sp_stop = get_scheduler_spotify_client(user_spotify_id, logger)
                        if sp_stop:
                            processed_stop_users[user_spotify_id] = sp_stop # Cache it

                    if sp_stop:
                        try:
                            # --- Check Current Playback State ---
                            current_state = sp_stop.current_playback()
                            should_pause = False
                            if current_state and current_state.get('is_playing'):
                                current_device = current_state.get('device')
                                current_context = current_state.get('context')
                                current_item = current_state.get('item')

                                if current_device and current_device.get('id') == device_id:
                                    logger.info(f"[Stop Check {schedule_id}]: Playback is active on the target device ({device_id}).")
                                    # Optional but Recommended: Check if the context matches the schedule's playlist
                                    if current_context and current_context.get('uri') == playlist_uri_to_match:
                                        logger.info(f"[Stop Check {schedule_id}]: Playback context ({playlist_uri_to_match}) matches. Proceeding with pause.")
                                        should_pause = True
                                    elif not current_context and current_item:
                                        # If playing a single track (no context), maybe still pause? Your choice.
                                        # Let's pause based only on device for now, comment out context check if too strict
                                        logger.warning(f"[Stop Check {schedule_id}]: Playing a track directly (no playlist context). Pausing based on device match.")
                                        should_pause = True # Decide if you want this behaviour
                                    else:
                                        context_uri_playing = current_context.get('uri') if current_context else 'None'
                                        logger.info(f"[Stop Check {schedule_id}]: Skipping pause - playback context ({context_uri_playing}) does not match scheduled ({playlist_uri_to_match}).")
                                else:
                                     logger.info(f"[Stop Check {schedule_id}]: Skipping pause - playback is active, but not on target device ({device_id}).")
                            else:
                                 logger.info(f"[Stop Check {schedule_id}]: Skipping pause - Spotify reports no active playback.")

                            # --- Send Pause Command if Checks Pass ---
                            if should_pause:
                                logger.info(f"Attempting to PAUSE playback for schedule {schedule_id} on device {device_id}...")
                                try:
                                    sp_stop.pause_playback(device_id=device_id)
                                    logger.info(f"Pause command sent successfully for schedule {schedule_id}.")
                                    # NOTE: Still might send pause multiple times if interval < 1 min
                                except SpotifyException as pause_e:
                                     logger.warning(f"Could not send PAUSE command for schedule {schedule_id} (Device: {device_id}): {pause_e}")
                                except Exception as general_pause_e:
                                     logger.error(f"Unexpected error sending PAUSE command for schedule {schedule_id}: {general_pause_e}", exc_info=True)

                        except SpotifyException as state_e:
                             logger.warning(f"[Stop Check {schedule_id}]: Could not get current playback state: {state_e}")
                        except Exception as general_state_e:
                              logger.error(f"[Stop Check {schedule_id}]: Unexpected error checking playback state: {general_state_e}", exc_info=True)
                    else:
                         logger.warning(f"Scheduler: Skipping STOP action for schedule {schedule_id} - could not get client.")
                # else: # Current time doesn't match stop time (no need to log normally)
                #      pass

            except pytz.UnknownTimeZoneError:
                 logger.warning(f"[Stop Check {schedule_id}]: Skipping stop check due to unknown timezone '{tz_str}'.")
            except Exception as e:
                 logger.error(f"[Stop Check {schedule_id}]: Error during stop check: {e}", exc_info=True)

    if due_to_stop_schedules_count == 0:
         logger.info("Scheduler: No schedules potentially due to STOP this cycle.") # Adjusted message

    logger.info("Scheduler: check_schedules job finished.")
