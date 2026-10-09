from typing import Any, Protocol

from session.models import Message, Session


class SessionRepository(Protocol):
    """会话持久化接口。实现可以是 Postgres，也可以是内存/测试替身。"""

    def create_session(self, title: str) -> Session: ...

    def get_session(self, session_id: str) -> Session | None: ...

    def list_sessions(self) -> list[Session]: ...

    def update_session_title(self, session_id: str, title: str) -> None: ...

    def touch_session(self, session_id: str) -> None: ...

    def delete_session(self, session_id: str) -> bool: ...

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
        token_usage: dict[str, Any] | None = None,
    ) -> Message: ...

    def get_messages(self, session_id: str) -> list[Message]: ...