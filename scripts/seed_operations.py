"""Create a reproducible 60-day scenario in a local development database."""
import os
from datetime import datetime, timedelta
from hashlib import md5
from random import Random

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from session.operations import ANSWER, QUESTION, TOOL, register_activity
from session.operations_reports import SHANGHAI


def require_development(dsn, env):
    cfg = conninfo_to_dict(dsn)
    local = {"localhost", "127.0.0.1", "::1"}
    production = {"prod", "production", "live", "stage", "staging"}
    stages = ("APP_ENV", "ENV", "ENVIRONMENT", "NODE_ENV", "DEPLOY_ENV", "STAGE")
    if (env.get("APP_ENV") != "development" or any(env.get(key, "").strip().lower() in production for key in stages)
            or env.get("AUTH_COOKIE_SECURE", "").strip().lower() in {"1", "true", "yes", "on"}
            or cfg.get("host") not in local or not cfg.get("dbname", "").endswith("_dev")
            or cfg.get("hostaddr", cfg.get("host")) not in local
            or "service" in cfg or env.get("PGSERVICE") or env.get("PGHOSTADDR")):
        raise SystemExit("只允许 APP_ENV=development 且使用本机 *_dev 数据库")


def seed(conn, now=None):
    now = now or datetime.now(SHANGHAI)
    start = now.replace(hour=0,minute=0,second=0,microsecond=0) - timedelta(days=59)
    docs = [md5(f"operations-preview-{n}".encode()).hexdigest() for n in range(3)]
    rng = Random(f"operations-preview:{now.date()}")
    with conn.transaction():
        if not conn.execute("INSERT INTO operations_coverage(metric) VALUES ('preview') ON CONFLICT DO NOTHING RETURNING metric").fetchone():
            return
        conn.execute("UPDATE operations_coverage SET started_at=LEAST(started_at,%s) WHERE metric='live'", (start,))
        conn.execute("UPDATE feedback_started SET started_at=LEAST(started_at,%s)", (start,))
        for idx, doc in enumerate(docs):
            conn.execute("""
                INSERT INTO kb_documents(file_md5,file_name,file_type,status,updated_at,visibility)
                VALUES (%s,%s,'pdf','ready',%s,'public') ON CONFLICT DO NOTHING
            """, (doc,["选课指南.pdf","图书馆开放时间.pdf","校历示例.pdf"][idx],now-timedelta(days=200*idx)))
        for n in range(60):
            day = start+timedelta(days=n)
            for i in range(rng.randrange(4, 18)):
                moment = min(now-timedelta(seconds=1),day+timedelta(hours=8,minutes=rng.randrange(600)))
                account = 100+n if i == 0 else rng.randrange(min(24,2+n))
                uid = md5(f"operations-preview-account-{account}".encode()).hexdigest()
                role = "admin" if account % 6 == 0 else "user"
                answer_id = -(n*40+i*2+2)
                keyword = rng.choice(["选课","学生证","图书馆","学费","食堂","天气"])
                label = {"选课":"教务","学生证":"学工","图书馆":"学习","学费":"财务"}.get(keyword,"生活")
                conn.execute(QUESTION, (answer_id-1,moment,uid,role,f"preview:{account}:{n//3}",label,[keyword],i==1))
                register_activity(conn,moment,uid,role)
                route = rng.choice(["direct","knowledge_search","academic_calendar","websearch","get_weather"])
                retrieved = route in {"knowledge_search","websearch"}
                failed = i % 11 == 10
                empty = route == "knowledge_search" and i % 3 == 0
                cited = int(retrieved and not empty and not failed)
                searches = 3 if retrieved and i%4 == 0 else int(retrieved)
                conn.execute(ANSWER, (f"preview:{answer_id}",moment,role,uid,answer_id if not failed else None,
                    0,route,not failed,"answer_failed" if failed else None,rng.randrange(180,12500),
                    rng.randrange(13000,21000),searches,cited,int(empty),bool(cited),
                    route=="websearch",docs[:1] if cited and route == "knowledge_search" else []))
                if route != "direct":
                    for call in range(max(1,searches)):
                        conn.execute(TOOL, (f"preview:{answer_id}:{call}",moment,role,uid,route,
                            "timeout" if failed else None, rng.randrange(40,3500),
                            keyword if retrieved else None,None if failed or not retrieved else 0 if empty else 2))
                if not failed and i % 3 != 1:
                    down = i % 4 == 0
                    conn.execute("""INSERT INTO answer_ratings(user_id,message_id,revision,role,vote,reason,voted_at)
                        VALUES (%s,%s,0,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                        (uid,answer_id,role,"dislike" if down else "like","unresolved" if down else None,moment))
            if n % 9 == 0:
                conn.execute("""INSERT INTO operations_events(occurred_at,kind,object_id,actor_id)
                    VALUES (%s,'audit:sync_knowledge','知识库登记表',%s)""", (day,uid))
        for kind in ("sensitive_block", "suspected_injection", "crisis"):
            conn.execute("INSERT INTO operations_coverage VALUES (%s,%s)", (kind,start))
            conn.execute("INSERT INTO operations_events(occurred_at,kind) VALUES (%s,%s)", (now-timedelta(hours=1),kind))
        conn.execute("""INSERT INTO operations_alerts(rule,triggered_at,recovered_at,value)
            VALUES ('latency',%s,%s,8200)""", (now-timedelta(days=1),now-timedelta(hours=23)))


if __name__ == "__main__":
    uri = os.environ.get("LANGGRAPH_POSTGRES_URI", "")
    require_development(uri, os.environ)
    with psycopg.connect(uri, row_factory=dict_row) as connection:
        seed(connection)
    print("运营看板演示数据已就绪")
