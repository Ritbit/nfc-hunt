from flask import Flask, request, redirect, url_for, render_template, session, flash, g
import uuid
import sqlite3
import datetime
import yaml
from dateutil import parser # Used to parse timestamps from SQLite
from better_profanity import profanity
from profanity_wordlists import DUTCH_PROFANITY_LIST # Import our custom Dutch list
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
        # If the player exists and has an end_time, they've finished.
        if player and player['end_time']:
            flash("Welcome back, Master Explorer! You have already completed the hunt. Here are the results.", "info")
            return redirect(url_for('leaderboard'))

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
    """Displays the very first clue to the player before the timer starts."""
    player_name = session.get('player_name')
    if not player_name:
        flash("Please register to start the hunt.", "error")
        return redirect(url_for('index'))
    
    return render_template('start_game.html', player_name=player_name, first_clue=CLUES[INITIAL_TAG]['clue'])

@app.route('/hunt/clue/<tag_id>')
def check_clue(tag_id):
    # 1. Identify Player
    player_id = session.get('player_id')
    player_name = session.get('player_name')
    
    if not player_id:
        # If a player tries to scan a tag without registering first
        flash("Please register with a player name to start the hunt!")
        return redirect(url_for('index'))

    db = get_db()
    player_row = db.execute("SELECT player_name, current_clue_tag, start_time, end_time FROM players WHERE player_id = ?", (player_id,)).fetchone()
    
    if not player_row:
        # Fallback for corrupted session/DB state
        session.clear()
        flash("Player session error. Please register again.")
        return redirect(url_for('index'))

    # 2. Game Start Logic
    # If start_time is NULL, this is the first scan that starts the game.
    if player_row['start_time'] is None:
        if tag_id != INITIAL_TAG:
            return render_template('error.html', message=f"To start the game, you must scan the first tag ({INITIAL_TAG}).", player_name=player_name)
        # START GAME: Record start_time and set current_clue_tag
        db.execute("UPDATE players SET current_clue_tag = ?, start_time = CURRENT_TIMESTAMP, last_scan_time = CURRENT_TIMESTAMP WHERE player_id = ?", (tag_id, player_id))
        db.commit()
        # Re-fetch player data after update
        player_row = db.execute("SELECT player_name, current_clue_tag, start_time, end_time FROM players WHERE player_id = ?", (player_id,)).fetchone()

    # 3. Process Scan
    current_expected_tag = player_row['current_clue_tag'] or INITIAL_TAG
    clue_data = CLUES.get(tag_id)

    if not clue_data:
        # Scanned an unknown tag
        return render_template('error.html', message="This tag is not active in the current hunt.", player_name=player_name)
    
    # Check if game is already finished
    if player_row['end_time']:
        # A player who has already finished scans a tag again.
        flash("You have already completed the hunt! Here are the results.", "info")
        return redirect(url_for('leaderboard'))


    # 4. Check if Scanned Tag is the Expected Clue
    if tag_id == current_expected_tag:
        # Success! Player found the correct tag in order.
        
        next_tag_id = clue_data['next_tag']
        completion_time = None
        player_rank = None
        
        if next_tag_id:
            # Update progress to the next tag
            db.execute("UPDATE players SET current_clue_tag = ?, last_scan_time = CURRENT_TIMESTAMP WHERE player_id = ?", (next_tag_id, player_id))
            
        else:
            # GAME FINISHED (Final tag)
            db.execute("UPDATE players SET current_clue_tag = 'FINISHED', end_time = CURRENT_TIMESTAMP, last_scan_time = CURRENT_TIMESTAMP WHERE player_id = ?", (player_id,))
            db.commit() # Commit before reading
            
            # Fetch the final times from the DB to ensure consistency
            final_times = db.execute("SELECT start_time, end_time FROM players WHERE player_id = ?", (player_id,)).fetchone()
            start_dt = parser.parse(final_times['start_time'])
            end_dt = parser.parse(final_times['end_time'])
            duration = end_dt - start_dt
            completion_time = _format_duration(duration.total_seconds())

            # Calculate player's rank
            # The rank is 1 + the number of players who finished with a shorter time.
            # We compare the duration in days, which is what JULIANDAY subtraction yields.
            rank_row = db.execute(
                '''
                SELECT COUNT(player_id) FROM players
                WHERE end_time IS NOT NULL AND (JULIANDAY(end_time) - JULIANDAY(start_time)) < ?
                ''',
                (duration.total_seconds() / 86400.0,)
            ).fetchone()
            player_rank = rank_row[0] + 1

        db.commit()
        
        # Display the clue
        return render_template('clue_display.html', 
                               clue=clue_data['clue'], 
                               final=clue_data['final'], 
                               player_name=player_name, 
                               completion_time=completion_time,
                               player_rank=player_rank)
    
    elif tag_id != current_expected_tag:
        # Player scanned an incorrect tag (out of order)
        # Display the clue they are currently looking for to help them get back on track
        current_clue_info = CLUES.get(current_expected_tag)
        if current_clue_info:
            error_message = f"Incorrect tag scanned. You are currently looking for the tag associated with the clue: \n\n\"{current_clue_info['clue']}\""
        else:
            error_message = "Incorrect tag scanned. Please check your current clue."
            
        return render_template('error.html', message=error_message, player_name=player_name)

    return render_template('error.html', message="An unexpected game state occurred.", player_name=player_name)

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

if __name__ == '__main__':
    # For testing, run with: python3 app.py
    # For production, use Gunicorn/Nginx as described previously
    app.run(host='0.0.0.0', port=5000, debug=True)
