#!/bin/env python3
import os
import sqlite3

# --- Configuration ---
# This script assumes it's in the same directory as app.py and the database.
basedir = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.environ.get('DATABASE', os.path.join(basedir, 'treasure_hunt.db'))

def reset_database():
    """
    Deletes the existing database file and creates a new, empty one
    with the required 'players' table.
    """
    # 1. Delete the old database file if it exists
    if os.path.exists(DATABASE):
        print(f"Deleting existing database: {DATABASE}")
        os.remove(DATABASE)
        print("Database deleted.")
    else:
        print("No existing database found. A new one will be created.")

    # 2. Create a new database and the 'players' table
    print("Initializing new database...")
    conn = sqlite3.connect(DATABASE)
    conn.execute('''
        CREATE TABLE players (
            player_id TEXT PRIMARY KEY,
            player_name TEXT NOT NULL,
            current_clue_tag TEXT,
            last_scan_time DATETIME,
            start_time DATETIME,
            end_time DATETIME
        )
    ''')
    conn.execute(
        'CREATE UNIQUE INDEX IF NOT EXISTS idx_players_name '
        'ON players(player_name COLLATE NOCASE)'
    )
    conn.commit()
    conn.close()

    # Note: File ownership (chown) has been removed from this script.
    # Permissions should be managed by the deployment process or the user running the server.
    # For example, after running this script, you might run: `chown adyen:nginx treasure_hunt.db`
    print("Database has been reset successfully.")

if __name__ == '__main__':
    # Ask for confirmation before proceeding to prevent accidental deletion
    confirm = input("Are you sure you want to reset the database? All player data will be lost. (yes/no): ")
    if confirm.lower() == 'yes':
        reset_database()
    else:
        print("Database reset cancelled.")
