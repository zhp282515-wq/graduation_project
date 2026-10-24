from typing import Any, Protocol, Iterator
from collections.abc import Callable

from session.models import Memory, Message, Session


class SessionRepository(Protocol):
    """会话持久化接口。实现可以是 Postgres，也可以是内存/测试替身。"""

    def create_session(self, user_id: str, title: str) -> Session: ...

    def find_empty_session(self, user_id: str, default_title: str) -> Session | None: ...

    def get_session(self, user_id: str, session_id: str) -> Session | None: ...

    def list_sessions(self, user_id: str) -> list[Session]: ...

    def update_session_title(self, user_id: str, session_id: str, title: str) -> None: ...

    def touch_session(self, session_id: str) -> None: ...

    def complete_turn(self, session_id: str, content: str, *, token_usage: dict[str, Any] | None = None,
                      sources: list[dict[str, Any]] | None = None, reply_to_message_id: int | None = None) -> Message: ...

    def replace_answer(self, session_id: str, message_id: int, content: str, *,
                       token_usage: dict[str, Any] | None, sources: list[dict[str, Any]]) -> Message: ...

    def list_memories(self, user_id: str) -> list[Memory]: ...

    def add_memory(self, user_id: str, content: str, category: str = "fact") -> Memory: ...

    def update_memory(self, user_id: str, memory_id: str, content: str) -> Memory | None: ...

    def delete_memory(self, user_id: str, memory_id: str) -> bool: ...

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
        history: Callable[[], list[dict[str, Any]]] | None = None,
        context_revision: int = 0,
    ) -> Iterator[dict[str, Any]]: ...

    def delete_thread(self, session_id: str) -> None: ...
