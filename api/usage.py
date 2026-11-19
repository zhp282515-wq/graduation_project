"""Administrator-only token totals. The cache contains counters, never account names."""
from datetime import datetime, timedelta
from threading import Lock
from time import monotonic
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from auth.routes import require_admin

SHANGHAI = ZoneInfo("Asia/Shanghai")
Role = Literal["all", "user", "admin"]
router = APIRouter(prefix="/api/admin/usage", dependencies=[Depends(require_admin)])


def summarize(rows, yesterday, now, role):
    today = now.astimezone(SHANGHAI).date()
    roles = ("user", "admin") if role == "all" else (role,)
    days = {}
    overview, rankings = [], {}
    for offset in range(29, -1, -1):
        date = today - timedelta(days=offset)
        days[date] = dict(date=date.isoformat(), user=0, admin=0, total=None)
    rows = [r for r in rows if r["role"] in roles]
    for row in rows:
        point = days.get(row["day"])
        if point is not None:
            value = row["total_tokens"]
            point[row["role"]] += value
            point["total"] = (point["total"] or 0) + value
    for period in (1, 7, 30):
        first = today - timedelta(days=period - 1)
        previous_start = first - timedelta(days=period)
        card = dict(period=period, input=0, output=0, total=0, user=0, admin=0, calls=0)
        accounts = {}
        previous = 0
        for row in rows:
            value = row["total_tokens"]
            if previous_start <= row["day"] < first:
                previous += value
            if not first <= row["day"] <= today:
                continue
            card["input"] += row["input_tokens"]
            card["output"] += row["output_tokens"]
            card["total"] += value
            card["calls"] += row["calls"]
            card[row["role"]] += value
            account = accounts.setdefault(row["user_id"], dict(total=0, roles=set()))
            account["total"] += value
            account["roles"].add(row["role"])
        if period == 1:
            previous = sum(yesterday.get(r, 0) for r in roles)
        card.update(active=len(accounts), previous=previous,
                    unclassified=card["total"] - card["input"] - card["output"],
                    change=round(100 * (card["total"] - previous) / previous, 1) if previous else None)
        overview.append(card)
        rankings[period] = sorted(accounts.items(), key=lambda item: (-item[1]["total"], item[0]))
    return dict(overview=overview, trend=list(days.values()), rankings=rankings, updated_at=now.isoformat())


class Reports:
    def __init__(self, pool):
        self.pool = pool
        self.lock = Lock()
        self.expires = 0
        self.date = None
        self.data = {}

    def get(self, role):
        with self.lock:
            now = datetime.now(SHANGHAI)
            if self.date == now.date() and monotonic() < self.expires:
                return self.data[role]
            midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
            with self.pool.connection() as conn, conn.transaction():
                conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                rows = conn.execute("""
                    SELECT * FROM token_usage_confirmed_daily WHERE day BETWEEN %s AND %s
                """, (now.date() - timedelta(days=59), now.date())).fetchall()
                yesterday = conn.execute("""
                    SELECT role, sum(total_tokens)::bigint AS total FROM token_usage_calls
                    WHERE NOT estimated AND created_at >= %s AND created_at < %s GROUP BY role
                """, (midnight - timedelta(days=1), now - timedelta(days=1))).fetchall()
            partial = {r["role"]: r["total"] for r in yesterday}
            self.data = {key: summarize(rows, partial, now, key) for key in ("all", "user", "admin")}
            self.date, self.expires = now.date(), monotonic() + 45
            return self.data[role]


def snapshot(request: Request, response: Response, role: Role = "all"):
    response.headers["Cache-Control"] = "private, no-store"
    return request.app.state.usage_reports.get(role)


@router.get("/access", status_code=204)
def access():
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.get("/overview")
def overview(data=Depends(snapshot)):
    return dict(items=data["overview"], updated_at=data["updated_at"])


@router.get("/trend")
def trend(data=Depends(snapshot)):
    return dict(items=data["trend"], updated_at=data["updated_at"])


@router.get("/ranking")
def ranking(request: Request, days: int = Query(1), limit: int = Query(5, ge=1, le=100),
            offset: int = Query(0, ge=0), data=Depends(snapshot)):
    if days not in (1, 7, 30):
        raise HTTPException(422, "请选择今日、7 天或 30 天")
    ordered = data["rankings"][days]
    page = ordered[offset:offset + limit]
    names = {}
    if page:
        with request.app.state.pg_pool.connection() as conn:
            users = conn.execute("SELECT id,username FROM app_users WHERE enabled AND id=ANY(%s)",
                                 ([uid for uid, _ in page],)).fetchall()
        names = {u["id"]: u["username"][:1] + "***" + u["username"][-1:] for u in users}
    return dict(total=len(ordered), updated_at=data["updated_at"], items=[
        dict(label=names.get(uid, "已注销用户"), roles=sorted(account["roles"]), total=account["total"])
        for uid, account in page
    ])
