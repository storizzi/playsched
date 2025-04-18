import os
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, current_app
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
import atexit
import logging
import pytz
from datetime import datetime, time, timedelta
import time as _time

# Import local modules
import spotify_client
from spotipy.exceptions import SpotifyException
import database
import scheduler # Import the scheduler module containing the check function

load_dotenv()

# Basic logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "DEFAULT_FALLBACK_SECRET_KEY_CHANGE_ME") # Use a default ONLY for dev if not set
# Configure Flask-Session (example using filesystem session type)
# pip install Flask-Session
# from flask_session import Session
# app.config["SESSION_PERMANENT"] = False
# app.config["SESSION_TYPE"] = "filesystem"
# Session(app)
# If not using Flask-Session, default Flask session management will use signed cookies

# Initialize Scheduler
scheduler_interval = int(os.getenv('SCHEDULER_INTERVAL_SECONDS', 60))
background_scheduler = BackgroundScheduler(daemon=True)
background_scheduler.add_job(
    func=scheduler.check_schedules, # The function to call
    args=[app.logger],
    trigger='interval',
    seconds=scheduler_interval,
    id='schedule_check_job'
)
background_scheduler.start()
# Shut down the scheduler when exiting the app
atexit.register(lambda: background_scheduler.shutdown())

def calculate_next_play_time_utc(schedule, now_utc):
    """
    Calculates the next run time for a schedule in UTC (Revised Logic).
    Returns a datetime object (UTC) or None if inactive/past play-once.
    """
    logger = current_app.logger if current_app else logging.getLogger(__name__)
    schedule_id_log = schedule.get('id', 'N/A')

    logger.info(f"[Calc {schedule_id_log}]: --- Starting Calculation (REVISED LOGIC) ---")
    logger.debug(f"[Calc {schedule_id_log}]: Input Schedule Data: {dict(schedule)}")
    logger.debug(f"[Calc {schedule_id_log}]: Current Time UTC: {now_utc.isoformat()}")

    if not isinstance(schedule, dict):
         logger.error(f"[Calc {schedule_id_log}]: Invalid schedule format. Returning None.")
         return None

    is_active_val = schedule.get('is_active')
    if not is_active_val:
        logger.info(f"[Calc {schedule_id_log}]: Returning None - Schedule inactive.")
        return None

    tz_str = schedule.get('timezone')
    start_time_str = schedule.get('start_time_local')
    days_of_week_str = schedule.get('days_of_week', "")
    is_play_once = (days_of_week_str == "")
    play_once_triggered = schedule.get('play_once_triggered', False)

    if not tz_str or not start_time_str:
        logger.warning(f"[Calc {schedule_id_log}]: Returning None - Missing timezone or start_time_local.")
        return None

    if is_play_once and play_once_triggered:
        logger.info(f"[Calc {schedule_id_log}]: Returning None - Play-once triggered.")
        return None

    try:
        schedule_tz = pytz.timezone(tz_str)
        start_time_local_obj = time.fromisoformat(start_time_str) # Keep as time object
        scheduled_days = set()
        if not is_play_once:
            if days_of_week_str:
                 scheduled_days = {int(day) for day in days_of_week_str.split(',') if day.strip()}
            else:
                 logger.warning(f"[Calc {schedule_id_log}]: Returning None - Repeating schedule has empty days_of_week.")
                 return None
    except Exception as e:
        logger.error(f"[Calc {schedule_id_log}]: Returning None - Error parsing schedule data: {e}", exc_info=True)
        return None

    # Get current date in UTC to start iteration
    current_date_utc = now_utc.date()

    for i in range(8): # Check today + next 7 days
        # We iterate based on UTC dates, but check against local day/time
        check_date_utc = current_date_utc + timedelta(days=i)

        # Create a naive datetime by combining the UTC date and local start time
        # This is just a preliminary step
        try:
             naive_potential_dt = datetime.combine(check_date_utc, start_time_local_obj)
        except Exception as combine_e:
             logger.error(f"[Calc {schedule_id_log}]: Error combining date {check_date_utc} / time {start_time_local_obj}: {combine_e}. Skipping day {i}.")
             continue

        # *** Explicitly Localize the naive datetime using the schedule's timezone ***
        try:
            localized_potential_dt = schedule_tz.localize(naive_potential_dt, is_dst=None) # is_dst=None handles ambiguity/non-existent times
        except (pytz.AmbiguousTimeError, pytz.NonExistentTimeError) as loc_e:
             logger.warning(f"[Calc {schedule_id_log}]: Timezone localization issue for {naive_potential_dt} in {tz_str}: {loc_e}. Skipping potential time.")
             # Optionally, try is_dst=True/False or add/subtract an hour if needed, but skipping is safer
             continue
        except Exception as e:
             logger.error(f"[Calc {schedule_id_log}]: Error localizing time {naive_potential_dt} in {tz_str}: {e}. Skipping day {i}.")
             continue


        potential_dt_utc = localized_potential_dt.astimezone(pytz.utc) # Convert localized time to UTC
        potential_weekday_local = localized_potential_dt.weekday() # Get weekday from the localized time

        logger.debug(f"[Calc {schedule_id_log}]: Checking Day {i}: DateUTC={check_date_utc}, PotentialLocal={localized_potential_dt.isoformat()}, PotentialUTC={potential_dt_utc.isoformat()}, LocalWeekday={potential_weekday_local}")

        is_scheduled_day = False
        if is_play_once:
             # Only consider play-once if the potential time is today (in local time) relative to the original now_local
             # We need now_local for this check
             now_local_check = now_utc.astimezone(schedule_tz)
             if localized_potential_dt.date() == now_local_check.date():
                  is_scheduled_day = True
             else:
                   continue # Play once relevant only for 'today'
        elif potential_weekday_local in scheduled_days:
            is_scheduled_day = True

        if not is_scheduled_day:
             logger.debug(f"[Calc {schedule_id_log}]: Day {potential_weekday_local} is not scheduled.")
             continue

        # Compare potential UTC time directly with current UTC time
        if potential_dt_utc > now_utc:
            logger.info(f"[Calc {schedule_id_log}]: Found next future UTC time: {potential_dt_utc.isoformat()}. Returning.")
            return potential_dt_utc # Return the calculated UTC time

        logger.debug(f"[Calc {schedule_id_log}]: Potential UTC time {potential_dt_utc.isoformat()} is in the past.")


    logger.warning(f"[Calc {schedule_id_log}]: Returning None - Could not find valid future run time within 7 days (Revised Logic).")
    return None

# --- Routes ---

@app.route('/')
def index():
    # Check if user is logged in via session
    if 'spotify_user_id' not in session:
        return render_template('index.html', logged_in=False)
    return render_template('index.html',
                           logged_in=True,
                           display_name=session.get('spotify_user_display_name', 'User'))

@app.route('/login')
def login():
    auth_url = spotify_client.get_auth_url()
    return redirect(auth_url)

@app.route('/logout')
def logout():
    session.pop('spotify_token_info', None)
    session.pop('spotify_user_id', None)
    session.pop('spotify_user_display_name', None)
    return redirect(url_for('index'))

@app.route('/callback')
def callback():
    code = request.args.get('code')
    if not code:
        return "Error: No code provided in callback.", 400
    success = spotify_client.get_token_from_code(code)
    if success:
        return redirect(url_for('index'))
    else:
        return "Error: Could not fetch token from Spotify.", 500

# --- API Routes ---

@app.before_request
def before_request_hook():
    # Exclude auth routes from requiring login for API calls
    if request.endpoint and 'api.' in request.endpoint and \
       request.endpoint not in ['api.get_auth_url', 'api.callback', 'api.auth_status']:
        if 'spotify_user_id' not in session:
            return jsonify({"error": "User not authenticated"}), 401
        # Optional: Refresh token before API call if needed, though get_spotify_client handles it
        # spotify_client.get_refreshed_token()

# --- API Auth Status ---
@app.route('/api/auth/status', methods=['GET'])
def api_auth_status():
    if 'spotify_user_id' in session and spotify_client.get_refreshed_token():
         # Check if token is valid/refreshable
        return jsonify({
            "logged_in": True,
            "user_id": session['spotify_user_id'],
            "display_name": session.get('spotify_user_display_name', 'User')
        }), 200
    else:
        # Clear potentially stale session data if token check fails
        session.pop('spotify_token_info', None)
        session.pop('spotify_user_id', None)
        session.pop('spotify_user_display_name', None)
        return jsonify({"logged_in": False}), 200

# --- API Spotify Data Fetching ---
@app.route('/api/playlists', methods=['GET'])
def api_get_playlists():
    # This endpoint now returns ALL playlists
    sp = spotify_client.get_spotify_client()
    if not sp: return jsonify({"error": "Authentication required or failed"}), 401

    try:
        # Call the function that gets ALL playlists
        playlists = spotify_client.get_all_user_playlists(sp)

        if playlists is None:
            return jsonify({"error": "Failed to fetch playlists from Spotify"}), 502

        # Return only essential info for the full list
        # No need for pagination info in the response itself now
        playlist_data = [{"uri": p["uri"], "name": p["name"], "id": p["id"]} for p in playlists]
        return jsonify(playlist_data), 200 # Return the full array

    except Exception as e:
         current_app.logger.error(f"Error in /api/playlists endpoint: {e}", exc_info=True)
         return jsonify({"error": "An internal error occurred"}), 500

@app.route('/api/devices', methods=['GET'])
def api_get_devices():
    sp = spotify_client.get_spotify_client()
    if not sp: return jsonify({"error": "Authentication required or failed"}), 401
    devices = spotify_client.get_user_devices(sp)
    if devices is None: return jsonify({"error": "Failed to fetch devices"}), 500
    # Return essential info
    device_data = [{"id": d["id"], "name": d["name"], "type": d["type"], "is_active": d["is_active"]} for d in devices]
    return jsonify(device_data), 200

# --- API Schedule CRUD ---
@app.route('/api/schedules', methods=['GET'])
def api_get_schedules():
    user_id = session.get('spotify_user_id')
    if not user_id: return jsonify({"error": "Not authenticated"}), 401

    schedules = database.get_all_schedules(user_id) # Fetches list of dicts
    now_utc = datetime.now(pytz.utc) # Get current time once

    # Calculate next play time for each schedule and add ISO string
    processed_schedules = []
    for schedule in schedules:
        # Calculate the datetime object
        next_time_obj = calculate_next_play_time_utc(schedule, now_utc)
        # Create a copy or new dict to avoid modifying original if needed elsewhere
        # Add the ISO formatted string to the dictionary being sent
        schedule['_next_play_time_utc_iso'] = next_time_obj.isoformat() if next_time_obj else None
        # Keep the object separate for sorting if preferred, or sort based on string
        schedule['_sort_obj'] = next_time_obj # Keep object for sorting
        processed_schedules.append(schedule)


    # Define a sort key function using the datetime object
    def sort_key(schedule):
        next_time = schedule.get('_sort_obj')
        # Assign a very large datetime for None so they sort last
        return next_time if next_time else datetime.max.replace(tzinfo=pytz.utc)

    # Sort the schedules list
    try:
        processed_schedules.sort(key=sort_key)
    except Exception as sort_e:
         msg = f"Error sorting schedules for user {user_id}: {sort_e}"
         if current_app: current_app.logger.error(msg, exc_info=True)
         else: logging.error(msg, exc_info=True)
         # Decide how to handle sort errors, maybe return unsorted
         pass

    # Remove the temporary sort object before returning JSON
    for schedule in processed_schedules:
       schedule.pop('_sort_obj', None)

    # Return the sorted list with the ISO string included
    return jsonify(processed_schedules), 200

@app.route('/api/schedules', methods=['POST'])
def api_add_schedule():
    user_id = session.get('spotify_user_id')
    if not user_id: return jsonify({"error": "Not authenticated"}), 401
    data = request.json
    if not data: return jsonify({"error": "Invalid request data"}), 400

    # ** Basic Validation (Add more robust validation) **
    required_fields = ['playlist_uri', 'target_device_id', 'days_of_week', 'start_time_local', 'timezone']
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Missing required fields"}), 400

    data['user_spotify_id'] = user_id
    data['shuffle_state'] = data.get('shuffle_state', False)
    schedule_id = database.add_schedule(data)

    if schedule_id:
        new_schedule = database.get_schedule_by_id(schedule_id, user_id) # Fetch to return
        return jsonify(new_schedule), 201 # 201 Created
    else:
        return jsonify({"error": "Failed to create schedule in database"}), 500

@app.route('/api/schedules/<int:schedule_id>', methods=['PUT'])
def api_update_schedule(schedule_id):
    user_id = session.get('spotify_user_id')
    if not user_id: return jsonify({"error": "Not authenticated"}), 401
    data = request.json
    if not data: return jsonify({"error": "Invalid request data"}), 400

    if 'shuffle_state' in data:
         data['shuffle_state'] = bool(data['shuffle_state'])

    success = database.update_schedule(schedule_id, user_id, data)
    if success:
         updated_schedule = database.get_schedule_by_id(schedule_id, user_id)
         return jsonify(updated_schedule), 200
    else:
         # Could be not found (404) or DB error (500) - need more specific checks in DB layer
         existing = database.get_schedule_by_id(schedule_id, user_id)
         if not existing:
             return jsonify({"error": "Schedule not found"}), 404
         else:
            return jsonify({"error": "Failed to update schedule"}), 500


@app.route('/api/schedules/<int:schedule_id>', methods=['DELETE'])
def api_delete_schedule(schedule_id):
    user_id = session.get('spotify_user_id')
    if not user_id: return jsonify({"error": "Not authenticated"}), 401

    success = database.delete_schedule(schedule_id, user_id)
    if success:
        return jsonify({"message": "Schedule deleted successfully"}), 200
    else:
        # Could be not found (404) or DB error (500)
        existing = database.get_schedule_by_id(schedule_id, user_id)
        if not existing:
             return jsonify({"error": "Schedule not found"}), 404
        else:
             return jsonify({"error": "Failed to delete schedule"}), 500

@app.route('/api/schedules/<int:schedule_id>/toggle', methods=['PUT']) # Use PUT for state change
def api_toggle_schedule(schedule_id):
    user_id = session.get('spotify_user_id')
    if not user_id: return jsonify({"error": "Not authenticated"}), 401

    success = database.toggle_schedule_active(schedule_id, user_id)
    if success:
         updated_schedule = database.get_schedule_by_id(schedule_id, user_id)
         return jsonify(updated_schedule), 200
    else:
        existing = database.get_schedule_by_id(schedule_id, user_id)
        if not existing:
             return jsonify({"error": "Schedule not found"}), 404
        else:
             return jsonify({"error": "Failed to toggle schedule status"}), 500


# --- API Playback Actions ---
@app.route('/api/schedules/<int:schedule_id>/play_now', methods=['POST'])
def api_play_schedule_now(schedule_id):
    user_id = session.get('spotify_user_id')
    if not user_id: return jsonify({"error": "Not authenticated"}), 401

    schedule_info = database.get_schedule_by_id(schedule_id, user_id)
    if not schedule_info:
        return jsonify({"error": "Schedule not found"}), 404

    sp = spotify_client.get_spotify_client()
    if not sp: return jsonify({"error": "Spotify client unavailable"}), 503

    # Extract necessary info
    device_id = schedule_info['target_device_id']
    playlist_uri = schedule_info['playlist_uri']
    volume = schedule_info.get('volume')
    shuffle_enabled = bool(schedule_info.get('shuffle_state', False)) # Get shuffle state

    app.logger.info(f"Manual Play Now for Schedule {schedule_id}: URI={playlist_uri}, Device={device_id}, Shuffle={shuffle_enabled}")

    # --- Prepare Playback Parameters ---
    playback_params = {
        'device_id': device_id,
        'context_uri': playlist_uri
        # Note: spotify_client.start_playback helper might need adjustment
        # If that helper doesn't accept arbitrary kwargs, you might need to call sp.start_playback directly here instead.
        # Assuming for now we modify start_playback or call sp directly:
    }
    # *** ADD OFFSET if shuffle is OFF ***
    if not shuffle_enabled:
        playback_params['offset'] = {'position': 0} # Start at the first track (index 0)
        app.logger.info(f"Setting playback offset to track 0 for manual play (Shuffle is OFF).")

    # --- Call playback ---
    # OPTION A: If spotify_client.start_playback can handle offset:
    # success = spotify_client.start_playback(
    #     sp,
    #     volume=volume,
    #     **playback_params # Pass device_id, context_uri, and potentially offset
    # )

    # OPTION B: Call sp.start_playback directly here (More likely needed)
    success = False
    try:
        # Set volume first if specified (using sp directly)
        if volume is not None:
             app.logger.info(f"Setting volume to {volume}% for device {device_id}")
             sp.volume(volume_percent=volume, device_id=device_id)
             _time.sleep(0.5) # Small delay

        # Start playback using the prepared parameters
        app.logger.debug(f"Attempting sp.start_playback for manual play with params: {playback_params}")
        sp.start_playback(**playback_params)
        app.logger.info(f"Playback command sent for manual play (Schedule {schedule_id}).")
        success = True
    except SpotifyException as e:
         app.logger.error(f"Spotify API error during manual playback start for schedule {schedule_id}: {e}")
         success = False
    except Exception as e:
         app.logger.error(f"Unexpected error during manual playback start for schedule {schedule_id}: {e}", exc_info=True)
         success = False

    if success:
        playback_command_sent_time = _time.time()
        # --- Set Shuffle State Based on Schedule ---
        app.logger.info(f"Attempting to set shuffle state to {shuffle_enabled} for manual play (Schedule {schedule_id})...")
        try:
            sleep_duration = 1.5 # Consistent delay
            _time.sleep(sleep_duration)
            # Explicitly set shuffle state based on the boolean variable
            sp.shuffle(state=shuffle_enabled, device_id=device_id)
            shuffle_command_sent_time = _time.time()
            app.logger.info(f"Shuffle state set to {shuffle_enabled} successfully for manual play (Schedule {schedule_id}) after {sleep_duration}s delay.")

            # Keep the state check for debugging/confirmation (optional but recommended)
            try:
                check_delay = 0.5
                _time.sleep(check_delay)
                current_state = sp.current_playback()
                check_time = _time.time()
                if current_state and current_state.get('device') and current_state.get('device').get('id') == device_id:
                    api_shuffle_state = current_state.get('shuffle_state', 'N/A')
                    app.logger.info(f"Checked state {check_delay:.1f}s after shuffle command:")
                    app.logger.info(f"  API shuffle_state reported: {api_shuffle_state} (Expected: {shuffle_enabled})")
                    if api_shuffle_state != shuffle_enabled:
                         app.logger.warning(f"  --> Shuffle state mismatch: Command sent for {shuffle_enabled}, but API reports {api_shuffle_state}.")
                # ... (rest of check logging) ...
            except Exception as check_e:
                 app.logger.warning(f"  Could not verify shuffle state after setting: {check_e}")

        except SpotifyException as shuffle_e:
            app.logger.warning(f"Could not set shuffle state to {shuffle_enabled} for manual play (Schedule {schedule_id}): {shuffle_e}")
        except Exception as general_shuffle_e:
             app.logger.error(f"Unexpected error setting shuffle state for manual play (Schedule {schedule_id}): {general_shuffle_e}", exc_info=True)
        # --- End Set Shuffle State ---

        return jsonify({"message": "Playback initiated"}), 200
    else:
        return jsonify({"error": "Failed to initiate playback via Spotify API"}), 502


@app.route('/api/play_now', methods=['POST'])
def api_play_arbitrary_now():
    user_id = session.get('spotify_user_id')
    if not user_id: return jsonify({"error": "Not authenticated"}), 401
    data = request.json
    if not data or 'playlist_uri' not in data or 'device_id' not in data:
        return jsonify({"error": "Missing playlist_uri or device_id"}), 400

    sp = spotify_client.get_spotify_client()
    if not sp: return jsonify({"error": "Spotify client unavailable"}), 503

    success = spotify_client.start_playback(
        sp,
        device_id=data['device_id'],
        playlist_uri=data['playlist_uri'],
        volume=data.get('volume') # Optional volume
    )

    if success:
        return jsonify({"message": "Playback initiated"}), 200
    else:
        return jsonify({"error": "Failed to initiate playback via Spotify API"}), 502

if __name__ == '__main__':
    host = os.getenv('FLASK_RUN_HOST', '0.0.0.0')
    # Using port 9093 as used previously in examples
    port = int(os.getenv('FLASK_RUN_PORT', 9093))
    debug_mode = (os.getenv('FLASK_DEBUG') == '1')

    # --- Determine SSL Context ---
    ssl_context_mode = None # Will be tuple (cert, key) or 'adhoc'
    cert_file_path = os.getenv('FLASK_CERT_FILE') # e.g., 'localhost.crt'
    key_file_path = os.getenv('FLASK_KEY_FILE')   # e.g., 'localhost.key'

    # Check if BOTH paths are provided via environment variables AND the files exist
    if cert_file_path and key_file_path and os.path.exists(cert_file_path) and os.path.exists(key_file_path):
        ssl_context_mode = (cert_file_path, key_file_path)
        print(f"--- Using Custom SSL Certificate ---")
        print(f"  Cert File: {cert_file_path}")
        print(f"  Key File:  {key_file_path}")
        print(f"  Access via: https://localhost:{port} or https://127.0.0.1:{port}")
        print(f"  Ensure browser/OS trusts the CA that signed this cert (e.g., myCA.pem).")
    else:
        # Fallback to adhoc if custom files are not specified or not found
        if cert_file_path or key_file_path:
             # Log a warning if paths were given but files not found/used
             print(f"--- WARNING: Custom SSL cert/key specified but not found/valid ---")
             print(f"  Specified Cert: {cert_file_path or 'Not Set'}")
             print(f"  Specified Key:  {key_file_path or 'Not Set'}")
             print(f"  Falling back to 'adhoc' SSL context.")
        else:
             print("--- Custom SSL cert/key not specified (FLASK_CERT_FILE, FLASK_KEY_FILE) ---")
             print("--- Using 'adhoc' SSL context ---")

        ssl_context_mode = 'adhoc'
        print(f"  Requires pyOpenSSL (pip install pyOpenSSL).")
        print(f"  Access via: https://localhost:{port} or https://127.0.0.1:{port}")
        print(f"  NOTE: Your browser WILL show a security warning (self-signed cert). You must accept/bypass it.")

    # --- End Determine SSL Context ---

    print(f" * Starting Spotify  Flask app with HTTPS...")
    if debug_mode:
        print(" * Debug mode is ON")

    try:
        app.run(
            host=host,
            port=port,
            debug=debug_mode,
            ssl_context=ssl_context_mode # Use the determined context
        )
    except ImportError:
         # This error specifically happens if 'adhoc' is attempted without pyOpenSSL
         print("\nERROR: pyOpenSSL not found, required for 'adhoc' SSL.")
         print("       Please install it: pip install pyOpenSSL")
         if ssl_context_mode != 'adhoc': # Check if we intended to use files
              print(f"       Attempted to use cert={cert_file_path}, key={key_file_path}. Verify paths/existence.")
         print("")
    except FileNotFoundError as e:
         # This might happen if paths were provided to ssl_context tuple but files invalid
         print(f"\nERROR: Could not find certificate or key file specified for ssl_context: {e}\n")
    except OSError as e:
         # Handle other errors like port already in use
         print(f"\nERROR starting Flask server: {e}\n")