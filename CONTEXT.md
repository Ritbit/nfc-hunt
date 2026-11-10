# Project Context: NFC Treasure Hunt

## 1. Project Overview
A lightweight, mobile-friendly NFC scavenger hunt application. Players use mobile phones to tap physical NFC tags programmed with NDEF URLs. The backend enforces strict clue progression in order, tracks player sessions, and calculates a final score based on completion time.

---

## 2. Tech Stack & Environment
- **Operating System:** Amazon Linux / RHEL-based Linux
- **Language & Runtime:** Python 3 (`python3`, `python3-devel`, `python3-pip`)
- **Web Framework:** Flask
- **Database:** SQLite (`treasure_hunt.db`)
- **Key Python Libraries:** `Flask`, `python-dateutil`, `uwsgi`
- **Application Server:** uWSGI (WSGI master/worker model)
- **Reverse Proxy / Web Server:** Nginx
- **Process Supervision:** Systemd (`systemctl`)

---

## 3. Directory Layout
```text
/var/www/nfc_hunt/
├── app.py                     # Main application logic, DB schema, clue routing
├── clues.yaml                 # Configurable clues and locations
├── profanity_wordlists.py     # Team/player name validation
├── reset_db.py                # Database reset and initialization script
├── treasure_hunt.db           # SQLite database (auto-initialized)
├── static/                    # PWA icons, manifest, service worker, fonts, CSS
├── templates/                 # Jinja2 HTML templates
│   ├── base.html
│   ├── index.html
│   ├── start_game.html
│   ├── resume_game.html
│   ├── clue_display.html
│   ├── leaderboard.html
│   ├── admin_dashboard.html
│   └── error.html
├── CONTEXT.md                 # Project architecture and runtime context
└── AGENTS.md                  # Development rules and agent instructions
```

---

## 4. Game Logic & Data Flow

### Sequence & Tag Registry
The hunt uses a sequential linked list of clue locations defined in `clues.yaml` or `app.py`:
1. `nfc-001` (Start: Coffee / Drink station) → Points to `nfc-002`
2. `nfc-002` (Under casual chair) → Points to `nfc-003`
3. `nfc-003` (Supply cabinet / pen box) → Points to `nfc-004`
4. `nfc-004` (Behind the main clock) → Points to `nfc-005`
5. `nfc-005` (Server rack / firewall) → Final tag (`next_tag: None`, `final: True`)

### Progression Rules
- **Entry Point:** A player starts by scanning `nfc-001` or entering the landing page to register team details.
- **Session Identification:** Players receive a random UUID / session stored in Flask client-side encrypted cookies or local state.
- **Sequential Enforcement:** If a player scans any tag other than `current_clue_tag`, the server rejects the scan and reminds them of their current objective.
- **Completion Scoring:** 
  - `start_time` is recorded on successful scan of the initial clue.
  - `end_time` is recorded on successful scan of the final clue.
  - Total elapsed duration is computed (`end_dt - start_dt`) and formatted as minutes and seconds, published to the leaderboard.

---

## 5. Server Configuration & Deployment

### uWSGI Configuration (`/etc/uwsgi.d/nfc_hunt.ini`)
```ini
[uwsgi]
chdir = /var/www/nfc_hunt
module = app
callable = app

master = true
processes = 5

# Dedicated runtime directory over /tmp
socket = /var/run/uwsgi/nfc_hunt.sock
chmod-socket = 660
vacuum = true

uid = ec2-user
gid = nginx
```

### Nginx Reverse Proxy (`/etc/nginx/conf.d/nfc_hunt.conf`)
```nginx
server {
    listen 80;
    server_name your_domain_or_ip;

    location / {
        include uwsgi_params;
        uwsgi_pass unix:///var/run/uwsgi/nfc_hunt.sock;
    }

    location /static {
        alias /var/www/nfc_hunt/static;
    }
}
```

### Systemd Service (`/etc/systemd/system/nfc_hunt.service`)
```ini
[Unit]
Description=uWSGI instance for NFC Treasure Hunt
After=network.target

[Service]
RuntimeDirectory=uwsgi
RuntimeDirectoryMode=0755
User=ec2-user
Group=nginx
WorkingDirectory=/var/www/nfc_hunt
Environment="PATH=/usr/bin"
ExecStart=/usr/bin/uwsgi --ini /etc/uwsgi.d/nfc_hunt.ini

[Install]
WantedBy=multi-user.target
```

---

## 6. Known Gotchas & Operational Notes
- **uWSGI INI Comments:** Do not place inline comments using `;` or `#` on the same line as directives (e.g. `gid = nginx ; comment`). The uWSGI parser treats trailing text as part of the directive value.
- **Python Development Headers:** Compiling uWSGI on Amazon Linux requires `python3-devel` and `pcre-devel`.
- **Socket Permissions:** Placing Unix sockets in `/tmp` frequently causes `502 Bad Gateway` errors due to standard directory access permissions or SELinux policies. Use `RuntimeDirectory=uwsgi` to manage `/var/run/uwsgi/` sockets cleanly.
- **HTTPS Requirement:** iOS and modern Android NFC handlers require HTTPS (`https://`) to launch URLs silently without safety warnings.
