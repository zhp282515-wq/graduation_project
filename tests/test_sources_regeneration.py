import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from agent.runtime import AgentRuntime
from knowledge.server import KnowledgeService
from models.base import ChatMessage, ChatResponse
from session.models import Message
from session.runs import KeyedLocks, SessionBusyError
from session.service import SessionService
from session.repository import PostgresSessionRepository, _to_message
from session.sources import normalize_sources
from tests.test_sessions import DONE, QUERY, repository
from utils.conversation import saved_history


KB = {"file_md5": "document-a", "file_name": "学生手册", "file_type": "pdf", "chunk_id": "chunk-a",
      "chunk_index": 21, "section_path": "学籍管理", "page": 3, "text": "当时检索到的完整分片"}
WEB = {"title": "学校官网", "url": "https://www.jxnu.edu.cn/article?id=1#section", "text": "网页摘要"}


class SourceTests(unittest.TestCase):
    def test_normalization_deduplicates_chunks_and_pages(self):
        self.assertEqual(len(normalize_sources([KB, KB], "knowledge_search")), 1)
        self.assertEqual(len(normalize_sources([WEB, {**WEB, "url": WEB["url"].split('#')[0]}], "websearch")), 1)
        source = normalize_sources([KB], "knowledge_search")[0]
        self.assertEqual((source["text"], source["page"], source["chunk_index"]), (KB["text"], 3, 21))

    def test_untrusted_links_and_non_pdf_pages_are_not_exposed(self):
        for url in ("javascript:alert(1)", "file:///secret", "https://user:password@example.com", "https://x:bad"):
            self.assertEqual(normalize_sources([{**WEB, "url": url}], "websearch"), [])
        for file_type in ("md", "doc", "docx", ""):
            self.assertIsNone(normalize_sources([{**KB, "file_type": file_type}], "knowledge_search")[0]["page"])
        self.assertIsNone(KnowledgeService._with_source({"text": "文字", "score": .5, "page": 1, "file_type": "md"})["source"]["page"])

    def test_successful_tool_snapshots_are_saved_with_answer(self):
        repo = repository()
        runtime = Mock()
        runtime.stream.return_value = iter([
            {"type": "tool_finished", "name": "knowledge_search", "status": "completed", "sources": [KB, KB]},
            {"type": "tool_finished", "name": "websearch", "status": "completed", "sources": [WEB]},
            {"type": "tool_finished", "name": "websearch", "status": "error", "sources": [{**WEB, "url": "https://invalid.example"}]},
            DONE,
        ])
        events = list(SessionService(repo, runtime).send_message("u", "s", QUERY, text="问题"))
        final = events[-1]["final_answer"]
        self.assertEqual(len(final["sources"]), 2)
        self.assertEqual(final["sources"], repo.complete_turn.call_args.kwargs["sources"])
        self.assertEqual((final["message_id"], final["reply_to_message_id"]), (2, 1))

    def test_multiple_searches_use_stable_ids_instead_of_local_tool_numbers(self):
        repo, runtime = repository(), Mock()
        runtime.stream.return_value = iter([
            {"type": "tool_finished", "name": "knowledge_search", "status": "completed", "sources": [{**KB, "index": 1}]},
            {"type": "tool_finished", "name": "knowledge_search", "status": "completed", "sources": [
                {**KB, "index": 2}, {**KB, "index": 1, "chunk_id": "another-chunk", "chunk_index": 22}]},
            {"type": "tool_finished", "name": "websearch", "status": "completed", "sources": [WEB]},
            {"type": "tool_finished", "name": "websearch", "status": "completed", "sources": [{**WEB, "url": WEB["url"].split('#')[0]}]},
            DONE,
        ])
        final = list(SessionService(repo, runtime).send_message("u", "s", QUERY, text="问题"))[-1]["final_answer"]
        self.assertEqual(len(final["sources"]), 3)
        self.assertEqual(len({source["id"] for source in final["sources"]}), 3)

    def test_images_are_restored_only_from_upload_directory(self):
        with tempfile.TemporaryDirectory() as folder, patch("utils.conversation.UPLOAD_DIR", Path(folder)):
            Path(folder, "image.png").write_bytes(b"test-image")
            message = Message(1, "s", "user", "问题", images=["/uploads/image.png"])
            self.assertTrue(saved_history([message])[0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))
            for image in ("/uploads/../secret.png", "/uploads/missing.png", "file:///private.png"):
                with self.assertRaises(ValueError):
                    saved_history([replace(message, images=[image])])


class RegenerationTests(unittest.TestCase):
    def setUp(self):
        self.messages = [
            Message(1, "s", "user", "第一问"), Message(2, "s", "assistant", "第一答", sources=[], reply_to_message_id=1),
            Message(3, "s", "user", "目标问题"), Message(4, "s", "assistant", "旧回答", sources=[KB], reply_to_message_id=3),
            Message(5, "s", "user", "后续问题"), Message(6, "s", "assistant", "后续回答", reply_to_message_id=5),
        ]
        self.repo = repository()
        self.session = SimpleNamespace(title="会话", context_revision=0)
        self.repo.get_session.return_value = self.session
        self.repo.get_messages.return_value = self.messages
        self.runtime = Mock()
        self.jobs = Mock()
        self.runs = KeyedLocks()
        self.service = SessionService(self.repo, self.runtime, runs=self.runs, on_complete=self.jobs)
        def commit(sid, mid, content, **kwargs):
            self.messages[3] = replace(self.messages[3], content=content, sources=kwargs["sources"])
            self.session.context_revision += 1
            return self.messages[3]
        self.repo.replace_answer.side_effect = commit
        self.runtime.stream.side_effect = lambda *a, **kw: iter([DONE])

    def test_replaces_only_target_after_success_and_seeds_only_earlier_context(self):
        def stream(query, **kwargs):
            self.assertEqual(query[0]["text"], "目标问题")
            self.assertEqual([m["content"][0]["text"] for m in kwargs["history"]()], ["第一问", "第一答"])
            self.assertTrue(kwargs["session_id"].startswith("regenerate:s:"))
            self.assertEqual(self.messages[3].content, "旧回答")
            yield DONE
        self.runtime.stream.side_effect = stream
        final = list(self.service.regenerate("u", "s", 4))[-1]
        self.assertEqual(final["final_answer"]["message_id"], 4)
        self.assertEqual([m.id for m in self.messages], [1, 2, 3, 4, 5, 6])
        self.assertEqual([m.content for m in self.messages[3:]], ["回答", "后续问题", "后续回答"])
        self.assertEqual(self.session.context_revision, 1)
        self.repo.add_message.assert_not_called()
        self.repo.complete_turn.assert_not_called()
        self.jobs.assert_not_called()
        self.assertEqual(self.runtime.delete_thread.call_args_list[0].args, ("s",))
        self.assertTrue(self.runtime.delete_thread.call_args_list[1].args[0].startswith("regenerate:s:"))

    def test_generation_or_database_failure_preserves_old_answer_and_sources(self):
        def broken(*a, **kw):
            yield DONE
            raise RuntimeError("模型失败")
        self.runtime.stream.side_effect = broken
        result = list(self.service.regenerate("u", "s", 4))
        self.assertEqual(result[-1]["type"], "run_failed")
        self.assertEqual((self.messages[3].content, self.messages[3].sources), ("旧回答", [KB]))
        self.repo.replace_answer.assert_not_called()
        self.runtime.stream.side_effect = lambda *a, **kw: iter([DONE])
        self.repo.replace_answer.side_effect = RuntimeError("数据库失败")
        self.assertEqual(list(self.service.regenerate("u", "s", 4))[-1]["type"], "run_failed")
        self.assertEqual(self.session.context_revision, 0)
        self.assertFalse(self.runs._active)

    def test_failed_main_checkpoint_cleanup_does_not_undo_committed_answer(self):
        def delete(thread_id):
            if thread_id == "s":
                raise RuntimeError("checkpoint unavailable")
        self.runtime.delete_thread.side_effect = delete
        self.assertEqual(list(self.service.regenerate("u", "s", 4))[-1]["type"], "done")
        self.assertEqual(self.session.context_revision, 1)

    def test_missing_foreign_or_unpaired_message_and_busy_requests(self):
        for message_id in (3, 999):
            with self.assertRaises(LookupError):
                self.service.regenerate("u", "s", message_id)
        self.messages[3].reply_to_message_id = None
        with self.assertRaises(ValueError):
            self.service.regenerate("u", "s", 4)
        with self.runs.acquire("s"):
            with self.assertRaises(SessionBusyError):
                self.service.regenerate("u", "s", 4)
        self.repo.get_session.return_value = None
        with self.assertRaises(LookupError):
            self.service.regenerate("other", "s", 4)

    def test_missing_images_fail_before_stream_and_release_lock(self):
        builder = Mock(side_effect=ValueError("原图片已不存在"))
        service = SessionService(self.repo, self.runtime, runs=self.runs, history_builder=builder)
        with self.assertRaisesRegex(ValueError, "原图片"):
            service.regenerate("u", "s", 4)
        self.runtime.stream.assert_not_called()
        self.repo.replace_answer.assert_not_called()
        self.assertFalse(self.runs._active)

    def test_image_question_regenerates_from_original_image_without_future_input(self):
        with tempfile.TemporaryDirectory() as folder, patch("utils.conversation.UPLOAD_DIR", Path(folder)):
            Path(folder, "original.png").write_bytes(b"original")
            self.messages[2].images = ["/uploads/original.png"]
            service = SessionService(self.repo, self.runtime, history_builder=saved_history)
            self.assertEqual(list(service.regenerate("u", "s", 4))[-1]["type"], "done")
            query = self.runtime.stream.call_args.args[0]
            self.assertEqual(query[0]["text"], "目标问题")
            self.assertEqual(query[1]["type"], "image_url")
            self.assertIn("b3JpZ2luYWw=", query[1]["image_url"]["url"])


class SourcePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.conn = MagicMock()
        self.cur = self.conn.cursor.return_value.__enter__.return_value
        self.cur.rowcount = 1
        self.row = dict(id=4, session_id="s", role="assistant", content="保存的回答", created_at=None,
                        tool_calls=None, tool_call_id=None, token_usage=None, images=None,
                        sources=[KB], reply_to_message_id=3)
        self.cur.fetchone.return_value = self.row
        self.repo = PostgresSessionRepository(self.conn)

    def test_new_answer_persists_snapshots_and_parent_in_business_transaction(self):
        saved = self.repo.complete_turn("s", "保存的回答", sources=[KB], reply_to_message_id=3)
        self.assertEqual((saved.sources, saved.reply_to_message_id), ([KB], 3))
        self.conn.transaction.assert_called_once()
        insert, touch = self.cur.execute.call_args_list
        self.assertEqual(insert.args[1][-2].obj, [KB])
        self.assertEqual(insert.args[1][-1], 3)
        self.assertIn("updated_at", touch.args[0])
        self.conn.commit.assert_called_once()

    def test_replacement_increments_revision_without_reordering_or_changing_parent(self):
        saved = self.repo.replace_answer("s", 4, "保存的回答", token_usage=None, sources=[KB])
        self.assertEqual(saved.id, 4)
        update, revision = self.cur.execute.call_args_list
        self.assertEqual(update.args[1][-2:], ("s", 4))
        self.assertNotIn("created_at =", update.args[0])
        self.assertNotIn("reply_to_message_id =", update.args[0])
        self.assertIn("context_revision = context_revision + 1", revision.args[0])
        self.conn.transaction.assert_called_once()

    def test_failed_session_update_does_not_commit_replacement(self):
        self.cur.rowcount = 0
        with self.assertRaises(ValueError):
            self.repo.replace_answer("s", 4, "保存的回答", token_usage=None, sources=[KB])
        self.conn.commit.assert_not_called()
        self.assertIs(self.conn.transaction.return_value.__exit__.call_args.args[0], ValueError)

    def test_legacy_null_and_explicit_empty_snapshots_remain_distinct(self):
        self.assertIsNone(_to_message({**self.row, "sources": None}).sources)
        self.assertEqual(_to_message({**self.row, "sources": []}).sources, [])


class RuntimeRevisionTests(unittest.TestCase):
    def test_revision_mismatch_rebuilds_messages_and_drops_old_summary(self):
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
        saver = InMemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=[ChatMessage, ChatResponse]))
        model = Mock()
        model.reasoning_kwargs.return_value = {}
        model.stream.side_effect = lambda **kw: iter([
            {"type": "text_delta", "content": "新回答"}, {"type": "done", "finish_reason": "stop"},
        ])
        runtime = AgentRuntime(model, [], checkpointer=saver)
        config = {"configurable": {"thread_id": "s"}}
        list(runtime.stream(QUERY, session_id="s"))
        runtime.graph.update_state(config, {"summary": "含旧回答的摘要", "summary_upto": 1})
        seed = Mock(return_value=[{"role": "assistant", "content": [{"type": "text", "text": "替换后的历史"}]}])
        list(runtime.stream(QUERY, session_id="s", context_revision=1, history=seed))
        values = runtime.graph.get_state(config).values
        self.assertEqual(values["context_revision"], 1)
        self.assertFalse(values.get("summary"))
        self.assertEqual(values["messages"][0].content[0]["text"], "替换后的历史")
        seed.assert_called_once()
        list(runtime.stream(QUERY, session_id="s", context_revision=1, history=seed))
        seed.assert_called_once()  # 相同修订号继续使用有效 checkpoint，不重复插入历史。
