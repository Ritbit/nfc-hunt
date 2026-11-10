import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('ADMIN_PASSWORD', 'test-admin-password')

import pytest

import app as app_module
import reset_db as reset_db_module

TAGS = list(app_module.CLUES)          # ordered tag chain
FIRST_TAG = TAGS[0]
FINAL_TAG = TAGS[-1]
ADMIN_PW = os.environ['ADMIN_PASSWORD']


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A test client backed by a fresh, isolated SQLite database."""
    db_path = str(tmp_path / 'test.db')
    monkeypatch.setattr(app_module, 'DATABASE', db_path)
    monkeypatch.setattr(reset_db_module, 'DATABASE', db_path)
    app_module.init_db()
    app_module._attempts.clear()       # reset rate limiter between tests
    app_module.app.config['TESTING'] = True
    with app_module.app.test_client() as c:
        yield c


def register(client, name='Explorer'):
    return client.post('/', data={'player_name': name})


def csrf_token(client):
    """Render the admin login page (which issues a token) and read it back."""
    client.get('/admin/dashboard')
    with client.session_transaction() as s:
        return s['csrf_token']


def admin_login(client):
    token = csrf_token(client)
    return client.post('/admin/dashboard',
                       data={'password': ADMIN_PW, 'csrf_token': token},
                       follow_redirects=True)


# --- Registration ---

def test_index_renders(client):
    assert client.get('/').status_code == 200


def test_register_redirects_to_start(client):
    r = register(client)
    assert r.status_code == 302 and '/start' in r.headers['Location']


def test_register_rejects_empty_name(client):
    r = client.post('/', data={'player_name': '   '}, follow_redirects=True)
    assert b'cannot be empty' in r.data


def test_register_rejects_profanity(client):
    r = client.post('/', data={'player_name': 'klootzak'}, follow_redirects=True)
    assert b'inappropriate language' in r.data


def test_register_rejects_duplicate_name_case_insensitive(client):
    register(client, 'Skipper')
    with client.session_transaction():
        pass  # ensure first registration is committed
    # New client simulates a second browser registering the same name
    with app_module.app.test_client() as c2:
        r = c2.post('/', data={'player_name': 'skipper'}, follow_redirects=True)
        assert b'already on a voyage' in r.data


# --- Game progression ---

def test_start_sets_timer_once(client):
    register(client)
    client.get('/start')
    with app_module.app.test_request_context():
        db = app_module.get_db()
        row = db.execute("SELECT start_time, current_clue_tag FROM players").fetchone()
        assert row['start_time'] is not None
        assert row['current_clue_tag'] == FIRST_TAG


def test_scan_first_tag_starts_game(client):
    """Scanning the first NFC tag without visiting /start starts the timer."""
    register(client)
    r = client.get(f'/hunt/clue/{FIRST_TAG}')
    assert r.status_code == 200
    assert b'Incorrect tag' not in r.data
    with app_module.app.test_request_context():
        db = app_module.get_db()
        row = db.execute("SELECT start_time, current_clue_tag FROM players").fetchone()
        assert row['start_time'] is not None
        assert row['current_clue_tag'] == TAGS[1]


def test_scan_wrong_first_tag_rejected(client):
    register(client)
    r = client.get(f'/hunt/clue/{FINAL_TAG}')
    assert b'Incorrect tag' in r.data


def test_out_of_order_scan_rejected(client):
    register(client)
    client.get('/start')
    r = client.get(f'/hunt/clue/{FINAL_TAG}')
    assert b'Incorrect tag' in r.data


def test_full_sequential_traversal(client):
    register(client)
    client.get('/start')
    for i, tag in enumerate(TAGS):
        r = client.get(f'/hunt/clue/{tag}')
        assert r.status_code == 200
        if i < len(TAGS) - 1:
            assert b'Incorrect tag' not in r.data
            next_clue = app_module.CLUES[TAGS[i + 1]]['clue']
            expected = next_clue['en'] if isinstance(next_clue, dict) else next_clue
            assert expected[:30].encode() in r.data
    assert b'minutes and' in r.data


def test_rescan_after_finish_redirects_to_leaderboard(client):
    register(client)
    for tag in TAGS:
        client.get(f'/hunt/clue/{tag}')
    r = client.get(f'/hunt/clue/{FIRST_TAG}')
    assert r.status_code == 302 and '/leaderboard' in r.headers['Location']


def test_unregistered_scan_redirects_to_index(client):
    r = client.get(f'/hunt/clue/{FIRST_TAG}')
    assert r.status_code == 302
    with client.session_transaction() as s:
        assert s.get('player_id') is None


def test_leaderboard_lists_finisher(client):
    register(client, 'Champion')
    for tag in TAGS:
        client.get(f'/hunt/clue/{tag}')
    assert b'Champion' in client.get('/leaderboard').data


# --- Admin ---

def test_admin_requires_password(client):
    r = client.get('/admin/dashboard')
    assert b'enter the password' in r.data.lower()


def test_admin_rejects_wrong_password(client):
    token = csrf_token(client)
    r = client.post('/admin/dashboard',
                    data={'password': 'wrong', 'csrf_token': token})
    assert b'Incorrect password' in r.data


def test_admin_login_and_player_listed(client):
    register(client, 'VisiblePlayer')
    admin_login(client)
    r = client.get('/admin/dashboard')
    assert b'VisiblePlayer' in r.data


def test_admin_dashboard_clamps_page(client):
    admin_login(client)
    assert client.get('/admin/dashboard?page=999').status_code == 200
    assert client.get('/admin/dashboard?page=-3').status_code == 200


def test_admin_reset_requires_csrf(client):
    admin_login(client)
    assert client.post('/admin/reset').status_code == 403


def test_admin_reset_with_csrf(client):
    register(client, 'ToBeWiped')
    admin_login(client)
    with client.session_transaction() as s:
        token = s['csrf_token']
    r = client.post('/admin/reset', data={'csrf_token': token}, follow_redirects=True)
    assert r.status_code == 200
    with app_module.app.test_request_context():
        db = app_module.get_db()
        assert db.execute('SELECT COUNT(*) FROM players').fetchone()[0] == 0


def test_admin_remove_player_requires_csrf(client):
    register(client)
    admin_login(client)
    assert client.post('/admin/remove_player/whatever').status_code == 403


def test_admin_rename_requires_csrf(client):
    register(client)
    admin_login(client)
    r = client.post('/admin/change_name/whatever', data={'new_name': 'X'})
    assert r.status_code == 403


def test_admin_status_filter(client):
    register(client, 'Finisher')
    for tag in TAGS:
        client.get(f'/hunt/clue/{tag}')
    with app_module.app.test_client() as c2:
        c2.post('/', data={'player_name': 'StillPlaying'})
        c2.get('/start')
    admin_login(client)
    r = client.get('/admin/dashboard?status=finished')
    assert b'Finisher' in r.data and b'StillPlaying' not in r.data
    r = client.get('/admin/dashboard?status=active')
    assert b'StillPlaying' in r.data and b'Finisher' not in r.data


def test_admin_sort_param_accepted(client):
    admin_login(client)
    for sort in ('start', 'last_scan', 'name', 'duration', 'bogus'):
        assert client.get(f'/admin/dashboard?sort={sort}').status_code == 200


def test_admin_adjust_time_requires_csrf(client):
    register(client)
    admin_login(client)
    r = client.post('/admin/adjust_time/whatever', data={'start_time': '2025-01-01T10:00'})
    assert r.status_code == 403


def test_admin_adjust_time_updates_player(client):
    register(client, 'TimeTraveler')
    client.get('/start')
    admin_login(client)
    with client.session_transaction() as s:
        token = s['csrf_token']
        player_id = s['player_id'] if 'player_id' in s else None
    # session is shared; fetch the player's id from the DB
    with app_module.app.test_request_context():
        db = app_module.get_db()
        pid = db.execute("SELECT player_id FROM players WHERE player_name = 'TimeTraveler'").fetchone()['player_id']
    r = client.post(f'/admin/adjust_time/{pid}', data={
        'csrf_token': token,
        'start_time': '2020-01-01T10:00',
        'end_time': '2020-01-01T11:30',
    }, follow_redirects=True)
    assert r.status_code == 200
    with app_module.app.test_request_context():
        db = app_module.get_db()
        row = db.execute("SELECT start_time, end_time FROM players WHERE player_id = ?", (pid,)).fetchone()
        assert row['start_time'] == '2020-01-01 10:00:00'
        assert row['end_time'] == '2020-01-01 11:30:00'


def test_start_page_shows_elapsed_timer(client):
    register(client)
    r = client.get('/start')
    assert b'elapsedTimer' in r.data


def test_resume_page_shows_elapsed_timer(client):
    register(client)
    client.get('/start')
    r = client.get('/resume')
    assert b'elapsedTimer' in r.data


# --- i18n ---

def test_language_toggle_serves_dutch_clue(client):
    register(client)
    client.get('/lang/nl')
    r = client.get('/start')
    dutch = app_module.CLUES[FIRST_TAG]['clue']['nl']
    assert dutch[:30].encode() in r.data


def test_default_language_is_english(client):
    register(client)
    r = client.get('/start')
    english = app_module.CLUES[FIRST_TAG]['clue']['en']
    assert english[:30].encode() in r.data


def test_registration_language_select(client):
    client.post('/', data={'player_name': 'Tulpen', 'language': 'nl'})
    with client.session_transaction() as s:
        assert s['lang'] == 'nl'


def test_invalid_language_ignored(client):
    client.get('/lang/klingon')
    with client.session_transaction() as s:
        assert s.get('lang') != 'klingon'


# --- Admin clue editor ---

def test_admin_clues_requires_login(client):
    r = client.get('/admin/clues')
    assert r.status_code == 302 and 'dashboard' in r.headers['Location']


def test_admin_clues_saves_valid_chain(client, tmp_path, monkeypatch):
    # Point the clues file at a throwaway copy so the real clues.yaml is untouched
    import yaml
    orig_clues = dict(app_module.CLUES)
    tmp_clues = tmp_path / 'clues.yaml'
    tmp_clues.write_text(yaml.safe_dump(orig_clues, allow_unicode=True))
    monkeypatch.setattr(app_module, 'CLUES_FILE', str(tmp_clues))

    admin_login(client)
    data = {'csrf_token': csrf_token(client)}
    for tag in TAGS:
        data[f'next_tag[{tag}]'] = app_module.CLUES[tag]['next_tag'] or ''
        data[f'clue_en[{tag}]'] = 'edited en'
        data[f'clue_nl[{tag}]'] = 'edited nl'
    r = client.post('/admin/clues', data=data, follow_redirects=True)
    assert b'Clues updated' in r.data
    assert app_module.CLUES[FIRST_TAG]['clue']['en'] == 'edited en'
    app_module.CLUES = orig_clues  # restore module state for other tests


def test_admin_clues_rejects_broken_chain(client):
    admin_login(client)
    data = {'csrf_token': csrf_token(client)}
    for tag in TAGS:
        data[f'next_tag[{tag}]'] = 'nonexistent-tag'
        data[f'clue_en[{tag}]'] = 'x'
        data[f'clue_nl[{tag}]'] = 'x'
    r = client.post('/admin/clues', data=data, follow_redirects=True)
    assert b'FATAL' in r.data


def test_admin_clues_post_requires_csrf(client):
    admin_login(client)
    assert client.post('/admin/clues', data={}).status_code == 403


# --- Admin stats ---

def test_admin_stats_requires_login(client):
    r = client.get('/admin/stats')
    assert r.status_code == 302 and 'dashboard' in r.headers['Location']


def test_admin_stats_renders(client):
    register(client, 'StatPlayer')
    for tag in TAGS:
        client.get(f'/hunt/clue/{tag}')
    admin_login(client)
    r = client.get('/admin/stats')
    assert r.status_code == 200
    assert b'Game Statistics' in r.data and b'Average Time' in r.data
