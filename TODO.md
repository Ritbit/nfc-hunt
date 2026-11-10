# TODO / Improvement Plan — Ocean Adventure NFC Hunt

## Bugs & Code Quality (fix now)

- [x] **Admin pagination not clamped** (`app.py`): `?page=99` renders an empty table with no way back; `page=0`/negative produces odd output. Clamp page to `[1, total_pages]`. (CodeRabbit)
- [x] **Leaderboard meta refresh** (`leaderboard.html`): full-page reload every 30s breaks keyboard focus and screen readers. Replace with a small JS poll that updates the table in place. (CodeRabbit)
- [x] **Redundant player re-fetch** (`check_clue`): `player_row` is fetched twice; drop the second query.
- [x] **Stale session in `start_game`**: if the player row was deleted (admin remove), the page still renders the first clue. Clear session and redirect to index instead.
- [x] **No validation of `clues.yaml`**: a broken `next_tag` pointer causes a `KeyError` mid-game. Validate the chain at startup (all `next_tag`s resolve, exactly one entry point, single final tag, no cycles).
- [x] **Dead file**: `templates/admin_clues.html` is empty with no route — removed.
- [x] **Missing `.gitignore`**: `nfc-hunt.tgz`, `treasure_hunt.db`, `__pycache__`, `.mypy_cache` should never be committed.

## Short-term improvements

- [x] **`requirements.txt`** — README told users to create it; now shipped.
- [ ] **Scan-first entry point**: AGENTS.md says a player may start by scanning `nfc-mirror`, but a scan before `/start` is rejected (`current_clue_tag` is NULL). Let a valid first-tag scan start the timer.
- [x] **Reconciled clue schema docs**: AGENTS.md documented a `final:` flag the code ignores — docs updated; "final" is derived from `next_tag: null`.
- [ ] **CSRF protection on admin POST routes** (`/admin/reset`, `/admin/remove_player`, `/admin/change_name`): add a session token check or Flask-WTF.
- [ ] **Rate limit registration and admin login** to slow down name-squatting / password brute force.
- [ ] **Server-side uniqueness constraint** on `player_name COLLATE NOCASE` — currently only enforced by a check-then-insert race.
- [ ] **Admin dashboard**: show `last_scan_time` (detect stalled players), sort/filter by progress, link player rows.
- [ ] **Countdown/timer display** on `start_game`/`resume_game`/`clue_display` so players see elapsed time.

## Longer-term extensions

- [ ] **Automated tests** (pytest): sequential traversal, out-of-order rejection, finished-player rescans, name validation, admin auth.
- [ ] **Multiple hunts / configurable entry tag**: support parallel hunts or team vs solo modes.
- [ ] **Admin clue editor**: fill in `admin_clues.html` — edit `clues.yaml` from the dashboard with validation.
- [ ] **i18n toggle**: clues are already bilingual (EN/NL) — let players pick a language instead of showing both.
- [ ] **Stats panel**: average completion time, drop-off per clue, scan timestamps chart.
- [ ] **Deployment artifacts**: ship the uWSGI ini / nginx conf / systemd unit from CONTEXT.md as files in `deploy/` so the server setup is versioned.
- [ ] **Time adjustment in admin**: fix accidental starts or manually set start/end times.
