"""Administrative log queries and audit events for explicit business operations."""
import logging
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from session import log_context
from session.operations import AUDIT_ACTIONS, EVENT
from auth.routes import require_admin

router = APIRouter(prefix="/api/admin/logs", dependencies=[Depends(require_admin)])
SHANGHAI = ZoneInfo("Asia/Shanghai")
ACTIONS = {
    "register": "注册账号", "login": "登录", "logout": "退出登录", "password": "修改密码",
    "add_user": "创建账号", "update_user": "修改账号权限或状态", "delete_user": "注销账号",
    "reset_password": "重置密码", "create_session": "创建会话", "delete_session": "删除会话",
    "chat": "发送消息", "regenerate_message": "重新生成回答", "upload_image": "上传图片",
    "create_note": "创建笔记", "update_note": "修改笔记", "delete_note": "删除笔记",
    "create_memory": "创建记忆", "update_memory": "修改记忆", "delete_memory": "删除记忆",
    "upload_knowledge_document": "提交知识库入库", "delete_knowledge_document": "删除知识库文档",
    "update_visibility": "修改文档可见范围", "sync_knowledge": "同步知识库",
    "search_knowledge": "检索知识库", "update_model_settings": "更新模型配置",
}


class AuditMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        with log_context.bind(log_context.request_state, scope.setdefault("state", {})):
            return await self.audit(scope, receive, send)

    async def audit(self, scope, receive, send):
        if scope["method"] in {"HEAD", "GET", "OPTIONS"}:
            return await self.app(scope, receive, send)
        status = 500

        async def inspect_status(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, inspect_status)
        finally:
            name = getattr(scope.get("route"), "name", None)
            state = scope.get("state", {})
            operations = getattr(scope["app"].state, "operations_writer", None)
            if operations and name in AUDIT_ACTIONS and state.get("audit_role") == "admin" and 200 <= status < 300:
                document = scope.get("path_params", {}).get("file_md5", "")
                if not re.fullmatch(r"[0-9a-f]{32}", document):
                    document = None
                target = state.get("audit_object") or document or {
                    "update_model_settings": "问答模型", "sync_knowledge": "知识库登记表",
                }.get(name)
                operations.submit(EVENT, ("audit:" + name,target,state.get("audit_actor")))
            writer = getattr(scope["app"].state, "dashboard_logs", None)
            if writer and name in ACTIONS:
                ok = 200 <= status < 300
                if name in ("chat", "regenerate_message"):
                    ok = ok and state.get("chat_completed", False)
                try:
                    writer.submit((datetime.now(timezone.utc), "operations", "账号操作", ACTIONS[name],
                                   None, state.get("audit_actor"), "成功" if ok else "失败", None))
                except Exception:
                    logging.getLogger(__name__).error("用户操作日志采集失败")


@router.get("")
def logs(request: Request, response: Response, category: Literal["runtime", "operations"]="runtime",
         start: date | None=None, end: date | None=None, level: Literal["DEBUG","INFO","WARNING","ERROR","CRITICAL"] | None=None,
         source: str=Query("", max_length=60), actor_id: str=Query("", max_length=64),
         outcome: Literal["成功","失败"] | None=None, before: int | None=Query(None, ge=1)):
    response.headers["Cache-Control"] = "private, no-store"
    if start and end and start > end:
        raise HTTPException(422, "开始日期应早于或等于结束日期")
    clauses, values = ["category=%s"], [category]
    if start:
        clauses.append("occurred_at >= %s")
        values.append(datetime.combine(start, time.min, SHANGHAI))
    if end and end < date.max:
        clauses.append("occurred_at < %s")
        values.append(datetime.combine(end + timedelta(days=1), time.min, SHANGHAI))
    for column, value in (("level",level), ("source",source), ("actor_id",actor_id.strip().lower()), ("outcome",outcome)):
        if value:
            clauses.append(column+"=%s")
            values.append(value)
    if before:
        clauses.append("(occurred_at,id) < (SELECT occurred_at,id FROM admin_log_events WHERE id=%s)")
        values.append(before)
    query = """SELECT id,occurred_at,source,event,level,actor_id,outcome,ctx.purpose,ctx.model,ctx.actor_kind
               FROM admin_log_events LEFT JOIN admin_log_context ctx ON ctx.event_id=admin_log_events.id
               WHERE """ + " AND ".join(clauses) + " ORDER BY occurred_at DESC,id DESC LIMIT 31"
    with request.app.state.pg_pool.connection() as conn:
        rows = conn.execute(query, values).fetchall()
    return {"items": rows[:30], "next": rows[29]["id"] if len(rows)>30 else None}
