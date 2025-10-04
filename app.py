from flask import Flask, request, redirect, url_for, render_template, session, flash, g
import uuid
import sqlite3
import datetime
import yaml
from dateutil import parser # Used to parse timestamps from SQLite
from better_profanity import profanity
from profanity_wordlists import DUTCH_PROFANITY_LIST # Import our custom Dutch list
from reset_db import reset_database # Import the reset function
# --- Flask Configuration ---
app = Flask(__name__)

import os
# --- Security Best Practice: Load Secret Key from Environment Variable ---
# In your terminal, run: export FLASK_SECRET_KEY='a_very_strong_and_random_secret'
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'default_dev_key_is_not_secure')

# --- Database Configuration ---
# Get the absolute path to the directory where this script is located
basedir = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.path.join(basedir, 'treasure_hunt.db')

def get_db():
    """Connects to the database, creating one connection per request."""
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    """Closes the database connection at the end of the request."""
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    """Initializes the database schema and performs simple migrations."""
    with app.app_context():
        db = get_db()
        # 1. Create the table with the latest schema if it doesn't exist
        db.execute('''
            CREATE TABLE IF NOT EXISTS players (
                player_id TEXT PRIMARY KEY,
                player_name TEXT NOT NULL,
                current_clue_tag TEXT,
                last_scan_time DATETIME,
                start_time DATETIME,
                end_time DATETIME
            )
        ''')

        # 2. Simple migration: Add player_name column if it's missing from an old DB
        cursor = db.execute("PRAGMA table_info(players)")
        columns = [row['name'] for row in cursor.fetchall()]
        if 'player_name' not in columns:
            # Add the column. The NOT NULL constraint requires a default value for existing rows.
            db.execute('ALTER TABLE players ADD COLUMN player_name TEXT NOT NULL DEFAULT "Old Player"')

        db.commit()
# Initialize DB once before the app runs
init_db()

# --- Game Clues and Logic ---
def load_clues():
    """Loads clues from the clues.yaml file."""
    try:
        with open('clues.yaml', 'r') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        raise RuntimeError("FATAL: clues.yaml not found. The game cannot start.")
    except yaml.YAMLError as e:
        raise RuntimeError(f"FATAL: Error parsing clues.yaml: {e}")

CLUES = load_clues()

# --- Profanity Filter Configuration ---
# Replace the default English list with our custom Dutch wordlist.
profanity.load_censor_words(DUTCH_PROFANITY_LIST)

# --- Helper Functions & Dynamic Configuration ---
INITIAL_TAG = next(iter(CLUES)) # Dynamically get the first tag from the clues file

def _format_duration(total_seconds):
    """Helper function to format seconds into a 'minutes and seconds' string."""
    minutes, seconds = divmod(int(total_seconds), 60)
    return f"{minutes} minutes and {seconds} seconds"

@app.route('/', methods=['GET', 'POST'])
def index():
    """Landing page for player registration."""
    # Check if a returning player has already finished the game.
    player_id = session.get('player_id')
    if player_id:
        db = get_db()
        player = db.execute("SELECT end_time FROM players WHERE player_id = ?", (player_id,)).fetchone()
        if player:
            # If the player exists in the DB and has an end_time, they've finished.
            if player['end_time']:
                flash("Welcome back, Master Explorer! You have already completed the hunt. Here are the results.", "info")
                return redirect(url_for('leaderboard'))
            else:
                # Player is active but not finished. Restore their session.
                return redirect(url_for('resume_game'))
        else:
            # The player_id in the cookie is invalid (not in DB). Clear the stale session.
            session.clear()

    if request.method == 'POST':
        player_name = request.form.get('player_name')
        if not player_name or not player_name.strip():
            flash("Player name cannot be empty!")
            return redirect(url_for('index'))
        
        clean_player_name = player_name.strip()

        # --- Sanity Checks for Player Name ---
        # 1. Check for inappropriate words using the better-profanity library
        if profanity.contains_profanity(clean_player_name):
            flash("That name contains inappropriate language. Please choose a different name.", "error")
            return redirect(url_for('index'))

        db = get_db()
        # 2. Check if a player with this name already exists (active or finished)
        existing_player = db.execute(
            "SELECT player_id FROM players WHERE player_name = ?",
            (clean_player_name,)
        ).fetchone()

        if existing_player:
            flash(f"A player named '{clean_player_name}' is already on a voyage! Please choose a different name.", "error")
            return redirect(url_for('index'))
        
        # --- End Sanity Checks ---

        player_id = str(uuid.uuid4())
        session['player_id'] = player_id
        session['player_name'] = clean_player_name
        session.permanent = True  # Make the session cookie more durable
        db.execute("INSERT INTO players (player_id, player_name) VALUES (?, ?)", (player_id, clean_player_name))
        db.commit()

        # Redirect to the new start page instead of directly to the clue check
        return redirect(url_for('start_game'))

    return render_template('index.html')

@app.route('/start')
def start_game():
    """Displays the very first clue to the player and starts the timer."""
    player_id = session.get('player_id')
    player_name = session.get('player_name')
    if not player_id or not player_name:
        flash("Please register to start the hunt.", "error")
        return redirect(url_for('index'))
    
    db = get_db()
    player = db.execute("SELECT start_time FROM players WHERE player_id = ?", (player_id,)).fetchone()

    # If the player exists and their timer hasn't started yet, start it now.
    # This is idempotent, so reloading the page won't reset the timer.
    if player and player['start_time'] is None:
        db.execute(
            "UPDATE players SET start_time = CURRENT_TIMESTAMP, current_clue_tag = ? WHERE player_id = ?",
            (INITIAL_TAG, player_id)
        )
        db.commit()
        flash("Your timer has started! Good luck!", "info")

    return render_template('start_game.html', player_name=player_name, first_clue=CLUES[INITIAL_TAG]['clue'])

@app.route('/resume')
def resume_game():
    """Shows a returning player their current clue."""
    player_id = session.get('player_id')
    if not player_id:
        # No session, send them to the start
        return redirect(url_for('index'))

    db = get_db()
    player = db.execute("SELECT player_name, current_clue_tag FROM players WHERE player_id = ?", (player_id,)).fetchone()

    if not player:
        session.clear()
        return redirect(url_for('index'))

    # The player's current clue is the one for the tag they are looking for.
    current_clue_tag = player['current_clue_tag'] or INITIAL_TAG
    current_clue_text = CLUES[current_clue_tag]['clue']
    return render_template('resume_game.html', player_name=player['player_name'], current_clue=current_clue_text)

def _get_player_from_session(db):
    """Authenticates a player from the session and fetches their DB record."""
    player_id = session.get('player_id')
    if not player_id:
        return None, None
    player_row = db.execute("SELECT player_name, current_clue_tag, start_time, end_time FROM players WHERE player_id = ?", (player_id,)).fetchone()
    if not player_row:
        session.clear()
        return None, None
    return player_id, player_row

def _handle_incorrect_scan(player_name, current_expected_tag):
    """Generates the response for scanning the wrong tag."""
    current_clue_info = CLUES.get(current_expected_tag)
    if current_clue_info:
        error_message = f"Incorrect tag scanned. You are currently looking for the tag associated with the clue: \n\n\"{current_clue_info['clue']}\""
    else:
        error_message = "Incorrect tag scanned. Please check your current clue."
    return render_template('error.html', message=error_message, player_name=player_name)

def _handle_final_scan(db, player_id):
    """Handles the logic for the final, game-winning scan."""
    db.execute("UPDATE players SET current_clue_tag = 'FINISHED', end_time = CURRENT_TIMESTAMP, last_scan_time = CURRENT_TIMESTAMP WHERE player_id = ?", (player_id,))
    db.commit()

    final_times = db.execute("SELECT start_time, end_time FROM players WHERE player_id = ?", (player_id,)).fetchone()
    start_dt = parser.parse(final_times['start_time'])
    end_dt = parser.parse(final_times['end_time'])
    duration = end_dt - start_dt
    
    rank_row = db.execute(
        '''
        SELECT COUNT(player_id) FROM players
        WHERE end_time IS NOT NULL AND (JULIANDAY(end_time) - JULIANDAY(start_time)) < ?
        ''',
        (duration.total_seconds() / 86400.0,)
    ).fetchone()
    
    return _format_duration(duration.total_seconds()), rank_row[0] + 1

@app.route('/hunt/clue/<tag_id>')
def check_clue(tag_id):
    db = get_db()
    player_id, player_row = _get_player_from_session(db)

    if not player_id:
        flash("Please register with a player name to start the hunt!", "error")
        return redirect(url_for('index'))

    player_name = player_row['player_name']

    # Handle players who have already finished
    if player_row['end_time']:
        flash("You have already completed the hunt! Here are the results.", "info")
        return redirect(url_for('leaderboard'))

    # Re-fetch player data to get the current expected tag
    player_row = db.execute("SELECT current_clue_tag FROM players WHERE player_id = ?", (player_id,)).fetchone()
    current_expected_tag = player_row['current_clue_tag']

    # Validate the scanned tag
    if tag_id != current_expected_tag:
        return _handle_incorrect_scan(player_name, current_expected_tag)

    # --- SUCCESS: Correct tag was scanned ---
    clue_data = CLUES.get(tag_id)
    if not clue_data:
        return render_template('error.html', message="This tag is not active in the current hunt.", player_name=player_name)

    next_tag_id = clue_data['next_tag']
    completion_time, player_rank = None, None

    if next_tag_id:
        # Update progress to the next tag
        db.execute("UPDATE players SET current_clue_tag = ?, last_scan_time = CURRENT_TIMESTAMP WHERE player_id = ?", (next_tag_id, player_id))
    else:
        # This is the final tag, end the game
        completion_time, player_rank = _handle_final_scan(db, player_id)

    db.commit()

    return render_template('clue_display.html',
                           clue=clue_data['clue'],
                           final=clue_data['final'],
                           player_name=player_name,
                           completion_time=completion_time,
                           player_rank=player_rank)

@app.route('/leaderboard')
def leaderboard():
    """Displays the top 10 players by completion time."""
    db = get_db()
    # Query for players who have finished, calculate duration, and order by it.
    # The JULIANDAY function allows for easy subtraction of datetime values.
    rows = db.execute('''
        SELECT player_name, (JULIANDAY(end_time) - JULIANDAY(start_time)) * 86400.0 AS duration
        FROM players
        WHERE end_time IS NOT NULL
        ORDER BY duration ASC
        LIMIT 10
    ''').fetchall()

    leaderboard_data = []
    for row in rows:
        minutes, seconds = divmod(int(row['duration']), 60)
        leaderboard_data.append({'name': row['player_name'], 'time': f"{minutes}m {seconds}s"})
    return render_template('leaderboard.html', leaderboard=leaderboard_data)

@app.route('/admin/dashboard', methods=['GET', 'POST'])
def admin_dashboard():
    """A password-protected dashboard to view all player data."""
    ADMIN_PASSWORD = "bruinvis"

    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            flash("Login successful!", "info")
            return redirect(url_for('admin_dashboard'))
        else:
            flash("Incorrect password.", "error")

    if not session.get('admin_logged_in'):
        return render_template('admin_dashboard.html', admin_logged_in=False)

    # If logged in, show the dashboard
    db = get_db()
    all_players = db.execute('''
        SELECT 
            player_name, 
            current_clue_tag, 
            start_time, 
            end_time, 
            (JULIANDAY(end_time) - JULIANDAY(start_time)) * 86400.0 AS duration
        FROM players 
        ORDER BY start_time DESC
    ''').fetchall()

    return render_template('admin_dashboard.html', players=all_players, format_duration=_format_duration, admin_logged_in=True)

@app.route('/admin/reset', methods=['POST'])
def admin_reset():
    """Handles the database reset action from the admin dashboard."""
    if not session.get('admin_logged_in'):
        return "Unauthorized", 403
    
    reset_database()
    # Clear all user sessions to prevent "ghost session" issues after a reset
    session.clear()
    session['admin_logged_in'] = True # Keep the admin logged in
    flash("Database has been successfully reset. All player data is gone.", "info")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/remove_player/<player_id>', methods=['POST'])
def admin_remove_player(player_id):
    """Removes a player from the database."""
    if not session.get('admin_logged_in'):
        return "Unauthorized", 403
    
    db = get_db()
    db.execute("DELETE FROM players WHERE player_id = ?", (player_id,))
    db.commit()
    
    flash(f"Player has been successfully removed.", "info")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/change_name/<player_id>', methods=['POST'])
def admin_change_name(player_id):
    """Changes a player's name."""
    if not session.get('admin_logged_in'):
        return "Unauthorized", 403

    new_name = request.form.get('new_name', '').strip()

    if not new_name:
        flash("Player name cannot be empty.", "error")
        return redirect(url_for('admin_dashboard'))

    if profanity.contains_profanity(new_name):
        flash("The new name contains inappropriate language.", "error")
        return redirect(url_for('admin_dashboard'))

    db = get_db()
    # Optional: Check if the new name is already taken by another player
    existing = db.execute("SELECT player_id FROM players WHERE player_name = ? AND player_id != ?", (new_name, player_id)).fetchone()
    if existing:
        flash(f"The name '{new_name}' is already in use by another player.", "error")
        return redirect(url_for('admin_dashboard'))

    db.execute("UPDATE players SET player_name = ? WHERE player_id = ?", (new_name, player_id))
    db.commit()
    flash("Player name has been updated successfully.", "info")
    return redirect(url_for('admin_dashboard'))

@app.errorhandler(404)
def page_not_found(e):
    """Custom 404 handler to redirect to the index page."""
    flash("The page you were looking for could not be found. Let's start over!", "error")
    return redirect(url_for('index'))

if __name__ == '__main__':
    # For testing, run with: python3 app.py
    # For production, use Gunicorn/Nginx as described previously
    app.run(host='0.0.0.0', port=5000, debug=True)
