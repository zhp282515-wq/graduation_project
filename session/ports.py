from typing import Any, Protocol, Iterator

from session.models import Message, Session


class SessionRepository(Protocol):
    """会话持久化接口。实现可以是 Postgres，也可以是内存/测试替身。"""

    def create_session(self, user_id: str, title: str) -> Session: ...

    def find_empty_session(self, user_id: str, default_title: str) -> Session | None: ...

    def get_session(self, user_id: str, session_id: str) -> Session | None: ...

    def list_sessions(self, user_id: str) -> list[Session]: ...

    def update_session_title(self, user_id: str, session_id: str, title: str) -> None: ...

    def touch_session(self, user_id: str, session_id: str) -> None: ...

    def delete_session(self, user_id: str, session_id: str) -> bool: ...

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        images: list[str] | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
        token_usage: dict[str, Any] | None = None,
    ) -> Message: ...

    def get_messages(self, user_id: str, session_id: str) -> list[Message]: ...


class AgentPort(Protocol):
    """业务层看到的 Agent 能力。实现是 AgentRuntime，但这里不依赖它。

    入参 query 是已组装好的模型内容块，由 API/适配层负责拼装，
    业务层不关心里面有几张图、文本怎么拼。
    """

    def stream(
        self,
        query: list[dict[str, Any]],
        *,
        session_id: str,
        max_turns: int | None = None,
        reasoning: Any | None = None,
        memory: list[str] | None = None,
        cancel_event: Any = None,
    ) -> Iterator[dict[str, Any]]: ...

    def delete_thread(self, session_id: str) -> None: ...