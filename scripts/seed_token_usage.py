"""Idempotent synthetic usage for explicitly local development databases only."""
import os
from datetime import datetime, timedelta
from random import Random
from zoneinfo import ZoneInfo

import psycopg
from psycopg.conninfo import conninfo_to_dict
from auth.repository import UserRepository
from session.usage import insert_event, setup


def require_development(dsn, env):
    settings = conninfo_to_dict(dsn)
    flags = [env.get(key, "").strip().lower() for key in
             ("APP_ENV","ENV","ENVIRONMENT","NODE_ENV","DEPLOY_ENV","STAGE")]
    if (flags[0] != "development" or any(x in ("prod","production","live","staging") for x in flags)
            or env.get("AUTH_COOKIE_SECURE", "").lower() == "true"
            or settings.get("host") not in ("localhost","127.0.0.1","::1")
            or not settings.get("dbname","").endswith("_dev")
            or settings.get("hostaddr", settings["host"]) not in ("localhost","127.0.0.1","::1")
            or "service" in settings or env.get("PGSERVICE") or env.get("PGHOSTADDR")):
        raise SystemExit("仅允许 APP_ENV=development 和本机 *_dev 数据库")


def seed(conn):
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    UserRepository(conn).setup()
    with conn.transaction():
        setup(conn)
        for n in range(9):
            uid = f"usage-preview-{n}"
            role = "admin" if n == 0 else "user"
            conn.execute("""INSERT INTO app_users(id,username,password_hash,role)
                VALUES (%s,%s,'!',%s) ON CONFLICT(id) DO NOTHING""", (uid,f"preview{n:03}",role))
            for offset in range(60):
                day = now.date() - timedelta(days=offset)
                rng = Random(f"{uid}:{day}")
                # Reserve two empty dates to exercise the matrix's missing-data state.
                if day.day in (9, 19) and offset:
                    continue
                start = now.replace(year=day.year, month=day.month, day=day.day, hour=0, minute=0, second=0, microsecond=0)
                span = int((now-start).total_seconds()) if offset == 0 else 86400
                for call in range(1 + rng.randrange(4)):
                    incoming, outgoing = rng.randint(100,9000), rng.randint(20,1800)
                    insert_event(conn, (f"preview:{uid}:{day}:{call}",uid,role,None,"preview",
                        incoming,outgoing,incoming+outgoing,"other",False,start+timedelta(seconds=rng.randrange(max(1,span)))))


if __name__ == "__main__":
    dsn = os.environ.get("LANGGRAPH_POSTGRES_URI", "")
    require_development(dsn, os.environ)
    with psycopg.connect(dsn) as connection:
        seed(connection)
    print("开发库 60 天预览数据已就绪")
