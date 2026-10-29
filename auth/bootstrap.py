"""python -m auth.bootstrap：备份后初始化首个管理员并幂等迁移演示数据。"""
import getpass
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row
from pydantic import ValidationError

from .repository import UserRepository
from .routes import Credentials
from .security import PASSWORDS


def bootstrap(conn, username, password):
    from session.repository import PostgresSessionRepository
    PostgresSessionRepository(conn).setup()
    repo = UserRepository(conn)
    repo.setup()
    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(7182026)')
        if conn.execute("SELECT 1 FROM app_migrations WHERE name='auth-bootstrap-v1'").fetchone():
            return False
        if conn.execute("SELECT 1 FROM app_users WHERE role='admin'").fetchone():
            raise ValueError('已有管理员，拒绝重新分配旧数据；请检查迁移状态')
        user = repo.create(username,PASSWORDS.hash(password),'admin')
        conn.execute("UPDATE sessions SET user_id=%s WHERE user_id IS NULL OR user_id IN ('','user_001')",(user['id'],))
        conn.execute("UPDATE memories SET user_id=%s WHERE user_id IN ('','user_001')",(user['id'],))
        rows = conn.execute('''SELECT m.images FROM messages m JOIN sessions s ON s.id=m.session_id
            WHERE s.user_id=%s''',(user['id'],)).fetchall()
        for row in rows:
            for image in row['images'] or []:
                if isinstance(image,str) and image.replace('\\','/').startswith(('data/uploads/','/uploads/')):
                    name = image.replace('\\','/').split('/')[-1]
                    if name and name not in ('.','..'):
                        conn.execute('INSERT INTO upload_owners(name,user_id) VALUES (%s,%s) ON CONFLICT DO NOTHING',(name,user['id']))
        conn.execute("INSERT INTO app_migrations(name) VALUES ('auth-bootstrap-v1')")
        return True


def main():
    load_dotenv(Path(__file__).resolve().parents[1]/'.env')
    print('请先备份 PostgreSQL 数据库。此命令会将旧演示数据迁给首个管理员。')
    if input('已完成备份？输入 BACKUP 确认：').strip() != 'BACKUP':
        return
    username = input('管理员用户名（3–32位字母、数字、下划线或连字符）：').strip()
    password = getpass.getpass('密码（8–128位）：')
    if password != getpass.getpass('再次输入密码：'):
        raise SystemExit('两次密码不一致')
    try:
        Credentials(username=username,password=password)
    except ValidationError:
        raise SystemExit('账号格式不正确：用户名为3–32位字母、数字、下划线或连字符，密码为8–128个字符。')
    with psycopg.connect(os.environ['LANGGRAPH_POSTGRES_URI'],autocommit=True,row_factory=dict_row) as conn:
        changed = bootstrap(conn,username,password)
    print('管理员创建及旧数据迁移完成。' if changed else '已初始化，未修改已有账号和数据。')


if __name__=='__main__':
    main()
