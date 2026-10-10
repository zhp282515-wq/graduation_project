import time
from collections.abc import Iterator
from typing import Any

from agent.runtime import AgentRuntime
from agent.state import AgentInput
from session.models import DEFAULT_SESSION_TITLE, Message, Session
from session.ports import SessionRepository
from utils.image_tool import build_query
from utils.logger_tool import logger

_AUTOTITLE_MAX_LEN = 30


class SessionService:
    """会话生命周期 + Agent 事件流 + 落库。runtime 由外部注入，不持有连接。"""

    def __init__(
        self,
        repository: SessionRepository,
        runtime: AgentRuntime,
    ):
        self._repo = repository
        self._runtime = runtime

    def create_session(self, title: str | None = None) -> Session:
        return self._repo.create_session(title or DEFAULT_SESSION_TITLE)

    def get_session(self, session_id: str) -> Session | None:
        return self._repo.get_session(session_id)

    def list_sessions(self) -> list[Session]:
        return self._repo.list_sessions()

    def history(self, session_id: str) -> list[Message]:
        return self._repo.get_messages(session_id)

    def delete_session(self, session_id: str) -> bool:
        """删除会话及其全部数据（业务消息 + checkpoint）。不存在则返回 False。"""
        if self._repo.get_session(session_id) is None:
            return False

        # 先删 checkpoint，再删业务行。顺序是刻意的：
        # 若 checkpoint 删除失败，业务行还在，调用方可重试；
        # 反过来则会出现"会话已消失、checkpoint 却残留"且无从引用的泄漏。
        self._runtime.delete_thread(session_id)
        deleted = self._repo.delete_session(session_id)
        logger.info("会话 %s 已删除", session_id)
        return deleted

    def send_message(
        self,
        session_id: str,
        text: str,
        *,
        images: list[str] | None = None,
        max_turns: int | None = None,
        enable_thinking: bool | None = None,
        reasoning_effort: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """把一条用户消息喂给 Agent，透传事件流，并在结束时落库。"""
        session = self._repo.get_session(session_id)
        if session is None:
            raise ValueError(f"会话不存在：{session_id}")

        # 落库只存文本 + 占位，图片本身在 checkpoint 里，见"决策 2"
        stored = f"[图片×{len(images)}] {text}" if images else text
        self._repo.add_message(session_id, "user", stored)
        if session.title == DEFAULT_SESSION_TITLE:
            self._repo.update_session_title(session_id, text[:_AUTOTITLE_MAX_LEN] or "图片消息")

        agent_input: AgentInput = {"query": build_query(text, images)}
        if max_turns is not None:
            agent_input["max_turns"] = max_turns
        if enable_thinking is not None:
            agent_input["enable_thinking"] = enable_thinking
        if reasoning_effort is not None:
            agent_input["reasoning_effort"] = reasoning_effort

        started = time.perf_counter()
        final_content = ""
        token_usage: dict[str, Any] | None = None

        try:
            for event in self._runtime.stream(agent_input, session_id=session_id):
                if event.get("type") == "done":
                    final = event.get("final_answer") or {}
                    final_content = final.get("content", "") or ""
                    token_usage = final.get("token_usage")
                yield event
        finally:
            # 生成器被提前关闭（调用方 break）时也会执行；此时 final_content 为空，
            # 不落库，避免写入半截回答。
            if final_content:
                self._repo.add_message(
                    session_id,
                    "assistant",
                    final_content,
                    token_usage=token_usage,
                )
                self._repo.touch_session(session_id)
                logger.info(
                    "会话 %s 完成一轮，耗时 %.2fs", session_id, time.perf_counter() - started
                )