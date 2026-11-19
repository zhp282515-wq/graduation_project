"""Recover only a verifiable final model call from pre-metering messages."""
import os
import psycopg
from psycopg.rows import dict_row
from session.usage import insert_event


def backfill(conn):
    inserted = 0
    # No identity, role history, model name or per-hop split is invented.
    # context_revision > 0 can mean a reply was rewritten at a different time.
    with conn.transaction(), conn.cursor(name="usage_history", row_factory=dict_row) as rows:
        rows.execute("""
            SELECT m.id,m.created_at,m.session_id,m.token_usage,u.id AS user_id,u.role
            FROM messages m JOIN sessions s ON s.id=m.session_id
            JOIN app_users u ON u.id=s.user_id CROSS JOIN token_usage_install i
            WHERE m.role='assistant' AND m.token_usage IS NOT NULL AND s.context_revision=0
            AND m.created_at<i.started_at AND u.updated_at<=m.created_at
        """)
        excluded = set(os.getenv("TOKEN_USAGE_EXCLUDED_USER_IDS", "").replace(" ", "").split(","))
        for row in rows:
            usage = row["token_usage"]
            if not isinstance(usage, dict) or row["user_id"] in excluded:
                continue
            left = usage.get("input_tokens", usage.get("prompt_tokens"))
            right = usage.get("output_tokens", usage.get("completion_tokens"))
            total = usage.get("total_tokens")
            if not all(type(n) is int and n >= 0 for n in (left, right, total)):
                continue
            if not total or left + right != total:
                continue
            inserted += insert_event(conn, (f"legacy:{row['id']}", row["user_id"], row["role"],
                row["session_id"], "历史未记录", left, right, total, "chat", False, row["created_at"]))
    return inserted


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    with psycopg.connect(os.environ["LANGGRAPH_POSTGRES_URI"]) as connection:
        print(f"新增历史调用 {backfill(connection)} 条")
