# Agent Guidelines: NFC Treasure Hunt

This document provides instructions, operational boundaries, and code standards for AI agents and developers modifying this codebase.

---

## 1. System Philosophy
- **Keep it minimal:** Simple Flask, built-in SQLite3, and responsive Jinja2 templates.
- **Zero client app requirements:** Works directly via standard mobile browsers (Safari / Chrome) when scanning NFC tags.
- **Reliable sequential progression:** State enforcement occurs strictly on the server, never client-side.

---

## 2. Coding Standards & Conventions

### Python Backend (`app.py`, helper scripts)
- Adhere to PEP 8 standards.
- Keep database operations explicit. When querying SQLite:
  - Always use parameterized queries (`?`) to prevent SQL injection.
  - Use `conn.row_factory = sqlite3.Row` for dict-like row access.
  - Ensure transactions are committed (`db.commit()`) immediately after state mutations.
- Keep helper scripts modular (`reset_db.py`, `profanity_wordlists.py`).

### Clue Registry & Configuration (`clues.yaml` / `app.py`)
Every entry in the clue configuration must adhere to this schema:
```yaml
tag_id:
  next_tag: next_tag_id_or_null
  clue:
    en: "English clue text"    # required
    nl: "Dutch clue text"      # optional
  hint:
    en: "Optional English hint"
    nl: "Optional Dutch hint"
```
`hint` is optional entirely; when present as a dict, `en` must be non-empty.
`clue` may also be a plain string (legacy format); localized dicts are preferred.
The final clue is identified by `next_tag: null` — there is no separate `final` flag.
The chain is validated at startup: every `next_tag` must resolve, exactly one
unreferenced start tag and one final tag must exist, and the chain must cover
all tags without cycles. Clues can also be edited via `/admin/clues`.

### HTML & Templates (`templates/`)
- Mobile-first, responsive layouts: All templates must look clean on portrait smartphone screens (360px–430px wide).
- Keep styles organized in `static/ocean_adventure.css` or embedded where appropriate.
- Maintain PWA compatibility (manifest and service worker in `static/`).

---

## 3. Safe Modification Playbooks

### Adding or Reordering Locations
1. Update `clues.yaml` (or `CLUES` in `app.py`).
2. Ensure the `next_tag` pointer of tag $N$ matches the key of tag $N+1$.
3. Ensure the initial tag matches the starting configuration.
4. Ensure the last clue has `next_tag: null` / `None` and `final: true`.

### Changing Database Schema
1. For schema modifications, write explicit migration steps or update `reset_db.py`.
2. Reinitialize the database cleanly when testing schema updates.

### Infrastructure & Configuration Edits
- When editing `/etc/uwsgi.d/nfc_hunt.ini`:
  - Never add inline comments (`#` or `;` on the same line as a directive).
  - Put comments on their own separate line starting with `#`.
- After any systemd or INI modification:
  ```bash
  sudo systemctl daemon-reload
  sudo systemctl restart nfc_hunt
  sudo systemctl restart nginx
  ```

---

## 4. Verification & Testing Checklist

Before every commit:

1. Run the test suite: `pytest tests/` (all tests must pass).
2. Run CodeRabbit on the changes: `coderabbit review --agent` and fix or
   explicitly dismiss each finding before committing.

When testing changes locally or on server:

When testing changes locally or on server:
1. **Fresh Player Flow:**
   ```bash
   curl -c cookies.txt -b cookies.txt -L http://127.0.0.1:5000/hunt/clue/nfc-001
   ```
   Verify HTTP 200 and receipt of session cookie.
2. **Out-of-Order Attempt:**
   ```bash
   curl -c cookies.txt -b cookies.txt -L http://127.0.0.1:5000/hunt/clue/nfc-003
   ```
   Verify rejection message stating that `nfc-002` is currently expected.
3. **Sequential Traversal:**
   Sequentially request all tags in order.
   Verify the final response returns completion time in minutes and seconds.
4. **Repeat Scan After Finish:**
   Request the final tag again with the same session cookie.
   Verify it cleanly renders the finished score page without recalculating or throwing errors.
