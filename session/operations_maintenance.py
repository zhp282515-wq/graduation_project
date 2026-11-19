"""Evaluate alerts and preserve a rollup before expiring old operational events."""
from datetime import timedelta

from psycopg.types.json import Jsonb

from config import operations as config
from session.operations_reports import high_frequency, quality_metrics, ratio


def evaluate_alerts(conn, now, live):
    alerts = {}
    minute = now.replace(second=0, microsecond=0)
    rates = conn.execute("""
        SELECT count(*) count,count(*) FILTER (WHERE NOT success) failed
        FROM operations_answers WHERE elapsed_ms IS NOT NULL AND occurred_at >= %s AND occurred_at < %s
        GROUP BY date_trunc('minute',occurred_at)
    """, (minute-timedelta(minutes=config.ERROR_MINUTES),minute)).fetchall()
    if len(rates) == config.ERROR_MINUTES and all(
        ratio(r["failed"],r["count"]) > config.ERROR_PERCENT for r in rates
    ):
        alerts["errors"] = ratio(sum(r["failed"] for r in rates), sum(r["count"] for r in rates))
    hour = now - timedelta(hours=1)
    latency = conn.execute("""
        SELECT percentile_cont(.95) WITHIN GROUP (ORDER BY first_ms) AS p95
        FROM operations_answers WHERE occurred_at >= %s AND occurred_at < %s
    """, (hour, now)).fetchone()["p95"]
    if latency is not None and latency > config.FIRST_P95_MS:
        alerts["latency"] = latency
    tools = conn.execute("""
        SELECT name,count(*) count,count(error) failed FROM operations_tools WHERE occurred_at >= %s AND occurred_at < %s
        GROUP BY name HAVING count(*) >= %s
    """, (hour,now,config.TOOL_SAMPLE)).fetchall()
    for row in tools:
        rate = ratio(row["failed"],row["count"])
        if rate > config.TOOL_FAILURE_PERCENT:
            alerts["tool:" + row["name"]] = rate
    midpoint, begin = now-timedelta(days=7), now-timedelta(days=14)
    if live <= begin:
        previous = quality_metrics(conn, (begin,midpoint,["user","admin"]))["missing"]
        current = quality_metrics(conn, (midpoint,now,["user","admin"]))["missing"]
        if previous is not None and current is not None and current - previous > config.MISSING_INCREASE_PP:
            alerts["missing"] = round(current-previous,2)
    count = conn.execute("""
        SELECT count(*) n FROM kb_documents d WHERE d.status='failed' AND EXISTS (
          SELECT 1 FROM operations_events e WHERE e.kind='ingest_failed' AND e.object_id=d.file_md5
        )
    """).fetchone()["n"]
    if count:
        alerts["ingest"] = count
    peaks = high_frequency(conn, (hour,now,["user","admin"]))
    if peaks:
        alerts["frequency"] = peaks[0]["total"]
    return alerts


def maintain(conn, now):
    if not conn.execute("SELECT pg_try_advisory_xact_lock(25111930) locked").fetchone()["locked"]:
        return
    conn.execute("""
        WITH dirty AS (DELETE FROM operations_rollup_pending WHERE day < %s RETURNING day)
        INSERT INTO operations_daily_traffic(day,scope,active,sessions)
        SELECT day,scope,count(DISTINCT user_id),count(DISTINCT session_id)
        FROM dirty CROSS JOIN (VALUES ('all'),('user')) AS scopes(scope)
        LEFT JOIN operations_questions q ON
          q.occurred_at >= (day::timestamp AT TIME ZONE 'Asia/Shanghai') AND
          q.occurred_at < ((day+1)::timestamp AT TIME ZONE 'Asia/Shanghai') AND
          (scope='all' OR q.role='user')
        GROUP BY day,scope
        ON CONFLICT(day,scope) DO UPDATE SET active=excluded.active,sessions=excluded.sessions
    """, (now.date(),))
    live = conn.execute("SELECT started_at FROM operations_coverage WHERE metric='live'").fetchone()["started_at"]
    active = evaluate_alerts(conn, now, live)
    conn.execute("UPDATE operations_alerts SET recovered_at=%s WHERE recovered_at IS NULL AND NOT(rule=ANY(%s))",
                 (now,list(active)))
    for key, value in active.items():
        conn.execute("""INSERT INTO operations_alerts(rule,triggered_at,value) VALUES (%s,%s,%s)
            ON CONFLICT (rule) WHERE recovered_at IS NULL DO UPDATE SET value=excluded.value""", (key,now,value))
    cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)-timedelta(days=config.RETENTION_DAYS)
    # Snapshot only completed days before removing event-level facts.
    rows = conn.execute("""
        SELECT day, jsonb_object_agg(metric,dimensions) totals FROM (
          SELECT day,metric,jsonb_object_agg(dimension,n) dimensions FROM (
            SELECT (occurred_at AT TIME ZONE 'Asia/Shanghai')::date AS day,'questions' metric,role dimension,count(*) n
            FROM operations_questions WHERE occurred_at<%s GROUP BY 1,2,3
            UNION ALL
            SELECT (occurred_at AT TIME ZONE 'Asia/Shanghai')::date,'answers',role||':'||route||':'||success,count(*)
            FROM operations_answers WHERE occurred_at<%s GROUP BY 1,2,3
            UNION ALL
            SELECT (occurred_at AT TIME ZONE 'Asia/Shanghai')::date,'tools',role||':'||name||':'||coalesce(error,'ok'),count(*)
            FROM operations_tools WHERE occurred_at<%s GROUP BY 1,2,3
            UNION ALL
            SELECT (occurred_at AT TIME ZONE 'Asia/Shanghai')::date,'events',kind,count(*)
            FROM operations_events WHERE occurred_at<%s GROUP BY 1,2,3
          ) measures GROUP BY day,metric
        ) groups GROUP BY day
    """, (cutoff,)*4).fetchall()
    for row in rows:
        conn.execute("""INSERT INTO operations_daily VALUES (%s,%s)
            ON CONFLICT(day) DO NOTHING""", (row["day"],Jsonb(row["totals"])))
    for table in ("operations_questions", "operations_answers", "operations_tools", "operations_events"):
        conn.execute(f"DELETE FROM {table} WHERE occurred_at<%s", (cutoff,))
