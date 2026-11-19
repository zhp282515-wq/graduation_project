"""Explicit user reports and per-answer-version votes."""
from datetime import date, datetime, time, timedelta
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field, StrictBool

from auth.routes import get_current_user, require_admin

SHANGHAI = ZoneInfo("Asia/Shanghai")
Category = Literal["answer", "knowledge", "bug", "suggestion", "other"]
Reason = Literal["inaccurate", "unresolved", "verbose", "other"]
router = APIRouter(prefix="/api")
MAX_IMAGE = 10 * 1024 * 1024


def require_feedback_sender(user=Depends(get_current_user)):
    if user["role"] != "user":
        raise HTTPException(403, "意见反馈仅供普通用户提交")
    return user


def image_type(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 45 and data[12:16] == b"IHDR":
        return "image/png"
    if data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9") and len(data) > 16:
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")) and len(data) >= 14 and data.endswith(b";"):
        return "image/gif"
    if (len(data) >= 20 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
            and data[12:16] in (b"VP8 ", b"VP8L", b"VP8X")
            and int.from_bytes(data[4:8], "little") == len(data) - 8):
        return "image/webp"
    return None


def lock_answer(conn, user_id, message_id, revision, session_id=None):
    answer = conn.execute("""
        SELECT m.session_id FROM messages m JOIN sessions s ON s.id=m.session_id
        WHERE m.id=%s AND s.user_id=%s AND m.role='assistant' FOR UPDATE OF m
    """, (message_id, user_id)).fetchone()
    if not answer or (session_id is not None and answer["session_id"] != session_id):
        raise HTTPException(404, "回答不存在")
    row = conn.execute("SELECT revision FROM answer_revisions WHERE message_id=%s", (message_id,)).fetchone()
    if revision != (row["revision"] if row else 0):
        raise HTTPException(409, "回答已经更新，请重新打开会话")


class Rating(BaseModel):
    revision: int = Field(ge=0)
    vote: Literal["like", "dislike"] | None


@router.put("/sessions/{session_id}/messages/{message_id}/rating")
def rate_answer(session_id: str, message_id: int, body: Rating, request: Request,
                user=Depends(get_current_user)):
    key = (user["id"], message_id, body.revision)
    with request.app.state.pg_pool.connection() as conn, conn.transaction():
        lock_answer(conn, *key, session_id)
        if body.vote is None:
            conn.execute("DELETE FROM answer_ratings WHERE (user_id,message_id,revision)=(%s,%s,%s)", key)
        else:
            conn.execute("""
                INSERT INTO answer_ratings(user_id,message_id,revision,role,vote) VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (user_id,message_id,revision) DO UPDATE SET vote=excluded.vote,
                    role=excluded.role, reason=NULL, voted_at=now()
                WHERE answer_ratings.vote <> excluded.vote
            """, (*key, user["role"], body.vote))
    return {"vote": body.vote}


@router.post("/feedback", status_code=201)
def submit_feedback(
    request: Request, submission_id: Annotated[UUID, Form()], category: Annotated[Category, Form()],
    description: Annotated[str, Form(max_length=2000)] = "",
    message_id: Annotated[int | None, Form(ge=1)] = None,
    revision: Annotated[int | None, Form(ge=0)] = None,
    reason: Annotated[Reason | None, Form()] = None,
    attachments: Annotated[list[UploadFile] | None, Form()] = None,
    user=Depends(require_feedback_sender),
):
    description = description.strip()
    if (message_id is None) != (revision is None) or (reason and message_id is None):
        raise HTTPException(422, "请提供对应的回答版本")
    if not description and not reason:
        raise HTTPException(422, "请填写说明或选择点踩原因")
    attachments = attachments or []
    if len(attachments) > 3:
        raise HTTPException(422, "每条反馈最多上传 3 张图片")
    pictures = []
    for file in attachments:
        data = file.file.read(MAX_IMAGE + 1)
        kind = image_type(data)
        if len(data) > MAX_IMAGE:
            raise HTTPException(413, "单张图片不能超过 10 MB")
        if not kind or kind != file.content_type:
            raise HTTPException(415, "图片须为 JPEG、PNG、GIF 或 WebP")
        pictures.append((kind, data))
    with request.app.state.pg_pool.connection() as conn, conn.transaction():
        params = (user["id"], submission_id)
        # The insert serializes retries before validating the current answer revision.
        row = conn.execute("""
            INSERT INTO feedback_entries(user_id,submission_id,category,description,message_id,revision,reason)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (user_id,submission_id) DO NOTHING RETURNING id
        """, (*params, category, description, message_id, revision, reason)).fetchone()
        if row is None:
            return conn.execute("""
                SELECT id FROM feedback_entries WHERE user_id=%s AND submission_id=%s
            """, params).fetchone()
        if message_id is not None:
            lock_answer(conn, user["id"], message_id, revision)
            vote = conn.execute("""
                UPDATE answer_ratings SET reason=COALESCE(%s,reason)
                WHERE user_id=%s AND message_id=%s AND revision=%s AND vote='dislike' RETURNING vote
            """, (reason, user["id"], message_id, revision)).fetchone()
            if not vote:
                raise HTTPException(409, "请先对该回答点踩")
        for position, (kind, data) in enumerate(pictures, 1):
            conn.execute("INSERT INTO feedback_attachments VALUES (%s,%s,%s,%s)",
                         (row["id"], position, kind, data))
    return row


@router.get("/feedback/{entry_id}/images/{position}")
def feedback_image(entry_id: int, position: int, request: Request, user=Depends(get_current_user)):
    with request.app.state.pg_pool.connection() as conn:
        row = conn.execute("""
            SELECT b.data,b.media_type FROM feedback_attachments b JOIN feedback_entries f ON f.id=b.entry_id
            WHERE b.entry_id=%s AND b.position=%s AND (f.user_id=%s OR %s)
        """, (entry_id, position, user["id"], user["role"] == "admin")).fetchone()
    if not row:
        raise HTTPException(404, "图片不存在")
    return Response(row["data"], media_type=row["media_type"], headers={
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
    })


@router.get("/admin/feedback")
def feedback_list(
    request: Request, response: Response, category: Category | None = None,
    source: Literal["general", "dislike"] | None = None,
    status: Literal["all", "pending", "processed"] = "all",
    user_id: str | None = Query(None, pattern=r"^[a-fA-F0-9]{32}$"),
    start: date | None = None, end: date | None = None,
    before: int | None = Query(None, ge=1), user=Depends(require_admin),
):
    if start and end and start > end:
        raise HTTPException(422, "开始日期不能晚于结束日期")
    filters = ["true"]
    params = []
    for value, condition in [
        (category, "f.category=%s"), (user_id.lower() if user_id else None, "f.user_id=%s"),
        (None if status == "all" else status == "processed", "coalesce(p.processed, false)=%s"),
        (datetime.combine(start, time.min, SHANGHAI) if start else None, "f.created_at >= %s"),
        (datetime.combine(end, time.max, SHANGHAI) if end else None, "f.created_at <= %s"),
        (before, "(f.created_at,f.id) < (SELECT created_at,id FROM feedback_entries WHERE id=%s)"),
    ]:
        if value is not None:
            filters.append(condition)
            params.append(value)
    if source:
        filters.append("f.message_id IS NULL" if source == "general" else "f.message_id IS NOT NULL")
    with request.app.state.pg_pool.connection() as conn:
        rows = conn.execute(f"""
            SELECT f.id, f.user_id, u.username, f.category, f.description, f.reason,
                f.message_id IS NOT NULL AS from_dislike, f.created_at,
                coalesce(p.processed, false) AS processed,
                ARRAY(SELECT position FROM feedback_attachments WHERE entry_id=f.id ORDER BY position) AS images
            FROM feedback_entries f LEFT JOIN app_users u ON u.id=f.user_id
            LEFT JOIN feedback_processing p ON p.entry_id=f.id
            WHERE {' AND '.join(filters)} ORDER BY f.created_at DESC,f.id DESC LIMIT 21
        """, params).fetchall()
    response.headers["Cache-Control"] = "private, no-store"
    return {"items": rows[:20], "next": rows[19]["id"] if len(rows) > 20 else None}


class FeedbackStatus(BaseModel):
    processed: StrictBool


@router.put("/admin/feedback/{entry_id}/status")
def update_feedback_status(entry_id: int, body: FeedbackStatus, request: Request, user=Depends(require_admin)):
    with request.app.state.pg_pool.connection() as conn:
        row = conn.execute("""
            INSERT INTO feedback_processing(entry_id, processed)
            SELECT id, %s FROM feedback_entries WHERE id=%s
            ON CONFLICT (entry_id) DO UPDATE SET processed=excluded.processed
            RETURNING processed
        """, (body.processed, entry_id)).fetchone()
    if row is None:
        raise HTTPException(404, "反馈不存在")
    return row


@router.get("/admin/feedback/trend")
def rating_trend(request: Request, response: Response, user=Depends(require_admin)):
    now = datetime.now(SHANGHAI)
    first = now.date() - timedelta(days=29)
    with request.app.state.pg_pool.connection() as conn:
        started = conn.execute("SELECT started_at FROM feedback_started").fetchone()["started_at"]
        rows = conn.execute("""
            SELECT (voted_at AT TIME ZONE 'Asia/Shanghai')::date AS day, vote, count(*) AS n
            FROM answer_ratings WHERE voted_at >= %s AND voted_at <= %s GROUP BY 1,2
        """, (datetime.combine(first, time.min, SHANGHAI), now)).fetchall()
    counts = {(r["day"], r["vote"]): r["n"] for r in rows}
    days = [first + timedelta(days=n) for n in range(30)]
    response.headers["Cache-Control"] = "private, no-store"
    return {"started_at": started, "days": [
        {"date": day, **{vote: (counts.get((day, vote), 0) if day >= started.astimezone(SHANGHAI).date()
                              else None) for vote in ("like", "dislike")}}
        for day in days
    ]}
