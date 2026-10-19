import time
from collections.abc import Iterator
from typing import Any

from session.models import DEFAULT_SESSION_TITLE, Message, Session
from session.ports import AgentPort, SessionRepository
from utils.logger_tool import logger
from datetime import datetime

_AUTOTITLE_MAX_LEN = 30


class SessionService:
    """会话生命周期 + Agent 事件流 + 落库。runtime 由外部注入，不持有连接。"""

    def __init__(
        self,
        repository: SessionRepository,
        runtime: AgentPort,
    ):
        self._repo = repository
        self._runtime = runtime

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
    ) -> Iterator[dict[str, Any]]:
        """校验 + 落库在调用时立即执行；流式部分由内部生成器负责。

        这样接 FastAPI 时，"会话不存在" 能在响应头发出前抛成 404，
        而不是在 200 之后断流。

        images 是给模型读取的本地路径；image_urls 是落库、供前端回显的地址。
        两者分开是因为模型要能读文件，而浏览器要能直接 <img src>。
        """
        session = self._repo.get_session(user_id, session_id)
        if session is None:
            raise ValueError(f"会话不存在：{session_id}")

        self._repo.add_message(
            session_id,
            "user",
            text,
            images=image_urls if image_urls is not None else images,
        )
        if session.title == DEFAULT_SESSION_TITLE:
            self._repo.update_session_title(user_id, session_id, text[:_AUTOTITLE_MAX_LEN] or "图片消息")

        return self._stream(
            session_id,
            query,
            max_turns=max_turns,
            reasoning=reasoning,
        )

    def _stream(
        self,
        session_id: str,
        query: list[dict[str, Any]],
        *,
        max_turns: int | None,
        reasoning: Any | None = None,
    ) -> Iterator[dict[str, Any]]:
        started = time.perf_counter()
        final_content = ""
        token_usage: dict[str, Any] | None = None

        yield {
            "type": "run_started",
            "session_id": session_id,
            "started_at": datetime.now().isoformat(timespec="seconds"),
        }

        try:
            for event in self._runtime.stream(
                query,
                session_id=session_id,
                max_turns=max_turns,
                reasoning=reasoning,
            ):
                if event.get("type") == "done":
                    final = event.get("final_answer") or {}
                    final_content = final.get("content", "") or ""
                    token_usage = final.get("total_tokens")
                yield event
        except Exception as exc:
            # 图抛异常时，调用方还没收到 done，必须补一个终止事件，
            # 否则前端永远卡在"运行中"
            logger.exception("会话 %s 本轮执行失败", session_id)

            yield {
                "type": "run_failed",
                "error_type": type(exc).__name__,
                "message": str(exc),
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
            }
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