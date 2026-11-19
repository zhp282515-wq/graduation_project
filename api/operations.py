"""Administrator-only, Shanghai-calendar operational reports."""
import logging
from datetime import datetime
from threading import Event, Lock, Thread
from time import monotonic
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel

from auth.routes import require_admin
from config.operations import STALE_DAYS
from session.operations import AUDIT_ACTIONS
from session.operations_maintenance import maintain
from session.operations_reports import (
    ROLES, SHANGHAI, change, daily_overview, gaps, knowledge_report, mask, overview_metrics,
    quality_report, security_report, system_report, windows,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/dashboard", dependencies=[Depends(require_admin)])
Period = Literal["1", "7", "30"]
Scope = Literal["all", "user"]
Tab = Literal["overview", "quality", "knowledge", "system", "security"]


class OperationsReports:
    def __init__(self, pool):
        self.pool = pool
        self.cache = {}
        self.lock = Lock()
        self.stop = Event()
        self.worker = Thread(target=self.loop, name="operations-maintenance", daemon=True)
        self.worker.start()

    def close(self):
        self.stop.set()
        self.worker.join()

    def loop(self):
        while not self.stop.is_set():
            try:
                with self.pool.connection(timeout=5) as conn, conn.transaction():
                    maintain(conn, datetime.now(SHANGHAI))
            except Exception:
                log.error("运营聚合或告警更新失败", exc_info=True)
            self.stop.wait(60)

    def clear(self):
        with self.lock:
            self.cache.clear()

    def get(self, tab, days, role):
        now = datetime.now(SHANGHAI)
        key = (tab, days, role)
        with self.lock:
            if key in self.cache:
                date, expires, payload = self.cache[key]
                if date == now.date() and monotonic() < expires:
                    return payload
            with self.pool.connection() as conn, conn.transaction():
                conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                payload = load_report(conn, tab, days, role, now)
            self.cache[key] = (now.date(), monotonic()+45, payload)
            return payload


def load_report(conn, tab, days, role, now):
    current, previous = windows(now, days)
    args, prior = (*current, ROLES[role]), (*previous, ROLES[role])
    coverage = dict((r["metric"],r["started_at"]) for r in conn.execute(
        "SELECT metric,started_at FROM operations_coverage").fetchall())
    live = coverage["live"]
    activity_start = min(coverage.get("history", live), live) if role == "all" else live
    rating_start = conn.execute("SELECT started_at FROM feedback_started").fetchone()["started_at"]
    common = dict(updated_at=now, started_at=live, activity_started_at=activity_start,
                  rating_started_at=rating_start, start_date=current[0].date(), end_date=now.date())
    if tab == "overview":
        metrics = overview_metrics(conn, args, args[1] > activity_start, args[1] > live, rating_start)
        baseline = overview_metrics(conn, prior, prior[0] >= activity_start, prior[0] >= live, rating_start)
        if prior[0] < rating_start:
            baseline["approval"] = None
        trend = daily_overview(conn,current,previous,ROLES[role],activity_start,live,rating_start)
        stale = conn.execute("""SELECT count(*) AS n FROM kb_documents WHERE status='ready'
            AND updated_at < %s - make_interval(days => %s)""", (now,STALE_DAYS)).fetchone()["n"]
        alerts = conn.execute("""
            SELECT rule,triggered_at,recovered_at,value FROM operations_alerts
            WHERE recovered_at IS NULL OR recovered_at >= %s
            ORDER BY recovered_at IS NULL DESC,triggered_at DESC,id DESC LIMIT 50
        """, (current[0],)).fetchall()
        payload = dict(cards=[dict(key=k,value=v,previous=baseline[k],change=change(v,baseline[k]))
                              for k,v in metrics.items()], trend=trend,
                       gaps=gaps(conn,args,5), stale=stale, alerts=alerts)
    elif tab == "quality":
        payload = quality_report(conn,args,prior,now,live)
    elif tab == "knowledge":
        payload = knowledge_report(conn,args,now,live)
    elif tab == "system":
        payload = system_report(conn,args)
    else:
        payload = security_report(conn,args)
    return dict(common, **payload)


@router.get("/audit")
def audit(request: Request, response: Response, period: Period = "7", role: Scope = "all",
          action: str | None = Query(None, max_length=40), before: int | None = Query(None, ge=1)):
    if action and action not in AUDIT_ACTIONS:
        raise HTTPException(422, "未知操作类型")
    current, _ = windows(datetime.now(SHANGHAI), int(period))
    with request.app.state.pg_pool.connection() as conn:
        rows = conn.execute("""
            SELECT id,occurred_at,kind,object_id,actor_id FROM operations_events
            WHERE occurred_at >= %s AND occurred_at < %s AND kind=ANY(%s)
              AND (%s::bigint IS NULL OR (occurred_at,id) <
                (SELECT occurred_at,id FROM operations_events WHERE id=%s))
            ORDER BY occurred_at DESC,id DESC LIMIT 21
        """, (*current, ["audit:" + k for k in ([action] if action else AUDIT_ACTIONS)], before,before)).fetchall() if role == "all" else []
    response.headers["Cache-Control"] = "private, no-store"
    return {"items": [dict(id=r["id"],time=r["occurred_at"],action=AUDIT_ACTIONS[r["kind"][6:]],
                           actor=mask(r["actor_id"]),object=r["object_id"]) for r in rows[:20]],
            "next": rows[19]["id"] if len(rows)>20 else None,
            "actions": AUDIT_ACTIONS}


@router.get("/{tab}")
def dashboard(tab: Tab, request: Request, response: Response, period: Period = "7", role: Scope = "all"):
    response.headers["Cache-Control"] = "private, no-store"
    return request.app.state.operations_reports.get(tab,int(period),role)


class GapMark(BaseModel):
    state: Literal["fixed", "ignored"]


@router.put("/gaps/{keyword}")
def mark_gap(keyword: str, body: GapMark, request: Request):
    with request.app.state.pg_pool.connection() as conn, conn.transaction():
        known = conn.execute("""
            SELECT 1 FROM operations_tools WHERE keyword=%s AND name='knowledge_search'
            AND error IS NULL AND results=0 LIMIT 1
        """, (keyword,)).fetchone()
        if not known:
            raise HTTPException(404, "知识缺口不存在")
        conn.execute("""INSERT INTO operations_gap_marks(keyword,state) VALUES (%s,%s)
            ON CONFLICT(keyword) DO UPDATE SET state=excluded.state, marked_at=now()""",
            (keyword,body.state))
    request.state.audit_object = keyword
    request.app.state.operations_reports.clear()
    return {"state": body.state}
