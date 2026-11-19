"""Backfill verifiable timestamps and ownership from retained conversation metadata."""
import os

import psycopg
from psycopg.rows import dict_row


def backfill(conn):
    with conn.transaction():
        live = conn.execute("SELECT started_at FROM operations_coverage WHERE metric='live'").fetchone()["started_at"]
        conn.execute("""
            INSERT INTO operations_active_days(day,user_id,role)
            SELECT DISTINCT (m.created_at AT TIME ZONE 'Asia/Shanghai')::date,s.user_id,'unknown'
            FROM messages m JOIN sessions s ON m.session_id=s.id
            WHERE m.role='user' AND s.user_id<>'' AND m.created_at<%s ON CONFLICT DO NOTHING
        """, (live,))
        conn.execute("""
            INSERT INTO operations_first_activity
            SELECT s.user_id,min(m.created_at),'unknown' FROM messages m JOIN sessions s ON m.session_id=s.id
            WHERE m.role='user' AND s.user_id<>'' AND m.created_at<%s GROUP BY s.user_id
            ON CONFLICT (user_id) DO UPDATE SET occurred_at=excluded.occurred_at,role=excluded.role
            WHERE operations_first_activity.occurred_at > excluded.occurred_at
        """, (live,))
        # Backfill the bounded query window without repopulating archived event rows.
        conn.execute("""
            INSERT INTO operations_questions(id,occurred_at,user_id,role,session_id)
            SELECT m.id,m.created_at,s.user_id,'unknown',s.id FROM messages m JOIN sessions s ON m.session_id=s.id
            WHERE m.role='user' AND s.user_id<>'' AND m.created_at<%s AND m.created_at>=now()-INTERVAL '90 days'
            ON CONFLICT DO NOTHING
        """, (live,))
        conn.execute("""
            INSERT INTO operations_answers(id,occurred_at,role,user_id,message_id,revision,route,success,
              searches,hits,empty_searches,cited,used_web,documents)
            SELECT 'history:'||m.id,m.created_at,'unknown',s.user_id,m.id,0,'unknown',true,
              0,0,0,false,false,ARRAY[]::text[] FROM messages m JOIN sessions s ON m.session_id=s.id
            LEFT JOIN answer_revisions r ON m.id=r.message_id
            WHERE m.role='assistant' AND r.message_id IS NULL AND s.user_id<>'' AND m.created_at<%s
              AND m.created_at>=now()-INTERVAL '90 days'
            ON CONFLICT DO NOTHING
        """, (live,))
        conn.execute("""
            INSERT INTO operations_coverage(metric,started_at)
            SELECT 'history',min(occurred_at) FROM operations_questions WHERE role='unknown'
            HAVING count(*)>0 ON CONFLICT(metric) DO NOTHING
        """)
        conn.execute("""INSERT INTO operations_rollup_pending(day)
            SELECT DISTINCT (occurred_at AT TIME ZONE 'Asia/Shanghai')::date
            FROM operations_questions WHERE role='unknown' ON CONFLICT DO NOTHING""")


if __name__ == "__main__":
    with psycopg.connect(os.environ["LANGGRAPH_POSTGRES_URI"], row_factory=dict_row) as connection:
        backfill(connection)
    print("历史运营数据回填完成")
