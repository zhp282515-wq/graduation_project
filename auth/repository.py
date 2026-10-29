import uuid


SCHEMA = """
CREATE TABLE IF NOT EXISTS app_users (
 id TEXT PRIMARY KEY, username TEXT NOT NULL, password_hash TEXT NOT NULL,
 role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user','admin')),
 enabled BOOLEAN NOT NULL DEFAULT true, must_change_password BOOLEAN NOT NULL DEFAULT false,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS app_users_username ON app_users (lower(username));
CREATE TABLE IF NOT EXISTS auth_sessions (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES app_users(id),
 expires_at TIMESTAMPTZ NOT NULL, revoked BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS auth_sessions_user ON auth_sessions(user_id);
CREATE TABLE IF NOT EXISTS auth_attempts (
 key TEXT PRIMARY KEY, failures INTEGER NOT NULL DEFAULT 0, started_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS upload_owners (
 name TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES app_users(id)
);
CREATE TABLE IF NOT EXISTS app_migrations (name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now());
"""
PUBLIC_FIELDS = 'id, username, role, enabled, must_change_password, created_at, updated_at'


class UserRepository:
    def __init__(self, conn):
        self.conn = conn

    def setup(self):
        self.conn.execute(SCHEMA)
        self.conn.commit()

    def by_name(self, username):
        return self.conn.execute('SELECT * FROM app_users WHERE lower(username)=lower(%s)', (username,)).fetchone()

    def by_id(self, user_id):
        return self.conn.execute('SELECT * FROM app_users WHERE id=%s', (user_id,)).fetchone()

    def create(self, username, password_hash, role='user', *, must_change=False):
        return self.conn.execute(f'''INSERT INTO app_users(id,username,password_hash,role,must_change_password)
            VALUES (%s,%s,%s,%s,%s) RETURNING {PUBLIC_FIELDS}''',
            (uuid.uuid4().hex, username, password_hash, role, must_change)).fetchone()

    def list_page(self, q='', page=1):
        # Literal substring matching; wildcard characters are not special here.
        args = (q,)
        total = self.conn.execute('SELECT count(*) AS n FROM app_users WHERE strpos(lower(username),lower(%s))>0', args).fetchone()['n']
        rows = self.conn.execute(f'''SELECT {PUBLIC_FIELDS} FROM app_users
            WHERE strpos(lower(username),lower(%s))>0 ORDER BY created_at,id LIMIT 20 OFFSET %s''',
            (q, (page - 1) * 20)).fetchall()
        return {'items': rows, 'total': total, 'page': page, 'page_size': 20}

    def new_session(self, user_id):
        sid = uuid.uuid4().hex
        self.conn.execute("INSERT INTO auth_sessions(id,user_id,expires_at) VALUES (%s,%s,now()+interval '8 hours')", (sid,user_id))
        return sid

    def session_user(self, sid, user_id):
        return self.conn.execute('''SELECT u.* FROM app_users u JOIN auth_sessions s ON s.user_id=u.id
            WHERE s.id=%s AND u.id=%s AND u.enabled AND NOT s.revoked AND s.expires_at>now()''', (sid,user_id)).fetchone()

    def revoke(self, user_id, sid=None):
        if sid:
            self.conn.execute('UPDATE auth_sessions SET revoked=true WHERE id=%s AND user_id=%s', (sid,user_id))
        else:
            self.conn.execute('UPDATE auth_sessions SET revoked=true WHERE user_id=%s', (user_id,))

    def change_password(self, user_id, hashed, *, must_change=False):
        self.conn.execute('UPDATE app_users SET password_hash=%s,must_change_password=%s,updated_at=now() WHERE id=%s', (hashed,must_change,user_id))
        self.revoke(user_id)

    def update(self, user_id, *, role=None, enabled=None):
        # A transaction-level advisory lock serializes concurrent last-admin changes.
        self.conn.execute('SELECT pg_advisory_xact_lock(7182026)')
        user = self.by_id(user_id)
        if user is None:
            return None
        next_role = role if role is not None else user['role']
        next_enabled = enabled if enabled is not None else user['enabled']
        if user['role']=='admin' and user['enabled'] and (next_role!='admin' or not next_enabled):
            count = self.conn.execute("SELECT count(*) AS n FROM app_users WHERE role='admin' AND enabled").fetchone()['n']
            if count <= 1:
                raise ValueError('至少保留一名启用的管理员')
        result = self.conn.execute(f'UPDATE app_users SET role=%s,enabled=%s,updated_at=now() WHERE id=%s RETURNING {PUBLIC_FIELDS}', (next_role,next_enabled,user_id)).fetchone()
        self.revoke(user_id)
        return result

    def delete(self, user_id):
        """注销账号：连同会话、记忆、笔记、上传归属一起删除。

        调用方需包事务；这里再拿一次 advisory lock，保证"最后一名管理员"的判断
        和 update() 一样不会被并发绕过。
        """
        self.conn.execute('SELECT pg_advisory_xact_lock(7182026)')
        user = self.by_id(user_id)
        if user is None:
            return None
        if user['role'] == 'admin' and user['enabled']:
            count = self.conn.execute("SELECT count(*) AS n FROM app_users WHERE role='admin' AND enabled").fetchone()['n']
            if count <= 1:
                raise ValueError('至少保留一名启用的管理员')
        # 先清子表：upload_owners 有外键，messages 靠 sessions 的 ON DELETE CASCADE 带走。
        self.conn.execute('DELETE FROM auth_sessions WHERE user_id=%s', (user_id,))
        self.conn.execute('DELETE FROM upload_owners WHERE user_id=%s', (user_id,))
        self.conn.execute('DELETE FROM sessions WHERE user_id=%s', (user_id,))
        self.conn.execute('DELETE FROM memories WHERE user_id=%s', (user_id,))
        self.conn.execute('DELETE FROM saved_notes WHERE user_id=%s', (user_id,))
        self.conn.execute('DELETE FROM app_users WHERE id=%s', (user_id,))
        return user

    def attempt(self, key):
        return self.conn.execute('''INSERT INTO auth_attempts(key,failures) VALUES (%s,1)
            ON CONFLICT(key) DO UPDATE SET
            failures=CASE WHEN auth_attempts.started_at<now()-interval '15 minutes' THEN 1 ELSE auth_attempts.failures+1 END,
            started_at=CASE WHEN auth_attempts.started_at<now()-interval '15 minutes' THEN now() ELSE auth_attempts.started_at END
            RETURNING failures''', (key,)).fetchone()['failures']

    def clear_attempt(self, key):
        self.conn.execute('DELETE FROM auth_attempts WHERE key=%s', (key,))

    def owns_upload(self, name, user_id):
        return self.conn.execute('SELECT 1 FROM upload_owners WHERE name=%s AND user_id=%s', (name,user_id)).fetchone() is not None


def public_user(user):
    return {key: user[key] for key in PUBLIC_FIELDS.replace(' ', '').split(',')}
