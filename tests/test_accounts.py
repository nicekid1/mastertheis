"""Authentication and tenant boundaries through real HTTP, no auth bypass."""
import concurrent.futures
from contextlib import closing
import json
import os
import httpx
import pytest
from app import server
from app.auth import Accounts, verify


def make_user(client, name):
    result = client.post('/api/admin/users', json={'username': name, 'password': 'user-password-1234'})
    assert result.status_code == 200, result.text
    c = httpx.Client(base_url=str(client.base_url), headers={'X-GISclaw': '1'}, timeout=30)
    result = c.post('/api/auth/login', json={'username': name, 'password': 'user-password-1234'})
    assert result.status_code == 200, result.text
    return c, result.json()


def test_passwords_sessions_and_last_admin(tmp_path):
    store = Accounts(str(tmp_path))
    user = store.create('administrator', 'long-password-123', 'admin')
    assert user['password'] != 'long-password-123'
    assert verify('long-password-123', user['password'])
    token, _ = store.login('administrator', 'long-password-123', 'localhost')
    assert store.session(token)['id'] == user['id']
    with store.db() as db:
        assert db.execute('SELECT token FROM sessions').fetchone()[0] != token
    with pytest.raises(ValueError):
        store.update(user['id'], active=False)
    store.update(user['id'], password='changed-password-123')
    assert store.session(token) is None
    for _ in range(10):
        with pytest.raises(ValueError):
            store.login('administrator', 'wrong-password', 'bad-address')
    with pytest.raises(ValueError):
        store.login('administrator', 'changed-password-123', 'bad-address')


def test_unauthenticated_and_role_boundaries(client):
    with httpx.Client(base_url=str(client.base_url)) as anon:
        for path in ('/api/projects', '/api/models', '/api/account', '/api/admin/users', '/api/settings'):
            assert anon.get(path).status_code == 401
        assert anon.post('/api/auth/login', json={}).status_code == 403
    c, user = make_user(client, 'ordinary_user')
    with closing(c):
        for path in ('/api/skills', '/api/memory', '/api/browse', '/api/admin/users', '/api/settings/local', '/api/settings/basemap'):
            assert c.get(path).status_code == 403, path
        assert 'providers' not in c.get('/api/settings').json()
        assert all('base_url' not in m for m in c.get('/api/models?all=1').json())
        assert 'masked_key' not in c.get('/api/map').json()
        assert c.post('/api/admin/users', json={'username': 'escalation', 'password': 'user-password-1234', 'role': 'admin'}).status_code == 403
        assert c.post('/api/settings/providers/openai', json={'api_key': 'attacker'}).status_code == 403
        assert c.post('/api/run', json={'project_id': 'anything'}).status_code == 403
        assert c.get('/api/run/unknown/stream').status_code == 403
        assert c.get('/api/run/active').json() == {'active': None}
        assert c.post('/api/auth/logout', json={}).status_code == 200
        assert c.get('/api/projects').status_code == 401


def test_server_profile_fails_closed_without_isolated_worker(client, monkeypatch):
    from app import isolated_analysis

    monkeypatch.setenv('GISCLAW_DISABLE_LEGACY_RUN', '1')
    monkeypatch.setattr(isolated_analysis, 'available', lambda: False)
    profile = client.get('/api/auth/me').json()
    assert profile['legacy_run_enabled'] is False
    assert profile['analysis_enabled'] is False
    response = client.post('/api/run', json={
        'project_id': 'not-used', 'model': 'not-used', 'instruction': 'must not run'
    })
    assert response.status_code == 503
    assert response.json()['code'] == 'legacy_run_disabled'

    monkeypatch.setattr(isolated_analysis, 'available', lambda: True)
    profile = client.get('/api/auth/me').json()
    assert profile['analysis_enabled'] is True
    assert profile['isolated_analysis_enabled'] is True
    assert profile['legacy_run_enabled'] is False


def test_two_users_have_separate_projects_preferences_and_files(client):
    alice, a = make_user(client, 'tenant_alice')
    bob, b = make_user(client, 'tenant_bob')
    with closing(alice), closing(bob):
        for c in (alice, bob):
            assert c.post('/api/projects', json={'name': 'shared-name'}).status_code == 200
        assert alice.post('/api/projects/shared-name/upload?name=secret.txt', content=b'alice private data').status_code == 200
        assert bob.get('/api/projects/shared-name/file?path=secret.txt').status_code == 404
        assert alice.get('/api/projects/shared-name/tree').json()['data'] == ['secret.txt']
        assert bob.get('/api/projects/shared-name/tree').json()['data'] == []
        assert alice.post('/api/settings/ui', json={'language': 'en'}).status_code == 200
        assert bob.get('/api/settings').json()['language'] == 'fa'
        assert alice.post('/api/projects/shared-name/rename', json={'name': 'alice-project'}).status_code == 200
        assert bob.get('/api/projects').json()[0]['id'] == 'shared-name'
        files = client.get(f"/api/admin/users/{a['id']}/files").json()
        assert any(f['path'] == 'alice-project/data/secret.txt' for f in files)
        assert bob.get(f"/api/admin/users/{a['id']}/files").status_code == 403
        assert client.get(f"/api/admin/users/{a['id']}/file", params={'path': 'alice-project/data/secret.txt'}).content == b'alice private data'
        assert client.patch('/api/admin/users/' + a['id'], json={'active': False}).status_code == 200
        assert alice.get('/api/projects').status_code == 401


def test_quota_serializes_uploads_and_counts_documents(client):
    c, user = make_user(client, 'quota_user')
    with closing(c):
        assert c.post('/api/projects', json={'name': 'quota'}).status_code == 200
        # Small quota makes the test cheap; production defaults to 50 MiB.
        with server.ACCOUNTS.db() as db:
            db.execute('UPDATE users SET quota=? WHERE id=?', (100_000, user['id']))
        def upload(n):
            return c.post(f'/api/projects/quota/documents/upload?name={n}.txt', content=b'x' * 25000).status_code
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            codes = list(pool.map(upload, (1, 2)))
        assert sorted(codes) == [200, 413]
        assert c.get('/api/account').json()['used_bytes'] < 100_000
        assert len(c.get('/api/projects/quota/tree').json()['documents']) == 1
        # Hidden directories must still consume quota.
        root = server.ACCOUNTS.root(server.ACCOUNTS.get(user['id']))
        hidden = os.path.join(root, '.users')
        os.mkdir(hidden)
        with open(os.path.join(hidden, 'counted.bin'), 'wb') as stream:
            stream.write(b'x' * 5000)
        assert c.get('/api/account').json()['used_bytes'] >= 30000


def test_symlink_escape_and_traversal_are_refused(client):
    from app.paths import safe_join
    c, user = make_user(client, 'symlink_user')
    with closing(c):
        root = server.ACCOUNTS.root(server.ACCOUNTS.get(user['id']))
        os.symlink(server.WORKSPACE, os.path.join(root, 'escape'))
        with pytest.raises(ValueError):
            safe_join(root, 'escape', '.gisclaw/settings.json')
        assert client.get(f"/api/admin/users/{user['id']}/file", params={'path': '../.gisclaw/settings.json'}).status_code == 404


def test_password_change_revokes_current_cookie(client):
    c, user = make_user(client, 'password_user')
    with closing(c):
        r = c.post('/api/auth/password', json={'current_password': 'user-password-1234', 'new_password': 'new-secure-password-123'})
        assert r.status_code == 200
        assert c.get('/api/auth/me').status_code == 401
        r = c.post('/api/auth/login', json={'username': user['username'], 'password': 'new-secure-password-123'})
        assert r.status_code == 200
        cookie = r.headers['set-cookie'].lower()
        assert 'httponly' in cookie and 'samesite=strict' in cookie


def test_short_passwords_are_accepted_but_empty_passwords_are_not(tmp_path):
    store = Accounts(str(tmp_path))
    user = store.create('short_password', '1')
    assert verify('1', user['password'])
    token, _ = store.login('short_password', '1', 'local')
    assert store.session(token)
    store.update(user['id'], password='2')
    assert verify('2', store.get(user['id'])['password'])
    for password in ('', None, 'x' * 257):
        with pytest.raises(ValueError):
            store.create('invalid_password', password)


def test_registration_disabled_for_everyone(client):
    with httpx.Client(base_url=str(client.base_url), headers={'X-GISclaw': '1'}) as anon:
        for route in ('/api/auth/register', '/api/auth/signup'):
            assert anon.post(route, json={'username': 'public_signup', 'password': '1'}).status_code == 403
            assert client.post(route, json={'username': 'public_signup', 'password': '1'}).status_code == 403


def test_only_admin_can_resize_quota_and_existing_files_survive(client):
    c, user = make_user(client, 'resized_quota_user')
    url = '/api/admin/users/' + user['id']
    with closing(c):
        assert c.post('/api/projects', json={'name': 'quota-edit'}).status_code == 200
        upload = '/api/projects/quota-edit/upload?name=keep.txt'
        assert c.post(upload, content=b'keep this file').status_code == 200
        assert c.patch(url, json={'quota': 100 * 1048576}).status_code == 403
        for invalid in (-1, True, 1.5, '50', 2**53):
            assert client.patch(url, json={'quota': invalid}).status_code == 400
        assert c.get('/api/account').json()['quota'] == 50 * 1048576
        assert client.patch(url, json={'quota': 0}).status_code == 200
        assert c.get('/api/account').json()['quota'] == 0
        assert c.post(upload, content=b'replace').status_code == 413
        assert c.get('/api/projects/quota-edit/file?path=keep.txt').json()['content'] == 'keep this file'
        assert client.patch(url, json={'quota': 100 * 1048576}).status_code == 200
        assert c.get('/api/account').json()['quota'] == 100 * 1048576
        assert c.post(upload, content=b'replacement').status_code == 200
        assert client.patch(url, json={'quota': 0}).status_code == 200
        assert c.delete('/api/projects/quota-edit/file?where=data&path=keep.txt').status_code == 200


def test_chunked_upload_enforces_remaining_space_and_keeps_existing_file(client):
    c, user = make_user(client, 'chunked_quota_user')
    with closing(c):
        assert c.post('/api/projects', json={'name': 'chunked'}).status_code == 200
        url = '/api/projects/chunked/upload?name=original.txt'
        assert c.post(url, content=b'original').status_code == 200
        client.patch('/api/admin/users/' + user['id'], json={'quota': 80000})
        response = c.post(url, content=(b'x' * 8192 for _ in range(3)))
        assert response.status_code == 413
        assert c.get('/api/projects/chunked/file?path=original.txt').json()['content'] == 'original'
        assert c.get('/api/account').json()['token_limit'] == 10000


def test_single_file_over_50_mib_is_rejected_even_with_larger_quota(client):
    c, user = make_user(client, 'large_file_user')
    with closing(c):
        c.post('/api/projects', json={'name': 'large-file'})
        client.patch('/api/admin/users/' + user['id'], json={'quota': 200 * 1048576})
        response = c.post('/api/projects/large-file/upload?name=too-large.bin', content=b'x' * (50 * 1048576 + 1))
        assert response.status_code == 413
        assert '۵۰' in response.json()['error']
        assert c.get('/api/projects/large-file/tree').json()['data'] == []
