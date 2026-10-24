import time
from collections.abc import Callable, Iterator
from typing import Any

from session.models import DEFAULT_SESSION_TITLE, Memory, Message, Session
from session.ports import AgentPort, SessionRepository
from session.runs import DEFAULT_RUNS, KeyedLocks, RunStream
from utils.logger_tool import logger
from datetime import datetime

_AUTOTITLE_MAX_LEN = 30


class SessionService:
    """会话生命周期 + Agent 事件流 + 落库。runtime 由外部注入，不持有连接。"""

    def __init__(
        self,
        repository: SessionRepository,
        runtime: AgentPort,
        *,
        runs: KeyedLocks | None = None,
        on_complete: Callable[[str, str, str], None] | None = None,
    ):
        self._repo = repository
        self._runtime = runtime
        self._runs = runs if runs is not None else DEFAULT_RUNS
        self._on_complete = on_complete

    def create_session(self, user_id: str, title: str | None = None) -> Session:
        # 未指定标题（= 用户点「新会话」）时复用已有的空会话，
        # 保证同一用户最多只有一个空会话，不会越点越多。
        if title is None:
            existing = self._repo.find_empty_session(user_id, DEFAULT_SESSION_TITLE)
            if existing is not None:
                return existing
        return self._repo.create_session(user_id, title or DEFAULT_SESSION_TITLE)

    def get_session(self, user_id: str, session_id: str) -> Session | None:
        return self._repo.get_session(user_id, session_id)

    # ---------- 长期记忆 ----------
    def list_memories(self, user_id: str) -> list[Memory]:
        return self._repo.list_memories(user_id)

    def update_memory(self, user_id: str, memory_id: str, content: str) -> Memory | None:
        return self._repo.update_memory(user_id, memory_id, content)

    def delete_memory(self, user_id: str, memory_id: str) -> bool:
        return self._repo.delete_memory(user_id, memory_id)

    def list_sessions(self, user_id: str) -> list[Session]:
        return self._repo.list_sessions(user_id)

    def history(self, user_id: str, session_id: str) -> list[Message]:
        return self._repo.get_messages(user_id, session_id)

    def delete_session(self, user_id: str, session_id: str) -> bool:
        """删除会话及其全部数据（业务消息 + checkpoint）。不存在则返回 False。"""
        if self._repo.get_session(user_id, session_id) is None:
            return False

        # 先删 checkpoint，再删业务行。顺序是刻意的：
        # 若 checkpoint 删除失败，业务行还在，调用方可重试；
        # 反过来则会出现"会话已消失、checkpoint 却残留"且无从引用的泄漏。
        with self._runs.acquire(session_id):
            if self._repo.get_session(user_id, session_id) is None:
                return False
            self._runtime.delete_thread(session_id)
            deleted = self._repo.delete_session(user_id, session_id)
        logger.info("用户 %s 删除会话 %s", user_id, session_id)
        return deleted

    def send_message(
        self,
        user_id: str,
        session_id: str,
        query: list[dict[str, Any]],
        *,
        text: str,
        images: list[str] | None = None,
        image_urls: list[str] | None = None,
        max_turns: int | None = None,
        reasoning: Any | None = None,
    ) -> RunStream:
        """校验 + 落库在调用时立即执行；流式部分由内部生成器负责。

        这样接 FastAPI 时，"会话不存在" 能在响应头发出前抛成 404，
        而不是在 200 之后断流。

        images 是给模型读取的本地路径；image_urls 是落库、供前端回显的地址。
        两者分开是因为模型要能读文件，而浏览器要能直接 <img src>。
        """
        session = self._repo.get_session(user_id, session_id)
        if session is None:
            raise ValueError(f"会话不存在：{session_id}")

        lease = self._runs.acquire(session_id)
        try:
            session = self._repo.get_session(user_id, session_id)
            if session is None:
                raise ValueError(f"会话不存在：{session_id}")
            self._repo.add_message(
                session_id, "user", text,
                images=image_urls if image_urls is not None else images,
            )
            if session.title == DEFAULT_SESSION_TITLE:
                self._repo.update_session_title(user_id, session_id, text[:_AUTOTITLE_MAX_LEN] or "图片消息")
            return RunStream(self._stream(
                session_id, query, max_turns=max_turns,
                reasoning=reasoning, user_id=user_id,
            ), lease)
        except BaseException:
            lease.release()
            raise

    def _stream(
        self,
        session_id: str,
        query: list[dict[str, Any]],
        *,
        max_turns: int | None,
        reasoning: Any | None = None,
        user_id: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        started = time.perf_counter()
        pending_done = None
        yield {
            "type": "run_started",
            "session_id": session_id,
            "started_at": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            memory_lines = [m.content for m in self._repo.list_memories(user_id)] if user_id else []
            events = self._runtime.stream(
                query, session_id=session_id, max_turns=max_turns,
                reasoning=reasoning, memory=memory_lines,
            )
            try:
                for event in events:
                    kind = event.get("type")
                    if kind == "done":
                        if pending_done is not None:
                            raise RuntimeError("Agent 返回了重复的完成事件")
                        pending_done = event
                    elif kind == "run_failed":
                        raise RuntimeError(event.get("message") or "Agent 执行失败")
                    else:
                        yield event
            finally:
                close = getattr(events, "close", None)
                if close:
                    close()
            final = (pending_done or {}).get("final_answer") or {}
            answer = final.get("content")
            if not isinstance(answer, str) or not answer.strip():
                raise RuntimeError("Agent 未返回有效的完成结果")
            usage = dict(final.get("token_usage") or {})
            if isinstance(final.get("total_tokens"), int):
                usage["total_tokens"] = final["total_tokens"]
            self._repo.complete_turn(session_id, answer, token_usage=usage or None)
        except Exception as exc:
            logger.exception("会话 %s 本轮执行失败", session_id)
            yield {
                "type": "run_failed",
                "error_type": type(exc).__name__,
                "message": str(exc),
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
            }
            return

        logger.info("会话 %s 完成一轮并保存回答，耗时 %.2fs", session_id, time.perf_counter() - started)
        # 后台任务登记失败也不能把已经提交的回答改判失败。
        if self._on_complete and user_id:
            user_text = "".join(
                p.get("text", "") for p in query
                if isinstance(p, dict) and p.get("type") == "text"
            )
            try:
                self._on_complete(user_id, user_text, answer)
            except Exception:
                logger.exception("后台记忆任务登记失败（回答已保存）")
        yield pending_done
