"""SQL read models for the operations dashboard."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from config.operations import STALE_DAYS, HIGH_FREQUENCY

SHANGHAI = ZoneInfo("Asia/Shanghai")
ROLES = {"all": ["user", "admin", "unknown"], "user": ["user"]}
QUESTION_WHERE = "occurred_at >= %s AND occurred_at < %s AND role=ANY(%s)"
ANSWER_WHERE = "a.occurred_at >= %s AND a.occurred_at < %s AND a.role=ANY(%s)"
MISS = "a.success AND a.empty_searches > 0 AND a.hits = 0 AND NOT a.cited"


def windows(now, days):
    now = now.astimezone(SHANGHAI)
    first = datetime.combine(now.date() - timedelta(days=days - 1), time.min, SHANGHAI)
    return (first, now), (first - timedelta(days=days), now - timedelta(days=1) if days == 1 else first)


def ratio(num, den):
    return round(100 * num / den, 2) if den else None


def change(current, previous):
    return round(100 * (current - previous) / previous, 1) if current is not None and previous else None


def mask(identifier):
    return identifier[:4] + "••••" + identifier[-4:] if identifier and len(identifier) >= 10 else "—"


def with_shares(rows):
    total = sum(row["count"] for row in rows)
    if not total:
        return rows
    values = [divmod(row["count"] * 10_000, total) for row in rows]
    remaining = 10_000 - sum(value for value, _ in values)
    highest = set(sorted(range(len(values)), key=lambda i: -values[i][1])[:remaining])
    return [dict(row, share=(values[i][0] + (i in highest)) / 100) for i, row in enumerate(rows)]


def quality_metrics(conn, args):
    row = conn.execute(f"""
        SELECT count(*) FILTER (WHERE success) AS answers,
            count(*) FILTER (WHERE NOT success) AS failed, count(*) FILTER (WHERE elapsed_ms IS NOT NULL) AS runs,
            count(*) FILTER (WHERE elapsed_ms IS NOT NULL AND NOT success) AS run_errors,
            count(*) FILTER (WHERE vote='like') AS likes, count(*) FILTER (WHERE vote='dislike') AS dislikes,
            count(*) FILTER (WHERE a.searches>0 AND a.success) AS retrieved,
            count(*) FILTER (WHERE {MISS}) AS missed,
            count(*) FILTER (WHERE a.hits>0 AND a.success) AS with_hits,
            count(*) FILTER (WHERE a.hits>0 AND a.success AND a.cited) AS with_source,
            count(*) FILTER (WHERE a.searches>=3 AND a.success) AS reached,
            count(*) FILTER (WHERE a.searches>0 AND a.success AND a.used_web) AS web_count,
            avg(a.searches) FILTER (WHERE a.searches>0 AND a.success) AS avg_searches
        FROM operations_answers a LEFT JOIN answer_ratings r
          ON a.success AND (r.user_id,r.message_id,r.revision)=(a.user_id,a.message_id,a.revision)
        WHERE {ANSWER_WHERE}
    """, args).fetchone()
    votes = row["likes"] + row["dislikes"]
    return dict(row, votes=votes, approval=ratio(row["likes"], votes), feedback=ratio(votes, row["answers"]),
                missing=ratio(row["missed"], row["retrieved"]), errors=ratio(row["run_errors"], row["runs"]),
                sources=ratio(row["with_source"], row["with_hits"]), capped=ratio(row["reached"], row["retrieved"]))


def overview_metrics(conn, args, questions_covered, answers_covered, rating_start):
    result = {name: None for name in ("active", "sessions", "new", "approval", "missing", "errors")}
    if questions_covered:
        result.update(conn.execute(f"""
            SELECT count(DISTINCT user_id) AS active, count(DISTINCT session_id) AS sessions
            FROM operations_questions WHERE {QUESTION_WHERE}
        """, args).fetchone())
        result["new"] = conn.execute(f"""
            SELECT count(*) AS n FROM operations_first_activity WHERE {QUESTION_WHERE}
        """, args).fetchone()["n"]
    if args[1] > rating_start or answers_covered:
        quality = quality_metrics(conn, args)
        result["approval"] = quality["approval"]
        if answers_covered:
            result.update(missing=quality["missing"], errors=quality["errors"])
    return result


def daily_overview(conn, current, previous, roles, coverage, live, rating_start):
    points = []
    for i in range((current[1].date()-current[0].date()).days + 1):
        day = current[0] + timedelta(days=i)
        prev = previous[0] + timedelta(days=i)
        end = min(day + timedelta(days=1), current[1])
        prev_end = min(prev + timedelta(days=1), previous[1])
        points.append((day, end, prev, prev_end))
    # One query for the entire chart. Use real event bounds, including yesterday's partial day.
    rows = conn.execute("""
        WITH bounds AS (
          SELECT * FROM unnest(%s::timestamptz[], %s::timestamptz[], %s::timestamptz[], %s::timestamptz[])
              AS b(day, ending, prev, prev_end)
        )
        SELECT b.day, b.ending, b.prev_end, coalesce(q_cache.active,q.active) active,
            coalesce(q_cache.sessions,q.sessions) sessions, n.new, a.approval, a.missing, a.errors,
            coalesce(p_cache.active,p.active) AS previous
        FROM bounds b
        LEFT JOIN operations_daily_traffic q_cache ON q_cache.day=(b.day AT TIME ZONE 'Asia/Shanghai')::date
          AND b.ending=b.day+INTERVAL '24 hours' AND q_cache.scope=%s
          AND NOT EXISTS (SELECT 1 FROM operations_rollup_pending WHERE day=q_cache.day)
        LEFT JOIN operations_daily_traffic p_cache ON p_cache.day=(b.prev AT TIME ZONE 'Asia/Shanghai')::date
          AND b.prev_end=b.prev+INTERVAL '24 hours' AND p_cache.scope=%s
          AND NOT EXISTS (SELECT 1 FROM operations_rollup_pending WHERE day=p_cache.day)
        CROSS JOIN LATERAL (
          SELECT count(DISTINCT user_id) active, count(DISTINCT session_id) sessions
          FROM operations_questions WHERE q_cache.day IS NULL AND occurred_at>=b.day AND occurred_at<b.ending AND role=ANY(%s)
        ) q
        CROSS JOIN LATERAL (
          SELECT count(DISTINCT user_id) active FROM operations_questions
          WHERE p_cache.day IS NULL AND occurred_at>=b.prev AND occurred_at<b.prev_end AND role=ANY(%s)
        ) p
        CROSS JOIN LATERAL (
          SELECT count(*) AS new FROM operations_first_activity
          WHERE occurred_at>=b.day AND occurred_at<b.ending AND role=ANY(%s)
        ) n
        CROSS JOIN LATERAL (
          SELECT round(100.0*count(*) FILTER (WHERE r.vote='like')/nullif(count(r.vote),0),2) AS approval,
            round(100.0*count(*) FILTER (WHERE a.success AND a.empty_searches>0 AND a.hits=0 AND NOT a.cited)/
              nullif(count(*) FILTER (WHERE a.success AND a.searches>0),0),2) AS missing,
            round(100.0*count(*) FILTER (WHERE a.elapsed_ms IS NOT NULL AND NOT a.success)/
              nullif(count(a.elapsed_ms),0),2) AS errors
          FROM operations_answers a LEFT JOIN answer_ratings r
            ON a.success AND (r.user_id,r.message_id,r.revision)=(a.user_id,a.message_id,a.revision)
          WHERE a.occurred_at>=b.day AND a.occurred_at<b.ending AND a.role=ANY(%s)
        ) a ORDER BY b.day
    """, (*[list(column) for column in zip(*points)], "user" if roles==["user"] else "all",
           "user" if roles==["user"] else "all", roles, roles, roles, roles)).fetchall()
    return [dict(date=r["day"].astimezone(SHANGHAI).date(),
                 **{key: r[key] if r["ending"] > coverage else None for key in ("active", "sessions", "new")},
                 previous=r["previous"] if r["prev_end"] > coverage else None,
                 approval=r["approval"] if r["ending"] > rating_start else None,
                 missing=r["missing"] if r["ending"] > live else None,
                 errors=r["errors"] if r["ending"] > live else None) for r in rows]


def gaps(conn, args, limit):
    return conn.execute(f"""
        SELECT keyword,count(*) AS count,count(DISTINCT user_id) AS people
        FROM operations_tools t LEFT JOIN operations_gap_marks m USING(keyword)
        WHERE {QUESTION_WHERE} AND t.name='knowledge_search' AND t.error IS NULL
          AND results=0 AND keyword IS NOT NULL AND (m.marked_at IS NULL OR t.occurred_at > m.marked_at)
        GROUP BY keyword ORDER BY count DESC,keyword LIMIT %s
    """, (*args, limit)).fetchall()


def quality_report(conn, args, previous, now, live):
    def topics(bounds):
        return conn.execute(f"""SELECT topic,count(*) AS count FROM operations_questions
            WHERE {QUESTION_WHERE} AND topic IS NOT NULL GROUP BY topic ORDER BY count DESC,topic""", bounds).fetchall()

    prior_topics = {r["topic"]: r["count"] for r in topics(previous)}
    current_topics = topics(args)
    for row in current_topics:
        row["previous"] = prior_topics.get(row["topic"], 0) if previous[0] >= live else None
    distributions = conn.execute(f"""
        SELECT route,count(*) count FROM operations_answers a
        WHERE {ANSWER_WHERE} AND success AND elapsed_ms IS NOT NULL GROUP BY route ORDER BY count DESC,route
    """, args).fetchall()
    keyword_rows = conn.execute(f"""
        SELECT keyword,count(*) count FROM operations_questions CROSS JOIN LATERAL unnest(keywords) AS keyword
        WHERE {QUESTION_WHERE} GROUP BY keyword ORDER BY count DESC,keyword LIMIT 10
    """, args).fetchall()
    heatmap = conn.execute(f"""
        SELECT extract(isodow FROM occurred_at AT TIME ZONE 'Asia/Shanghai')::int AS weekday,
          extract(hour FROM occurred_at AT TIME ZONE 'Asia/Shanghai')::int AS hour, count(*) count
        FROM operations_questions WHERE {QUESTION_WHERE} GROUP BY 1,2
    """, args).fetchall()
    repeated = conn.execute(f"""
        SELECT count(*) FILTER (WHERE repeated) AS n, count(repeated) AS total
        FROM operations_questions WHERE {QUESTION_WHERE}
    """, args).fetchone()
    reasons = conn.execute(f"""
        SELECT r.reason,count(*) count FROM operations_answers a JOIN answer_ratings r
          ON a.success AND (r.user_id,r.message_id,r.revision)=(a.user_id,a.message_id,a.revision)
        WHERE {ANSWER_WHERE} AND r.vote='dislike' AND r.reason IS NOT NULL GROUP BY r.reason
    """, args).fetchall()
    retention = {}
    for period in (1, 7):
        row = conn.execute(f"""
            SELECT count(*) AS eligible,count(*) FILTER (WHERE EXISTS (
              SELECT 1 FROM operations_active_days d WHERE d.user_id=f.user_id AND
                d.day=(f.occurred_at AT TIME ZONE 'Asia/Shanghai')::date+%s AND d.role=ANY(%s)
            )) AS retained FROM operations_first_activity f WHERE {QUESTION_WHERE}
              AND (occurred_at AT TIME ZONE 'Asia/Shanghai')::date+%s < %s
        """, (period,args[2], *args, period, now.date())).fetchone()
        retention[period] = dict(row, rate=ratio(row["retained"], row["eligible"]))
    trend = conn.execute(f"""
        SELECT (a.occurred_at AT TIME ZONE 'Asia/Shanghai')::date AS date,
          count(*) FILTER (WHERE {MISS}) AS missed,
          count(*) FILTER (WHERE a.success AND a.searches>0) AS retrieved
        FROM operations_answers a WHERE {ANSWER_WHERE} AND elapsed_ms IS NOT NULL GROUP BY 1 ORDER BY 1
    """, args).fetchall()
    return dict(metrics=quality_metrics(conn, args), topics=with_shares(current_topics), routes=with_shares(distributions), keywords=keyword_rows,
                heatmap=heatmap, repeat=ratio(repeated["n"], repeated["total"]), retention=retention, reasons=reasons,
                trend=[dict(row, missing=ratio(row["missed"], row["retrieved"])) for row in trend])


def knowledge_report(conn, args, now, live):
    documents = conn.execute("""
        SELECT file_type,count(*) AS count,max(updated_at) AS last_update
        FROM kb_documents WHERE status='ready' GROUP BY file_type ORDER BY count DESC,file_type
    """).fetchall()
    deadline = now - timedelta(days=STALE_DAYS)
    stale = conn.execute("""SELECT file_md5,file_name,updated_at,count(*) OVER () AS total
        FROM kb_documents WHERE status='ready' AND updated_at < %s ORDER BY updated_at,file_md5 LIMIT 50""",
        (deadline,)).fetchall()
    cited = conn.execute(f"""
        SELECT d.file_md5,d.file_name,count(*) AS count
        FROM operations_answers a CROSS JOIN LATERAL unnest(a.documents) AS doc_id
        JOIN kb_documents d ON d.file_md5=doc_id WHERE {ANSWER_WHERE} AND a.success
        GROUP BY d.file_md5,d.file_name ORDER BY count DESC,d.file_md5 LIMIT 10
    """, args).fetchall()
    since = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=29)
    unused = None if since < live else conn.execute("""
        WITH cited AS (
          SELECT DISTINCT unnest(documents) AS id FROM operations_answers
          WHERE occurred_at >= %s AND occurred_at < %s AND role=ANY(%s)
        )
        SELECT d.file_md5,d.file_name,d.updated_at,count(*) OVER () AS total FROM kb_documents d
        LEFT JOIN cited ON cited.id=d.file_md5 WHERE d.status='ready' AND cited.id IS NULL
        ORDER BY d.updated_at,d.file_md5 LIMIT 50
    """, (since,now,args[2])).fetchall()
    metrics = quality_metrics(conn, args)
    return dict(documents=documents, stale=stale, cited=cited, unused=unused, gaps=gaps(conn,args,30),
                web_share=ratio(metrics["web_count"], metrics["retrieved"]))


def system_report(conn, args):
    times = conn.execute(f"""
        SELECT (a.occurred_at AT TIME ZONE 'Asia/Shanghai')::date AS day, count(*) count,
            count(*) FILTER (WHERE NOT success) failed,
            percentile_cont(.5) WITHIN GROUP (ORDER BY first_ms) first_p50,
            percentile_cont(.95) WITHIN GROUP (ORDER BY first_ms) first_p95,
            percentile_cont(.5) WITHIN GROUP (ORDER BY elapsed_ms) total_p50,
            percentile_cont(.95) WITHIN GROUP (ORDER BY elapsed_ms) total_p95
        FROM operations_answers a WHERE {ANSWER_WHERE} AND elapsed_ms IS NOT NULL GROUP BY 1 ORDER BY 1
    """, args).fetchall()
    tools = conn.execute(f"""
        SELECT name,count(*) count,count(*) FILTER (WHERE error IS NULL) AS succeeded,
          round(avg(elapsed_ms),1) average,percentile_cont(.95) WITHIN GROUP (ORDER BY elapsed_ms) p95
        FROM operations_tools WHERE {QUESTION_WHERE} GROUP BY name ORDER BY count DESC,name
    """, args).fetchall()
    reasons = conn.execute(f"""SELECT name,error,count(*) count FROM operations_tools
        WHERE {QUESTION_WHERE} AND error IS NOT NULL GROUP BY name,error ORDER BY count DESC,error""", args).fetchall()
    for row in tools:
        row.update(success=ratio(row["succeeded"],row["count"]), reasons=[r for r in reasons if r["name"] == row["name"]][:3])
    return dict(times=[dict(row,error_rate=ratio(row["failed"],row["count"])) for row in times],tools=tools)


def high_frequency(conn, args):
    rows = conn.execute("""
        WITH requests AS (
          SELECT user_id, occurred_at, count(*) OVER (
            PARTITION BY user_id ORDER BY occurred_at RANGE BETWEEN INTERVAL '1 hour' PRECEDING AND CURRENT ROW
          ) AS count
          FROM operations_answers WHERE occurred_at > %s - INTERVAL '1 hour'
            AND occurred_at < %s AND role=ANY(%s) AND elapsed_ms IS NOT NULL
        ), peaks AS (
          SELECT DISTINCT ON(user_id) user_id,count,occurred_at FROM requests
          WHERE occurred_at >= %s AND count>%s ORDER BY user_id,count DESC,occurred_at DESC
        )
        SELECT *,count(*) OVER () AS total FROM peaks ORDER BY count DESC,user_id LIMIT 50
    """, (*args, args[0], HIGH_FREQUENCY)).fetchall()
    return [dict(account=mask(r["user_id"]), count=r["count"], time=r["occurred_at"], total=r["total"]) for r in rows]


def security_report(conn, args):
    from session.operations import SECURITY_KINDS

    active = conn.execute("SELECT metric,started_at FROM operations_coverage WHERE metric=ANY(%s)",
                          (sorted(SECURITY_KINDS),)).fetchall()
    covered = {r["metric"]: r["started_at"] for r in active}
    rows = conn.execute("""
        SELECT (occurred_at AT TIME ZONE 'Asia/Shanghai')::date AS date, kind,count(*) count
        FROM operations_events WHERE occurred_at >= %s AND occurred_at < %s AND kind=ANY(%s)
        GROUP BY 1,2 ORDER BY 1
    """, (*args[:2], sorted(SECURITY_KINDS))).fetchall()
    return dict(detections={kind: dict(started_at=covered.get(kind),
                                     data=[r for r in rows if r["kind"] == kind])
                            for kind in sorted(SECURITY_KINDS)},
                frequency=high_frequency(conn, args))
