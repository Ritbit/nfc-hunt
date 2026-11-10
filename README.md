
# 🌊 Ocean Adventure: An NFC-Based Treasure Hunt Game

Welcome to Ocean Adventure, a web-based, interactive treasure hunt game powered by Flask and Web NFC technology. Players embark on a voyage by registering their name, solving clues, and scanning physical NFC tags to progress through the hunt. The goal is to complete the adventure in the shortest time possible and earn a spot on the Deep Sea Leaderboard!

This application is designed to be a Progressive Web App (PWA), allowing users to "install" it to their home screen for a more native app-like experience.

## ✨ Features

- **Player Registration**: Simple and quick registration with a player name.
- **Profanity Filter**: Player names are checked against a Dutch profanity list to keep things friendly.
- **Unique Player Names**: Prevents multiple players from using the same name (case-insensitive).
- **Timed Gameplay**: A timer starts as soon as the player views the first clue and stops upon scanning the final tag.
- **NFC Integration**: Uses the Web NFC API for a seamless tag-scanning experience on compatible mobile devices.
- **Dynamic Clue System**: Clues and the hunt sequence are managed via a simple `clues.yaml` file.
- **Leaderboard**: A public leaderboard displays the top 10 fastest players.
- **Admin Dashboard**: A password-protected area to monitor player progress, manage players (rename/remove), and reset the entire game.
- **PWA Ready**: Includes a service worker and manifest to be installable on mobile devices.

## ⚙️ How It Works

1. **Register**: A player visits the home page and enters their name to start.
2. **First Clue**: The game starts, the timer begins, and the first clue is displayed.
3. **Hunt**: The player must solve the clue, which leads them to a physical location with an NFC tag.
4. **Scan**: Using their phone, the player scans the NFC tag. The app's front-end uses the Web NFC API to read the tag's ID.
5. **Progress**: The app sends the scanned tag ID to the Flask backend.
    - If the tag is **correct**, the player is shown the next clue.
    - If the tag is **incorrect**, an error message is displayed, prompting them to try again.
6. **Finish**: Upon scanning the final tag, the timer stops. The player is shown their total time and their rank on the leaderboard.
7. **Compete**: Players can view the leaderboard at any time to see how they stack up against other explorers.

## 🚀 Getting Started

Follow these instructions to get the application running on your own server.

### Prerequisites

- Python 3.7+
- `pip` (Python package installer)
- A web server (like Nginx or Apache) for production deployment.
- Physical NFC tags programmed with the IDs from `clues.yaml` (e.g., `nfc-mirror`, `nfc-ADAM`, etc.).

### Installation

1. **Clone the repository:**

    ```bash
    git clone <your-repository-url>
    cd adyen-nfc_hunt
    ```

2. **Create and activate a virtual environment (recommended):**

    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3. **Install the required Python packages:**

    ```bash
    pip install -r requirements.txt
    ```

4. **Set the Flask Secret Key:**
    For security, the application's session key should be set as an environment variable.

    ```bash
    export FLASK_SECRET_KEY='a_very_strong_and_random_secret_key'
    ```

### Running the Application

#### For Development

You can use the built-in Flask development server. This is not suitable for production.

```bash
flask run --host=0.0.0.0 --port=5000
```

The app will be available at `http://<your-local-ip>:5000`.

#### For Production (with Gunicorn & Nginx)

1. **Run with Gunicorn:**
    Gunicorn is a robust WSGI HTTP server for UNIX.

    ```bash
    gunicorn --workers 3 --bind unix:adyen-nfc_hunt.sock -m 007 app:app
    ```

2. **Configure Nginx as a reverse proxy:**
    Set up an Nginx server block to proxy requests to the Gunicorn socket. This is also where you would configure SSL/TLS for HTTPS, which is **required** for the Web NFC API to work.

## 🔧 Configuration

### Clues

Modify `clues.yaml` to change the clues, add new steps, or alter the sequence of the hunt. The final clue in the sequence is identified by having `next_tag: null`.

### Admin Access

The admin password is set via an environment variable for security. Before running the application, set the `ADMIN_PASSWORD` variable.

```bash
export ADMIN_PASSWORD='your_super_secret_password'
```

The dashboard is available at `/admin/dashboard`. The app refuses to start if `ADMIN_PASSWORD` is not set — there is no insecure default.

### Database

The application uses SQLite (`treasure_hunt.db`). The database is created automatically. To reset all player data, you can use the reset button in the admin dashboard or run the `reset_db.py` script directly:

```bash
python3 reset_db.py
```
