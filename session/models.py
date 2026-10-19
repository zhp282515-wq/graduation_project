from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

SessionStatus = Literal["active", "archived"]

DEFAULT_SESSION_TITLE = "新会话"


@dataclass
class Session:
    id: str
    user_id: str
    title: str
    status: SessionStatus
    created_at: datetime
    updated_at: datetime


@dataclass
class Message:
    id: int
    session_id: str
    role: str
    content: str
    created_at: datetime | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    token_usage: dict[str, Any] | None = None
    images: list[str] | None = None