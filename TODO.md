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
- [x] **Scan-first entry point**: scanning `nfc-mirror` as a registered player (before `/start`) now starts the timer and advances to the second clue.
- [x] **Reconciled clue schema docs**: AGENTS.md documented a `final:` flag the code ignores — docs updated; "final" is derived from `next_tag: null`.
- [x] **CSRF protection on admin POST routes** (`/admin/reset`, `/admin/remove_player`, `/admin/change_name`, login): session token checked on every POST.
- [x] **Rate limit registration and admin login**: 10 registrations/min and 10 login attempts/5min per IP, in-process (note: uWSGI workers multiply effective limits).
- [x] **Server-side uniqueness constraint** on `player_name COLLATE NOCASE` — unique index created in `init_db`/`reset_db.py`; `IntegrityError` handled at insert and rename.
- [x] **Admin dashboard**: `last_scan_time` column added (spot stalled players), sortable columns (name/start/last scan/duration), status filter (all/active/finished).
- [x] **Countdown/timer display**: live elapsed-time counter on `start_game`, `resume_game`, and `clue_display` via shared `templates/_timer.html`.

## Feature ideas (brainstorm)

Cheap wins:

- [x] **Wrong-tag counter**: `wrong_scans` column (migrated), incremented on each bad scan, shown on finish screen + admin dashboard.
- [x] **Celebration feedback**: confetti + `navigator.vibrate` on `clue_display` (bigger burst on the final tag); shake + vibrate on the error page.
- [x] **QR fallback**: `/admin/tags` renders printable SVG QR codes per tag (print-friendly CSS), linked from the dashboard.
- [x] **Podium medals**: 🥇🥈🥉 replace #1–#3 on the leaderboard.
- [x] **Players still hunting**: finish screen shows "N explorers still out there hunting!".

Medium:

- [x] **Teams**: `team_name` on registration + column; Top Teams table on leaderboard (ranked by fastest finisher); admin column + CSV field.
- [x] **Hint system**: optional `hint: {en, nl}` per clue (editable in `/admin/clues`); `/hint` route shows it and counts `hints_used`; shown on finish screen.
- [x] **Live admin feed**: `scans` event table logs every scan (correct/wrong); "Recent Scans" table on dashboard auto-refreshes every 15s in place.
- [ ] **Countdown race mode**: fixed time limit, score = clues found.
- [ ] **Randomized clue order per player**: shuffled chain stored per player, kills tag-queuing.

Bigger:

- [ ] **Photo finish**: selfie upload at final tag, hall-of-fame gallery.
- [ ] **Websocket leaderboard**: Flask-SocketIO is already installed; push updates instead of polling.
- [x] **CSV export**: `/admin/export.csv` streams all player data (name, team, times, wrong scans, hints).

## Longer-term extensions

- [x] **Automated tests** (pytest): `tests/test_app.py` — 21 tests covering registration, profanity/duplicate names, sequential traversal, scan-first start, out-of-order rejection, rescans, admin auth, CSRF, pagination clamp, and DB reset. Run: `pytest tests/`.
- [ ] **Multiple hunts / configurable entry tag** (deferred — decide scope first):
  - Option A: multiple clue sets, admin picks which single hunt is active.
  - Option B: parallel hunts chosen at registration, `hunt_id` on players + per-hunt leaderboards.
- [x] **Admin clue editor**: `/admin/clues` — edit `next_tag` + EN/NL clue text per tag, add new tags; chain validated before save, backup written to `clues.yaml.bak`.
- [x] **i18n toggle**: `clues.yaml` uses `{en, nl}` clue maps (plain strings still supported); language select at registration + global 🇬🇧/🇳🇱 toggle via `/lang/<lang>`.
- [x] **Stats panel**: `/admin/stats` — registered/active/finished counts, avg/min/max completion time, per-stage player distribution with bars.
- [x] **Deployment artifacts**: uWSGI ini, nginx conf, and systemd unit now versioned in `deploy/` (from CONTEXT.md).
- [x] **Time adjustment in admin**: `/admin/adjust_time/<player_id>` — set start/end times via datetime pickers or clear `end_time` to reopen a game. CSRF-protected.
