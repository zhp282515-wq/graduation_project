from datetime import datetime, time, timedelta
from pathlib import Path
from threading import Lock
from time import monotonic
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")


def setup_activity(conn):
    path = Path(__file__).resolve().parents[1] / "session" / "activity_schema.sql"
    conn.execute(path.read_text(encoding="utf8"))


def activity_days(rows, started, now, role):
    first = now.astimezone(SHANGHAI).date() - timedelta(days=29)
    launch = started.astimezone(SHANGHAI).date()
    days = {}
    for offset in range(30):
        day = first + timedelta(days=offset)
        days[day] = {"date": day.isoformat(), "messages": 0 if day >= launch else None,
                     "tools": {} if day >= launch else None}
    for row in rows:
        if role != "all" and row["role"] != role:
            continue
        point = days[row["day"]]
        name = row["tool_name"]
        if name is None:
            point["messages"] += row["calls"]
        else:
            point["tools"][name] = point["tools"].get(name, 0) + row["calls"]
    return {"started_at": started.isoformat(), "updated_at": now.isoformat(), "items": list(days.values())}


class ActivityReports:
    def __init__(self, pool):
        self.pool = pool
        self.lock = Lock()
        self.cache = {}
        self.date = None
        self.expires = 0

    def get(self, role):
        with self.lock:
            now = datetime.now(SHANGHAI)
            if self.date != now.date() or monotonic() >= self.expires:
                first = datetime.combine(now.date() - timedelta(days=29), time.min, SHANGHAI)
                with self.pool.connection() as conn:
                    started = conn.execute("SELECT started_at FROM usage_activity_install").fetchone()["started_at"]
                    rows = conn.execute("""
                        SELECT (occurred_at AT TIME ZONE 'Asia/Shanghai')::date AS day,
                               role, tool_name, count(*) AS calls
                        FROM usage_activity_events WHERE occurred_at BETWEEN %s AND %s
                        GROUP BY 1,2,3
                    """, (max(first, started), now)).fetchall()
                self.cache = {key: activity_days(rows, started, now, key) for key in ("all","user","admin")}
                self.date, self.expires = now.date(), monotonic() + 45
            return self.cache[role]
