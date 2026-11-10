from flask import Flask, request, redirect, url_for, render_template, session, flash, g
import uuid
import sqlite3
import datetime
import yaml
from dateutil import parser # Used to parse timestamps from SQLite
from better_profanity import profanity
from profanity_wordlists import DUTCH_PROFANITY_LIST # Import our custom Dutch list
from reset_db import reset_database # Import the reset function
import math
import io
import secrets
import shutil
import time

import qrcode
import qrcode.image.svg
from collections import defaultdict
# --- Flask Configuration ---
app = Flask(__name__)

import os
# --- Security Best Practice: Load Secret Key from Environment Variable ---
# In your terminal, run: export FLASK_SECRET_KEY='a_very_strong_and_random_secret'
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'default_dev_key_is_not_secure')

# --- Security Best Practice: Load Admin Password from Environment Variable ---
# In your terminal, run: export ADMIN_PASSWORD='your_secure_password'
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD')
if not ADMIN_PASSWORD:
    raise RuntimeError("FATAL: ADMIN_PASSWORD environment variable is not set.")

# --- Database Configuration ---
# Get the absolute path to the directory where this script is located
basedir = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.environ.get('DATABASE', os.path.join(basedir, 'treasure_hunt.db'))
CLUES_FILE = os.path.join(basedir, 'clues.yaml')

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
        if 'wrong_scans' not in columns:
            db.execute('ALTER TABLE players ADD COLUMN wrong_scans INTEGER NOT NULL DEFAULT 0')

        # 3. Enforce case-insensitive uniqueness of player names at the DB level,
        #    so concurrent registrations can't slip past the check-then-insert.
        try:
            db.execute(
                'CREATE UNIQUE INDEX IF NOT EXISTS idx_players_name '
                'ON players(player_name COLLATE NOCASE)'
            )
        except sqlite3.IntegrityError:
            print("WARNING: duplicate player names exist in the database; "
                  "the unique index could not be created. Clean up duplicates "
                  "or reset the database to enforce name uniqueness.")

        db.commit()
# Initialize DB once before the app runs
init_db()

# --- Game Clues and Logic ---
def load_clues():
    """Loads clues from the clues.yaml file."""
    try:
        with open(CLUES_FILE, 'r') as f:
            clues = yaml.safe_load(f)
    except FileNotFoundError:
        raise RuntimeError("FATAL: clues.yaml not found. The game cannot start.")
    except yaml.YAMLError as e:
        raise RuntimeError(f"FATAL: Error parsing clues.yaml: {e}")
    return clues

def validate_clues(clues):
    """Validates the clue chain at startup: every next_tag must resolve,
    exactly one tag must be the entry point, and the chain must be a
    single non-cyclic path covering all tags."""
    if not clues:
        raise RuntimeError("FATAL: clues.yaml is empty. The game cannot start.")
    for tag_id, data in clues.items():
        clue = data.get('clue')
        if not clue:
            raise RuntimeError(f"FATAL: clue '{tag_id}' has no clue text.")
        if isinstance(clue, dict) and not (clue.get('en') or '').strip():
            raise RuntimeError(f"FATAL: clue '{tag_id}' is missing required 'en' clue text.")
        next_tag = data.get('next_tag')
        if next_tag is not None and next_tag not in clues:
            raise RuntimeError(f"FATAL: clue '{tag_id}' points to unknown tag '{next_tag}'.")
    referenced = {c['next_tag'] for c in clues.values() if c.get('next_tag')}
    starts = [t for t in clues if t not in referenced]
    finals = [t for t, c in clues.items() if c.get('next_tag') is None]
    if len(starts) != 1 or len(finals) != 1:
        raise RuntimeError(
            f"FATAL: clue chain must have exactly one start tag and one final tag "
            f"(found starts={starts}, finals={finals}).")
    # Walk the chain from the start tag; it must visit every tag exactly once.
    seen, tag = set(), starts[0]
    while tag is not None:
        if tag in seen:
            raise RuntimeError(f"FATAL: cycle detected in clue chain at '{tag}'.")
        seen.add(tag)
        tag = clues[tag].get('next_tag')
    if seen != set(clues):
        raise RuntimeError(f"FATAL: clue chain does not cover all tags (missing: {set(clues) - seen}).")
    return starts[0]

CLUES = load_clues()
INITIAL_TAG = validate_clues(CLUES) # Returns the chain's entry-point tag
_clues_mtime = os.path.getmtime(CLUES_FILE)

@app.before_request
def _refresh_clues():
    """uWSGI runs several workers; an admin clue edit writes the file but only
    updates the saving worker's memory. Every worker reloads when the mtime
    changes, keeping all workers on the same clue chain."""
    global CLUES, INITIAL_TAG, _clues_mtime
    try:
        mtime = os.path.getmtime(CLUES_FILE)
    except OSError:
        return
    if mtime != _clues_mtime:
        try:
            new_clues = load_clues()
            new_initial = validate_clues(new_clues)
        except RuntimeError:
            return  # keep serving the last valid chain if the file is broken
        CLUES, INITIAL_TAG, _clues_mtime = new_clues, new_initial, mtime

# --- Profanity Filter Configuration ---
# Replace the default English list with our custom Dutch wordlist.
profanity.load_censor_words(DUTCH_PROFANITY_LIST)

# --- Helper Functions & Dynamic Configuration ---
SUPPORTED_LANGUAGES = ('en', 'nl')

def clue_text(tag_id):
    """Returns the clue text for a tag in the player's session language.
    Supports both plain-string clues and localized {en: ..., nl: ...} dicts."""
    clue = CLUES[tag_id].get('clue')
    if isinstance(clue, dict):
        lang = session.get('lang', 'en')
        return clue.get(lang) or clue.get('en') or next(iter(clue.values()))
    return clue

@app.route('/lang/<lang>')
def set_language(lang):
    """Stores the player's language preference and returns to the page they came from."""
    if lang in SUPPORTED_LANGUAGES:
        session['lang'] = lang
    # Never redirect back to a /hunt/clue/ URL — it would rescan the tag
    # (GET mutates progress), producing a bogus "incorrect tag" page.
    ref = request.referrer
    if not ref or '/hunt/clue/' in ref:
        return redirect(url_for('resume_game' if session.get('player_id') else 'index'))
    return redirect(ref)

def _format_duration(total_seconds):
    """Helper function to format seconds into a 'minutes and seconds' string."""
    minutes, seconds = divmod(int(total_seconds), 60)
    return f"{minutes} minutes and {seconds} seconds"

def _elapsed_seconds(start_time_str):
    """Seconds elapsed since a SQLite 'YYYY-MM-DD HH:MM:SS' (UTC) timestamp."""
    if not start_time_str:
        return 0
    start_dt = parser.parse(start_time_str)
    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    return max(0, int((now_utc - start_dt).total_seconds()))

# --- CSRF Protection ---
def get_csrf_token():
    """Returns the session's CSRF token, generating one on first use."""
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(16)
    return session['csrf_token']

app.jinja_env.globals['csrf_token'] = get_csrf_token

def _csrf_valid():
    """Checks that the submitted form carries the session's CSRF token."""
    token = session.get('csrf_token')
    return bool(token) and secrets.compare_digest(token, request.form.get('csrf_token', ''))

# --- Rate Limiting ---
# Simple in-process limiter. Note: uWSGI runs multiple workers, so limits
# are effectively multiplied by the process count — still a useful slowdown.
_attempts = defaultdict(list)

def _rate_limited(key, limit, window_seconds):
    """Returns True if `key` has exceeded `limit` attempts within the window."""
    now = time.time()
    attempts = _attempts[key]
    attempts[:] = [t for t in attempts if now - t < window_seconds]
    if len(attempts) >= limit:
        return True
    attempts.append(now)
    return False

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
        if _rate_limited(f"register:{request.remote_addr}", limit=10, window_seconds=60):
            flash("Too many registration attempts. Please wait a moment and try again.", "error")
            return redirect(url_for('index'))

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
            "SELECT player_id FROM players WHERE player_name = ? COLLATE NOCASE",
            (clean_player_name,)
        ).fetchone()

        if existing_player:
            flash(f"A player named '{clean_player_name}' is already on a voyage! Please choose a different name.", "error")
            return redirect(url_for('index'))
        
        # --- End Sanity Checks ---

        player_id = str(uuid.uuid4())
        try:
            db.execute("INSERT INTO players (player_id, player_name) VALUES (?, ?)", (player_id, clean_player_name))
            db.commit()
        except sqlite3.IntegrityError:
            # Unique index caught a concurrent duplicate registration
            db.rollback()
            flash(f"A player named '{clean_player_name}' is already on a voyage! Please choose a different name.", "error")
            return redirect(url_for('index'))

        session['player_id'] = player_id
        session['player_name'] = clean_player_name
        lang = request.form.get('language')
        if lang in SUPPORTED_LANGUAGES:
            session['lang'] = lang
        session.permanent = True  # Make the session cookie more durable

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

    if not player:
        # Stale session: the player was removed from the DB (e.g. by an admin).
        session.clear()
        flash("Your registration could not be found. Please register again.", "error")
        return redirect(url_for('index'))

    # If the player exists and their timer hasn't started yet, start it now.
    # This is idempotent, so reloading the page won't reset the timer.
    if player and player['start_time'] is None:
        db.execute(
            "UPDATE players SET start_time = DATETIME('now'), current_clue_tag = ? WHERE player_id = ?",
            (INITIAL_TAG, player_id)
        )
        db.commit()
        flash("Your timer has started! Good luck!", "info")

    return render_template('start_game.html',
                           player_name=player_name,
                           first_clue=clue_text(INITIAL_TAG),
                           elapsed_seconds=_elapsed_seconds(player['start_time']))

@app.route('/resume')
def resume_game():
    """Shows a returning player their current clue."""
    player_id = session.get('player_id')
    if not player_id:
        # No session, send them to the start
        return redirect(url_for('index'))

    db = get_db()
    player = db.execute("SELECT player_name, current_clue_tag, start_time, end_time FROM players WHERE player_id = ?", (player_id,)).fetchone()

    if not player:
        session.clear()
        return redirect(url_for('index'))

    if player['end_time']:
        # Finished players have no current clue; 'FINISHED' is not a real tag.
        return redirect(url_for('leaderboard'))

    # The player's current clue is the one for the tag they are looking for.
    current_clue_tag = player['current_clue_tag'] or INITIAL_TAG
    current_clue_text = clue_text(current_clue_tag)
    return render_template('resume_game.html',
                           player_name=player['player_name'],
                           current_clue=current_clue_text,
                           elapsed_seconds=_elapsed_seconds(player['start_time']))

def _get_player_from_session(db):
    """Authenticates a player from the session and fetches their DB record."""
    player_id = session.get('player_id')
    if not player_id:
        return None, None
    player_row = db.execute("SELECT player_name, current_clue_tag, start_time, end_time, wrong_scans FROM players WHERE player_id = ?", (player_id,)).fetchone()
    if not player_row:
        session.clear()
        return None, None
    return player_id, player_row

def _handle_incorrect_scan(db, player_id, player_name, current_expected_tag):
    """Generates the response for scanning the wrong tag."""
    db.execute("UPDATE players SET wrong_scans = wrong_scans + 1 WHERE player_id = ?", (player_id,))
    db.commit()
    current_clue_info = CLUES.get(current_expected_tag)
    if current_clue_info:
        error_message = f"Incorrect tag scanned. You are currently looking for the tag associated with the clue: \n\n\"{clue_text(current_expected_tag)}\""
    else:
        error_message = "Incorrect tag scanned. Please check your current clue."
    return render_template('error.html', message=error_message, player_name=player_name)

def _handle_final_scan(db, player_id):
    """Handles the logic for the final, game-winning scan."""
    db.execute("UPDATE players SET current_clue_tag = 'FINISHED', end_time = DATETIME('now'), last_scan_time = DATETIME('now') WHERE player_id = ?", (player_id,))
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

    current_expected_tag = player_row['current_clue_tag']

    # A player who registered but never visited /start has no current tag.
    # Scanning the first tag doubles as their start: begin the timer and
    # treat the scan as a correct first find.
    if current_expected_tag is None:
        if tag_id != INITIAL_TAG:
            return _handle_incorrect_scan(db, player_id, player_name, INITIAL_TAG)
        db.execute(
            "UPDATE players SET start_time = DATETIME('now'), current_clue_tag = ? WHERE player_id = ?",
            (INITIAL_TAG, player_id)
        )
        db.commit()
        current_expected_tag = INITIAL_TAG

    # Validate the scanned tag
    if tag_id != current_expected_tag:
        return _handle_incorrect_scan(db, player_id, player_name, current_expected_tag)

    # --- SUCCESS: Correct tag was scanned ---
    clue_data = CLUES.get(tag_id)
    if not clue_data:
        return render_template('error.html', message="This tag is not active in the current hunt.", player_name=player_name)

    next_tag_id = clue_data['next_tag']
    completion_time, player_rank = None, None

    # Determine which clue to display on the success page.
    display_clue = ""

    still_hunting = None
    if next_tag_id:
        # Update progress to the next tag
        db.execute("UPDATE players SET current_clue_tag = ?, last_scan_time = DATETIME('now') WHERE player_id = ?", (next_tag_id, player_id))
        # The clue to display is the one for the NEXT tag the player needs to find.
        display_clue = clue_text(next_tag_id)
    else:
        # This is the final tag, end the game
        completion_time, player_rank = _handle_final_scan(db, player_id)
        # On the final screen, we can re-display the final clue text.
        display_clue = clue_text(tag_id)
        # How many explorers are still out there hunting?
        still_hunting = db.execute(
            "SELECT COUNT(*) FROM players WHERE end_time IS NULL AND start_time IS NOT NULL AND player_id != ?",
            (player_id,)
        ).fetchone()[0]

    db.commit()

    return render_template('clue_display.html',
                           clue=display_clue,
                           final=(next_tag_id is None),
                           player_name=player_name,
                           completion_time=completion_time,
                           player_rank=player_rank,
                           wrong_scans=player_row['wrong_scans'],
                           still_hunting=still_hunting,
                           elapsed_seconds=_elapsed_seconds(player_row['start_time']))

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
    if request.method == 'POST':
        if _rate_limited(f"admin-login:{request.remote_addr}", limit=10, window_seconds=300):
            flash("Too many login attempts. Please wait a few minutes and try again.", "error")
            return render_template('admin_dashboard.html', admin_logged_in=False)
        if not _csrf_valid():
            flash("Invalid or expired form token. Please try again.", "error")
            return render_template('admin_dashboard.html', admin_logged_in=False)
        if secrets.compare_digest(request.form.get('password', ''), ADMIN_PASSWORD):
            session['admin_logged_in'] = True
            flash("Login successful!", "info")
            return redirect(url_for('admin_dashboard'))
        else:
            flash("Incorrect password.", "error")

    if not session.get('admin_logged_in'):
        return render_template('admin_dashboard.html', admin_logged_in=False)

    # --- Pagination Logic ---
    PER_PAGE = 15 # Number of players to show per page

    # --- Sorting & Filtering (order clauses come from a fixed whitelist) ---
    SORT_ORDERS = {
        'start': 'start_time DESC',
        'last_scan': 'last_scan_time DESC',
        'name': 'player_name COLLATE NOCASE ASC',
        'duration': 'duration DESC',
    }
    sort = request.args.get('sort', 'start')
    order_by = SORT_ORDERS.get(sort, SORT_ORDERS['start'])

    status = request.args.get('status')
    where_clause = ''
    if status == 'active':
        where_clause = 'WHERE end_time IS NULL'
    elif status == 'finished':
        where_clause = 'WHERE end_time IS NOT NULL'
    else:
        status = 'all'

    db = get_db()

    # Get the total number of players for pagination controls
    total_players_row = db.execute(f'SELECT COUNT(player_id) FROM players {where_clause}').fetchone()
    total_players = total_players_row[0]
    total_pages = math.ceil(total_players / PER_PAGE)

    # Clamp the requested page to the available range
    page = request.args.get('page', 1, type=int)
    page = max(1, min(page, total_pages)) if total_pages else 1
    offset = (page - 1) * PER_PAGE

    # Fetch only the players for the current page
    players_on_page = db.execute(f'''
        SELECT
            player_id,
            player_name,
            current_clue_tag,
            start_time,
            end_time,
            last_scan_time,
            wrong_scans,
            (JULIANDAY(end_time) - JULIANDAY(start_time)) * 86400.0 AS duration
        FROM players
        {where_clause}
        ORDER BY {order_by}
        LIMIT {PER_PAGE} OFFSET {offset}
    ''').fetchall()

    return render_template('admin_dashboard.html',
                           players=players_on_page,
                           format_duration=_format_duration,
                           admin_logged_in=True,
                           current_page=page,
                           total_pages=total_pages,
                           current_sort=sort,
                           current_status=status)

@app.route('/admin/reset', methods=['POST'])
def admin_reset():
    """Handles the database reset action from the admin dashboard."""
    if not session.get('admin_logged_in'):
        return "Unauthorized", 403
    if not _csrf_valid():
        return "Invalid CSRF token", 403
    
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
    if not _csrf_valid():
        return "Invalid CSRF token", 403
    
    db = get_db()
    db.execute("DELETE FROM players WHERE player_id = ?", (player_id,))
    db.commit()
    
    flash(f"Player has been successfully removed.", "info")
    return redirect(url_for('admin_dashboard'))

def _parse_admin_datetime(value):
    """Normalizes a datetime-local form value to SQLite 'YYYY-MM-DD HH:MM:SS'.
    Returns None for empty input; raises ValueError on unparseable input."""
    value = (value or '').strip().replace('T', ' ')
    if not value:
        return None
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            return datetime.datetime.strptime(value, fmt).strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            pass
    raise ValueError(f"Invalid datetime: {value}")

@app.route('/admin/adjust_time/<player_id>', methods=['POST'])
def admin_adjust_time(player_id):
    """Manually corrects a player's start/end time (e.g. accidental starts)."""
    if not session.get('admin_logged_in'):
        return "Unauthorized", 403
    if not _csrf_valid():
        return "Invalid CSRF token", 403

    db = get_db()
    player = db.execute("SELECT player_id, start_time FROM players WHERE player_id = ?", (player_id,)).fetchone()
    if not player:
        flash("Player not found.", "error")
        return redirect(url_for('admin_dashboard'))

    try:
        new_start = _parse_admin_datetime(request.form.get('start_time'))
        new_end = _parse_admin_datetime(request.form.get('end_time'))
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for('admin_dashboard'))

    # An end_time without a start_time makes duration NULL and breaks the leaderboard
    effective_start = new_start if new_start is not None else player['start_time']
    if new_end is not None and effective_start is None:
        flash("Cannot set an end time for a player whose timer has not started.", "error")
        return redirect(url_for('admin_dashboard'))

    updates, params = [], []
    if new_start is not None:
        updates.append("start_time = ?")
        params.append(new_start)
    if request.form.get('clear_end_time'):
        updates.append("end_time = NULL")
        # Reopened players are still 'FINISHED' in current_clue_tag; point them
        # back at the final tag so rescanning it completes the game again.
        final_tag = next(t for t, c in CLUES.items() if c.get('next_tag') is None)
        updates.append("current_clue_tag = ?")
        params.append(final_tag)
    elif new_end is not None:
        updates.append("end_time = ?")
        params.append(new_end)

    if not updates:
        flash("No time changes submitted.", "error")
        return redirect(url_for('admin_dashboard'))

    params.append(player_id)
    db.execute(f"UPDATE players SET {', '.join(updates)} WHERE player_id = ?", params)
    db.commit()
    flash("Player times updated.", "info")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/clues', methods=['GET', 'POST'])
def admin_clues():
    """Lets an admin edit clues.yaml from the dashboard, with validation."""
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_dashboard'))

    global CLUES, INITIAL_TAG, _clues_mtime

    if request.method == 'POST':
        if not _csrf_valid():
            return "Invalid CSRF token", 403

        # Rebuild the clue mapping from the form fields
        new_clues = {}
        for tag_id in CLUES:
            next_tag = request.form.get(f'next_tag[{tag_id}]', '').strip() or None
            new_clues[tag_id] = {
                'next_tag': next_tag,
                'clue': {
                    'en': request.form.get(f'clue_en[{tag_id}]', '').strip(),
                    'nl': request.form.get(f'clue_nl[{tag_id}]', '').strip(),
                },
            }

        # Optionally append a new tag (only usable if some next_tag points to it)
        new_tag_id = request.form.get('new_tag_id', '').strip()
        if new_tag_id:
            if new_tag_id in new_clues:
                flash(f"Tag '{new_tag_id}' already exists.", "error")
                return redirect(url_for('admin_clues'))
            new_clues[new_tag_id] = {
                'next_tag': request.form.get('new_next_tag', '').strip() or None,
                'clue': {
                    'en': request.form.get('new_clue_en', '').strip(),
                    'nl': request.form.get('new_clue_nl', '').strip(),
                },
            }

        try:
            new_initial = validate_clues(new_clues)
        except RuntimeError as e:
            flash(str(e), "error")
            return redirect(url_for('admin_clues'))

        # Back up the old file before overwriting
        shutil.copy(CLUES_FILE, CLUES_FILE + '.bak')
        with open(CLUES_FILE, 'w') as f:
            yaml.safe_dump(new_clues, f, sort_keys=False, allow_unicode=True)

        CLUES, INITIAL_TAG = new_clues, new_initial
        _clues_mtime = os.path.getmtime(CLUES_FILE)
        flash("Clues updated successfully. A backup was saved to clues.yaml.bak", "info")
        return redirect(url_for('admin_clues'))

    # Walk the chain to display tags in hunt order
    ordered_tags, tag = [], INITIAL_TAG
    while tag is not None:
        ordered_tags.append(tag)
        tag = CLUES[tag].get('next_tag')

    return render_template('admin_clues.html', clues=CLUES, ordered_tags=ordered_tags)

@app.route('/admin/tags')
def admin_tags():
    """Printable QR codes per tag — a fallback for unreadable/broken NFC tags."""
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_dashboard'))

    tags = []
    tag = INITIAL_TAG
    while tag is not None:
        url = url_for('check_clue', tag_id=tag, _external=True)
        img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=8)
        buf = io.BytesIO()
        img.save(buf)
        tags.append({'tag': tag, 'url': url, 'svg': buf.getvalue().decode()})
        tag = CLUES[tag].get('next_tag')

    return render_template('admin_tags.html', tags=tags)

@app.route('/admin/stats')
def admin_stats():
    """Aggregated game statistics for the admin."""
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_dashboard'))

    db = get_db()
    totals = db.execute('''
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN end_time IS NOT NULL THEN 1 ELSE 0 END) AS finished,
               SUM(CASE WHEN end_time IS NULL AND start_time IS NOT NULL THEN 1 ELSE 0 END) AS active,
               SUM(CASE WHEN start_time IS NULL THEN 1 ELSE 0 END) AS not_started
        FROM players
    ''').fetchone()

    durations = db.execute('''
        SELECT AVG(d) AS avg_d, MIN(d) AS min_d, MAX(d) AS max_d FROM (
            SELECT (JULIANDAY(end_time) - JULIANDAY(start_time)) * 86400.0 AS d
            FROM players WHERE end_time IS NOT NULL
        )
    ''').fetchone()

    # Players currently stuck at each stage (or not started yet)
    stalled_rows = db.execute('''
        SELECT current_clue_tag, COUNT(*) AS n FROM players
        WHERE end_time IS NULL
        GROUP BY current_clue_tag
    ''').fetchall()
    stalled = {r['current_clue_tag'] or 'NOT_STARTED': r['n'] for r in stalled_rows}

    # Build per-stage funnel in hunt order
    stages = [{'tag': 'NOT_STARTED', 'clue': 'Registered, timer not started'}]
    tag = INITIAL_TAG
    while tag is not None:
        clue = CLUES[tag].get('clue')
        full = clue.get('en', '') if isinstance(clue, dict) else str(clue)
        snippet = full[:60] + '…' if len(full) > 60 else full
        stages.append({'tag': tag, 'clue': snippet})
        tag = CLUES[tag].get('next_tag')
    for s in stages:
        s['count'] = stalled.get(s['tag'], 0)

    return render_template('admin_stats.html',
                           totals=totals,
                           durations=durations,
                           stages=stages,
                           format_duration=_format_duration)

@app.route('/admin/change_name/<player_id>', methods=['POST'])
def admin_change_name(player_id):
    """Changes a player's name."""
    if not session.get('admin_logged_in'):
        return "Unauthorized", 403
    if not _csrf_valid():
        return "Invalid CSRF token", 403

    new_name = request.form.get('new_name', '').strip()

    if not new_name:
        flash("Player name cannot be empty.", "error")
        return redirect(url_for('admin_dashboard'))

    if profanity.contains_profanity(new_name):
        flash("The new name contains inappropriate language.", "error")
        return redirect(url_for('admin_dashboard'))

    db = get_db()
    # Optional: Check if the new name is already taken by another player
    existing = db.execute("SELECT player_id FROM players WHERE player_name = ? COLLATE NOCASE AND player_id != ?", (new_name, player_id)).fetchone()
    if existing:
        flash(f"The name '{new_name}' is already in use by another player.", "error")
        return redirect(url_for('admin_dashboard'))

    try:
        db.execute("UPDATE players SET player_name = ? WHERE player_id = ?", (new_name, player_id))
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        flash(f"The name '{new_name}' is already in use by another player.", "error")
        return redirect(url_for('admin_dashboard'))
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
