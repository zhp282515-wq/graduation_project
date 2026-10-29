import time
from uuid import uuid4
from collections.abc import Callable, Iterator
from typing import Any

from session.models import DEFAULT_SESSION_TITLE, Memory, Message, Note, Session
from session.ports import AgentPort, SessionRepository
from session.runs import DEFAULT_RUNS, KeyedLocks, RunStream
from session.sources import normalize_sources
from utils.logger_tool import logger
from datetime import datetime

_AUTOTITLE_MAX_LEN = 30


class ModelCapabilityError(ValueError):
    """当前模型无法处理本次请求或其历史。"""


class SessionService:
    """会话生命周期 + Agent 事件流 + 落库。runtime 由外部注入，不持有连接。"""

    def __init__(
        self,
        repository: SessionRepository,
        runtime: AgentPort,
        *,
        runs: KeyedLocks | None = None,
        on_complete: Callable[[str, str, str], None] | None = None,
        history_builder: Callable[[list[Message]], list[dict[str, Any]]] | None = None,
        model_resolver: Callable[[], tuple[Any, dict[str, Any]]] | None = None,
    ):
        self._principal = None
        self._repo = repository
        self._runtime = runtime
        self._runs = runs if runs is not None else DEFAULT_RUNS
        self._on_complete = on_complete
        self._history_builder = history_builder
        self._model_resolver = model_resolver

    def _model_for_run(self, query, history, reasoning=None):
        if self._model_resolver is None:
            return None
        model, capabilities = self._model_resolver()
        if reasoning and not capabilities["reasoning"]:
            raise ModelCapabilityError("当前模型不支持深度思考，请关闭深度思考或联系管理员切换模型")
        if not capabilities["images"] and (any(p.get("type") == "image_url" for p in query if isinstance(p, dict))
                                                or any(m.images for m in history)):
            raise ModelCapabilityError("当前模型不支持图片，当前问题或对话历史包含图片，请联系管理员切换模型或新建会话")
        return model

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

    def add_memory(self, user_id: str, content: str, category: str = "fact") -> Memory:
        return self._repo.add_memory(user_id, content, category)

    def update_memory(self, user_id: str, memory_id: str, content: str) -> Memory | None:
        return self._repo.update_memory(user_id, memory_id, content)

    def delete_memory(self, user_id: str, memory_id: str) -> bool:
        return self._repo.delete_memory(user_id, memory_id)

    # ---------- 已保存的笔记 ----------
    def create_note(self, user_id: str, title: str, content: str,
                    source_session_id: str | None = None) -> Note:
        return self._repo.create_note(user_id, title, content, source_session_id)

    def list_notes(self, user_id: str) -> list[Note]:
        return self._repo.list_notes(user_id)

    def get_note(self, user_id: str, note_id: str) -> Note | None:
        return self._repo.get_note(user_id, note_id)

    def update_note(self, user_id: str, note_id: str, *, title: str, content: str) -> Note | None:
        return self._repo.update_note(user_id, note_id, title=title, content=content)

    def delete_note(self, user_id: str, note_id: str) -> bool:
        return self._repo.delete_note(user_id, note_id)

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
            prefix = self._repo.get_messages(user_id, session_id)
            model = self._model_for_run(query, prefix, reasoning)
            question = self._repo.add_message(
                session_id, "user", text,
                images=image_urls if image_urls is not None else images,
            )
            if session.title == DEFAULT_SESSION_TITLE:
                self._repo.update_session_title(user_id, session_id, text[:_AUTOTITLE_MAX_LEN] or "图片消息")
            return RunStream(self._stream(
                session_id, query, max_turns=max_turns,
                reasoning=reasoning, user_id=user_id, question_id=question.id,
                history=prefix, context_revision=getattr(session, "context_revision", 0), model=model,
            ), lease)
        except BaseException:
            lease.release()
            raise

    def _build_history(self, messages: list[Message]) -> list[dict[str, Any]]:
        if self._history_builder is not None:
            return self._history_builder(messages)
        if any(m.images for m in messages):
            raise ValueError("恢复图片对话需要配置图片历史适配器")
        return [{"role": m.role, "content": [{"type": "text", "text": m.content}]} for m in messages]

    def regenerate(self, user_id: str, session_id: str, message_id: int) -> RunStream:
        if self._repo.get_session(user_id, session_id) is None:
            raise LookupError("会话不存在")
        lease = self._runs.acquire(session_id)
        try:
            session = self._repo.get_session(user_id, session_id)
            if session is None:
                raise LookupError("会话不存在")
            messages = self._repo.get_messages(user_id, session_id)
            answer = next((m for m in messages if m.id == message_id and m.role == "assistant"), None)
            if answer is None:
                raise LookupError("目标回复不存在")
            question_index = next((i for i, m in enumerate(messages)
                                   if m.id == answer.reply_to_message_id and m.role == "user" and m.id < answer.id), None)
            if question_index is None:
                raise ValueError("该回复无法关联原问题，不能重新生成")
            question = messages[question_index]
            query = self._build_history([question])[0]["content"]
            prefix = messages[:question_index]
            model = self._model_for_run(query, prefix)
            # 在响应开始前校验图片；不在模型调用中途才发现历史不可恢复。
            seed = self._build_history(prefix)
            return RunStream(self._stream(
                session_id, query, max_turns=None, user_id=user_id,
                question_id=question.id, history=prefix, context_revision=session.context_revision,
                replacement_id=answer.id, seed=seed, model=model,
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
        question_id: int,
        history: list[Message],
        context_revision: int,
        replacement_id: int | None = None,
        seed: list[dict[str, Any]] | None = None,
        model: Any = None,
    ) -> Iterator[dict[str, Any]]:
        started = time.perf_counter()
        pending_done = None
        sources = {}
        runtime_id = f"regenerate:{session_id}:{uuid4().hex}" if replacement_id is not None else session_id
        yield {
            "type": "run_started",
            "session_id": session_id,
            "user_message_id": question_id,
            "operation": "regenerate" if replacement_id is not None else "send",
            "message_id": replacement_id,
            "started_at": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            memory_lines = [m.content for m in self._repo.list_memories(user_id)] if user_id else []
            access = {"principal": self._principal} if self._principal is not None else {}
            if model is not None:
                access["model"] = model
            events = self._runtime.stream(
                query, session_id=runtime_id, max_turns=max_turns,
                reasoning=reasoning, memory=memory_lines, context_revision=context_revision,
                history=lambda: seed if seed is not None else self._build_history(history),
                **access,
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
                        if kind == "tool_finished" and event.get("status") == "completed":
                            normalized = normalize_sources(event.get("sources"), event.get("name", ""))
                            sources.update((source["id"], source) for source in normalized)
                            event = {**event, "sources": normalized}
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
            snapshots = list(sources.values())
            if replacement_id is None:
                saved = self._repo.complete_turn(
                    session_id, answer, token_usage=usage or None, sources=snapshots, reply_to_message_id=question_id,
                )
            else:
                saved = self._repo.replace_answer(
                    session_id, replacement_id, answer, token_usage=usage or None, sources=snapshots,
                )
                try:
                    self._runtime.delete_thread(session_id)
                except Exception:
                    logger.exception("清理旧主 checkpoint 失败，后续依靠上下文修订号重建")
            pending_done = {**pending_done, "final_answer": {
                **final, "message_id": saved.id, "reply_to_message_id": question_id, "sources": snapshots,
            }}
        except Exception as exc:
            logger.exception("会话 %s 本轮执行失败", session_id)
            yield {
                "type": "run_failed",
                "error_type": type(exc).__name__,
                "message": str(exc),
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
            }
            return
        finally:
            if replacement_id is not None:
                try:
                    self._runtime.delete_thread(runtime_id)
                except Exception:
                    logger.exception("临时重新生成 checkpoint 清理失败：%s", runtime_id)

        logger.info("会话 %s 完成一轮并保存回答，耗时 %.2fs", session_id, time.perf_counter() - started)
        # 后台任务登记失败也不能把已经提交的回答改判失败。
        if self._on_complete and user_id and replacement_id is None:
            user_text = "".join(
                p.get("text", "") for p in query
                if isinstance(p, dict) and p.get("type") == "text"
            )
            try:
                self._on_complete(user_id, user_text, answer)
            except Exception:
                logger.exception("后台记忆任务登记失败（回答已保存）")
        yield pending_done
