import sqlite3
import os
from dotenv import load_dotenv

load_dotenv()
SCHEDULE_DB_FILE = os.getenv('SCHEDULE_DB_FILE', 'playsched.db')

def get_db_connection():
    """Establishes and returns a database connection."""
    conn = sqlite3.connect(SCHEDULE_DB_FILE)
    conn.row_factory = sqlite3.Row # Return rows as dictionary-like objects
    return conn

def create_tables():
    """Creates the schedules table if it doesn't exist (including shuffle_state)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # shuffle_state column included in the initial table definition
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_spotify_id TEXT NOT NULL,
                playlist_uri TEXT NOT NULL,
                playlist_name TEXT,
                target_device_id TEXT NOT NULL,
                target_device_name TEXT,
                days_of_week TEXT NOT NULL,
                start_time_local TEXT NOT NULL,
                stop_time_local TEXT,
                volume INTEGER,
                is_active BOOLEAN DEFAULT 1,
                timezone TEXT NOT NULL,
                play_once_triggered BOOLEAN DEFAULT 0,
                last_triggered_utc TEXT,
                shuffle_state BOOLEAN DEFAULT 0 -- Added shuffle state (0=false, 1=true)
            )
        ''')
        # Removed the ALTER TABLE block
        conn.commit()
        print("Database tables checked/created.")
    except sqlite3.Error as e:
        print(f"Database error during table creation: {e}")
        # raise # Decide if you want to stop the app
    finally:
        conn.close()

# --- CRUD Functions for Schedules ---

def add_schedule(data):
    # Add shuffle_state to INSERT
    sql = '''INSERT INTO schedules(user_spotify_id, playlist_uri, playlist_name, target_device_id, target_device_name, days_of_week, start_time_local, stop_time_local, volume, is_active, timezone, play_once_triggered, last_triggered_utc, shuffle_state)
             VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''' # Added one placeholder
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(sql, (
            data['user_spotify_id'], data['playlist_uri'], data['playlist_name'],
            data['target_device_id'], data['target_device_name'], data['days_of_week'],
            data['start_time_local'], data.get('stop_time_local'), data.get('volume'),
            data.get('is_active', 1), data['timezone'],
            data.get('play_once_triggered', 0), None,
            data.get('shuffle_state', 0) # Get shuffle state, default 0
        ))
        conn.commit()
        return cursor.lastrowid
    except sqlite3.Error as e:
        print(f"Database error adding schedule: {e}")
        return None
    finally:
        conn.close()

def get_all_schedules(user_spotify_id):
    """Retrieves all schedules for a given user."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM schedules WHERE user_spotify_id = ?", (user_spotify_id,))
        schedules = [dict(row) for row in cursor.fetchall()]
        return schedules
    except sqlite3.Error as e:
        print(f"Database error getting all schedules: {e}")
        return []
    finally:
        conn.close()

def get_schedule_by_id(schedule_id, user_spotify_id):
    """Retrieves a specific schedule by ID for a user."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM schedules WHERE id = ? AND user_spotify_id = ?", (schedule_id, user_spotify_id))
        schedule = cursor.fetchone()
        return dict(schedule) if schedule else None
    except sqlite3.Error as e:
        print(f"Database error getting schedule by ID: {e}")
        return None
    finally:
        conn.close()

def update_schedule(schedule_id, user_spotify_id, data):
    fields = []
    values = []
    # Add shuffle_state to allowed fields
    allowed_fields = ['playlist_uri', 'playlist_name', 'target_device_id', 'target_device_name', 'days_of_week', 'start_time_local', 'stop_time_local', 'volume', 'is_active', 'timezone', 'shuffle_state']
    for field in allowed_fields:
        if field in data:
            fields.append(f"{field} = ?")
            # Convert boolean for shuffle_state if necessary
            value = data[field]
            if field == 'shuffle_state':
                 value = 1 if value else 0 # Ensure it's stored as 0 or 1
            values.append(value)

    if not fields:
        return False # Nothing to update

    sql = f"UPDATE schedules SET {', '.join(fields)} WHERE id = ? AND user_spotify_id = ?"
    values.extend([schedule_id, user_spotify_id])

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(sql, tuple(values))
        conn.commit()
        return cursor.rowcount > 0 # Return True if update happened
    except sqlite3.Error as e:
        print(f"Database error updating schedule {schedule_id}: {e}")
        return False
    finally:
        conn.close()


def delete_schedule(schedule_id, user_spotify_id):
    """Deletes a schedule."""
    sql = "DELETE FROM schedules WHERE id = ? AND user_spotify_id = ?"
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(sql, (schedule_id, user_spotify_id))
        conn.commit()
        return cursor.rowcount > 0 # Return True if deletion happened
    except sqlite3.Error as e:
        print(f"Database error deleting schedule {schedule_id}: {e}")
        return False
    finally:
        conn.close()

def toggle_schedule_active(schedule_id, user_spotify_id):
    """Toggles the is_active status of a schedule."""
    # First get current status
    current_schedule = get_schedule_by_id(schedule_id, user_spotify_id)
    if not current_schedule:
        return False

    new_status = 1 - current_schedule['is_active'] # Toggle 0 to 1 or 1 to 0
    sql = "UPDATE schedules SET is_active = ? WHERE id = ? AND user_spotify_id = ?"
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(sql, (new_status, schedule_id, user_spotify_id))
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        print(f"Database error toggling schedule {schedule_id}: {e}")
        return False
    finally:
        conn.close()

def get_active_schedules_for_scheduler():
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # Add shuffle_state to SELECT list
        cursor.execute("SELECT id, user_spotify_id, playlist_uri, target_device_id, days_of_week, start_time_local, stop_time_local, volume, timezone, play_once_triggered, last_triggered_utc, shuffle_state FROM schedules WHERE is_active = 1")
        schedules = [dict(row) for row in cursor.fetchall()]
        return schedules
    except sqlite3.Error as e:
        print(f"Database error getting active schedules for scheduler: {e}")
        return []
    finally:
        conn.close()

def update_schedule_trigger_info(schedule_id, trigger_time_utc_iso, played_once=False):
    """Updates trigger info after a schedule runs."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        if played_once:
            cursor.execute("UPDATE schedules SET last_triggered_utc = ?, play_once_triggered = 1 WHERE id = ?", (trigger_time_utc_iso, schedule_id))
        else:
            cursor.execute("UPDATE schedules SET last_triggered_utc = ? WHERE id = ?", (trigger_time_utc_iso, schedule_id))
        conn.commit()
    except sqlite3.Error as e:
        print(f"Database error updating trigger info for schedule {schedule_id}: {e}")
    finally:
        conn.close()

# Ensure tables exist when module is loaded
create_tables()