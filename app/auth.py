"""Local account/session store. No plaintext passwords or bearer tokens on disk."""
import contextlib
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time

QUOTA = 50 * 1024 * 1024
COOKIE = 'gisclaw_session'


def password_hash(password, salt=None):
    if not isinstance(password, str) or not password:
        raise ValueError('رمز عبور نمی‌تواند خالی باشد.')
    if len(password) > 256:
        raise ValueError('رمز عبور نباید بیش از ۲۵۶ نویسه باشد.')
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
    return salt + ':' + digest


def verify(password, encoded):
    try:
        return hmac.compare_digest(password_hash(password, encoded.split(':')[0]), encoded)
    except (ValueError, TypeError, AttributeError):
        return False


class Accounts:
    def __init__(self, workspace):
        self.workspace = os.path.abspath(workspace)
        root = os.path.join(self.workspace, '.gisclaw')
        os.makedirs(root, mode=0o700, exist_ok=True)
        self.path = os.path.join(root, 'accounts.sqlite3')
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL, role TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    quota INTEGER NOT NULL, preferences TEXT NOT NULL DEFAULT '{}');
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS attempts (
                    key TEXT PRIMARY KEY, count INTEGER NOT NULL, since REAL NOT NULL);
            ''')
        os.chmod(self.path, 0o600)
        self.dummy = password_hash(secrets.token_urlsafe(32))
        from app.token_budget import TokenBudget
        self.tokens = TokenBudget(self)

    @contextlib.contextmanager
    def db(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def create(self, username, password, role='user'):
        if not isinstance(username, str) or not username.strip():
            raise ValueError('نام کاربری نمی‌تواند خالی باشد.')
        if role not in ('admin', 'user'):
            raise ValueError('نقش نامعتبر است.')
        username = username.strip().lower()
        uid = secrets.token_hex(16)
        encoded = password_hash(password)
        try:
            with self.db() as db:
                db.execute('INSERT INTO users(id, username, password, role, quota) VALUES(?,?,?,?,?)',
                           (uid, username, encoded, role, QUOTA))
        except sqlite3.IntegrityError:
            raise ValueError('نام کاربری قبلاً ثبت شده است.')
        os.makedirs(self.root(self.get(uid)), mode=0o700, exist_ok=True)
        return self.get(uid)

    def get(self, uid):
        with self.db() as db:
            row = db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
            return dict(row) if row else None

    def root(self, user):
        # Existing projects remain available to administrators; never auto-migrate.
        return self.workspace if user['role'] == 'admin' else os.path.join(self.workspace, '.users', user['id'])

    def usage(self, user):
        total = 0
        def scan_error(error):
            # Never silently undercount an unreadable directory and allow writes.
            raise error

        for root, dirs, files in os.walk(self.root(user), followlinks=False, onerror=scan_error):
            dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))
                       and not (user['role'] == 'admin' and root == self.workspace and d in ('.gisclaw', '.users'))]
            for name in files:
                path = os.path.join(root, name)
                if not os.path.islink(path):
                    try:
                        total += os.path.getsize(path)
                    except FileNotFoundError:
                        pass
        return total

    def public(self, user):
        from app.isolated_analysis import available
        from app.features import text_chat_enabled
        isolated = available()
        legacy_run_enabled = os.environ.get('GISCLAW_DISABLE_LEGACY_RUN') != '1'
        return {k: user[k] for k in ('id', 'username', 'role', 'active', 'quota')} | {
            **self.tokens.status(user['id']),
            'used_bytes': self.usage(user), 'preferences': json.loads(user['preferences']),
            'chat_enabled': text_chat_enabled(), 'isolated_analysis_enabled': isolated,
            'legacy_run_enabled': legacy_run_enabled,
            'analysis_enabled': isolated or (user['role'] == 'admin' and legacy_run_enabled)}

    def login(self, username, password, address):
        key = hashlib.sha256(address.encode()).hexdigest()
        now = time.time()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM attempts WHERE since < ?', (now - 900,))
            attempt = db.execute('SELECT count FROM attempts WHERE key=?', (key,)).fetchone()
            if attempt and attempt['count'] >= 10:
                raise ValueError('تلاش‌های ورود بیش از حد است؛ ۱۵ دقیقه بعد دوباره امتحان کنید.')
            db.execute('INSERT INTO attempts VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1', (key, now))
            row = db.execute('SELECT * FROM users WHERE username=?', (str(username).strip().lower(),)).fetchone()
        valid = verify(password, row['password'] if row else self.dummy)
        if not row or not row['active'] or not valid:
            raise ValueError('نام کاربری یا رمز عبور نادرست است.')
        token = secrets.token_urlsafe(32)
        with self.db() as db:
            db.execute('DELETE FROM attempts WHERE key=?', (key,))
            db.execute('DELETE FROM sessions WHERE expires < ?', (now,))
            db.execute('INSERT INTO sessions VALUES(?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), row['id'], now + 12 * 3600))
        return token, dict(row)

    def session(self, token):
        if not token or len(token) > 256:
            return None
        with self.db() as db:
            row = db.execute('SELECT users.* FROM sessions JOIN users ON users.id=sessions.user_id WHERE token=? AND expires>? AND active=1',
                             (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
            return dict(row) if row else None

    def logout(self, token):
        with self.db() as db:
            db.execute('DELETE FROM sessions WHERE token=?', (hashlib.sha256(token.encode()).hexdigest(),))

    def update(self, uid, *, password=None, active=None, preferences=None, quota=None):
        if quota is not None and (type(quota) is not int or not 0 <= quota <= 2**53 - 1):
            raise ValueError('سهمیه باید تعداد صحیح و نامنفی بایت باشد.')
        encoded = password_hash(password) if password is not None else None
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            user = db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
            if not user:
                raise ValueError('کاربر یافت نشد.')
            if active is False and user['role'] == 'admin':
                count = db.execute("SELECT count(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]
                if count <= 1 and user['active']:
                    raise ValueError('آخرین ادمین فعال را نمی‌توان غیرفعال کرد.')
            if encoded:
                db.execute('UPDATE users SET password=? WHERE id=?', (encoded, uid))
            if active is not None:
                db.execute('UPDATE users SET active=? WHERE id=?', (int(active), uid))
            if preferences is not None:
                db.execute('UPDATE users SET preferences=? WHERE id=?', (json.dumps(preferences), uid))
            if quota is not None:
                db.execute('UPDATE users SET quota=? WHERE id=?', (quota, uid))
            if encoded or active is False:
                db.execute('DELETE FROM sessions WHERE user_id=?', (uid,))
        return self.get(uid)

    def users(self):
        with self.db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM users ORDER BY username')]


if __name__ == '__main__':
    import argparse
    import getpass
    parser = argparse.ArgumentParser(description='Create a GISclaw administrator locally')
    parser.add_argument('command', choices=['create-admin'])
    parser.add_argument('--workspace', default=os.environ.get('GISCLAW_WORKSPACE', os.path.join(os.path.dirname(os.path.dirname(__file__)), 'projects')))
    args = parser.parse_args()
    username = input('Admin username: ')
    password = getpass.getpass('Password: ')
    if password != getpass.getpass('Repeat password: '):
        raise SystemExit('Passwords do not match')
    try:
        Accounts(args.workspace).create(username, password, 'admin')
    except ValueError as exc:
        raise SystemExit(str(exc))
    print('Administrator created.')
