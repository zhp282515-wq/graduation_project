import asyncio
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from pathlib import Path
from threading import RLock
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import BackgroundTasks
from fastapi.testclient import TestClient
from starlette.requests import ClientDisconnect

from api import main
from api.streaming import ChatStreamingResponse
from session.runs import KeyedLocks, RunStream
from tests.test_sessions import DONE, repository


class FakePool:
    def __init__(self):
        self.active = 0
        self.open, self.wait, self.close = Mock(), Mock(), Mock()

    @contextmanager
    def connection(self):
        self.active += 1
        try:
            yield object()
        finally:
            self.active -= 1


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.pools = [FakePool(), FakePool()]
        self.repo = repository()
        self.repo.delete_session.return_value = True
        self.kb_repo = Mock()
        self.kb_repo.reconcile_after_restart.return_value = 0
        self.knowledge = Mock(registry_lock=RLock())
        self.runtime = Mock()
        self.runtime.stream.side_effect = lambda *a, **k: iter([DONE])
        self.jobs = Mock()
        self.stack.enter_context(patch.object(main, "ConnectionPool", side_effect=self.pools))
        self.stack.enter_context(patch.object(main, "PostgresSaver"))
        self.stack.enter_context(patch.object(main, "PostgresSessionRepository", return_value=self.repo))
        self.stack.enter_context(patch.object(main, "KbDocumentRepository", return_value=self.kb_repo))
        self.factory = self.stack.enter_context(patch.object(main, "KnowledgeService", return_value=self.knowledge))
        self.runtime_factory = self.stack.enter_context(patch.object(main, "AgentRuntime", return_value=self.runtime))
        self.stack.enter_context(patch.object(main, "DashScopeProvider"))
        self.stack.enter_context(patch.object(main, "MemoryExtractor"))
        self.stack.enter_context(patch.object(main, "MemoryJobs", return_value=self.jobs))
        self.stack.enter_context(patch.dict("os.environ", {"LANGGRAPH_POSTGRES_URI": "mock://tests"}))

    def client(self):
        return self.stack.enter_context(TestClient(main.app))

    def test_knowledge_failure_attempted_once_chat_works_management_503(self):
        self.factory.side_effect = RuntimeError("Milvus unavailable")
        client = self.client()
        response = client.get("/api/knowledge/documents")
        self.assertEqual(response.status_code, 503)
        response = client.post("/api/chat", headers={"x-user-id": "u"},
                               json={"session_id": "s", "text": "问题"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text.count('"type": "done"'), 1)
        self.factory.assert_called_once()
        self.assertIsNone(self.runtime_factory.call_args.kwargs["tools"][-1].service)

    def test_busy_send_and_delete_return_409_without_writing(self):
        client = self.client()
        with main.app.state.runs.acquire("s"):
            response = client.post("/api/chat", headers={"x-user-id": "u"},
                                   json={"session_id": "s", "text": "重复"})
            self.assertEqual(response.status_code, 409)
            self.repo.add_message.assert_not_called()
            response = client.delete("/api/sessions/s", headers={"x-user-id": "u"})
            self.assertEqual(response.status_code, 409)
        response = client.delete("/api/sessions/s", headers={"x-user-id": "u"})
        self.assertEqual(response.status_code, 200)

    def test_chat_returns_connection_before_background_job(self):
        client = self.client()
        def run(*args):
            self.assertEqual(self.pools[1].active, 0)
            self.assertFalse(main.app.state.runs._active)
        self.jobs.run.side_effect = run
        response = client.post("/api/chat", headers={"x-user-id": "u"},
                               json={"session_id": "s", "text": "问题"})
        self.assertEqual(response.status_code, 200)
        self.jobs.run.assert_called_once_with("u", "问题", "回答")

    def test_regeneration_and_history_expose_saved_ids_and_source_snapshots(self):
        from session.models import Message
        snapshots = [{"id": "web:1", "kind": "web", "url": "https://example.com/", "title": "官网", "text": "当时摘要"}]
        self.repo.get_messages.return_value = [
            Message(1, "s", "user", "原问题"),
            Message(2, "s", "assistant", "旧回答", sources=snapshots, reply_to_message_id=1),
            Message(3, "s", "user", "后续问题"),
        ]
        self.repo.replace_answer.return_value = Message(2, "s", "assistant", "回答", sources=[], reply_to_message_id=1)
        client = self.client()
        history = client.get("/api/sessions/s/messages", headers={"x-user-id": "u"}).json()
        self.assertEqual(history[1]["sources"], snapshots)
        self.assertEqual(history[1]["reply_to_message_id"], 1)
        response = client.post("/api/sessions/s/messages/2/regenerate", headers={"x-user-id": "u"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text.count('"type": "done"'), 1)
        self.assertIn('"user_message_id": 1', response.text)
        self.assertIn('"message_id": 2', response.text)
        self.repo.add_message.assert_not_called()
        self.jobs.run.assert_not_called()
        self.assertFalse(main.app.state.runs._active)
        self.assertEqual(self.pools[1].active, 0)

    def test_regeneration_http_validation_and_busy_requests_do_not_write(self):
        from session.models import Message
        self.repo.get_messages.return_value = [Message(1, "s", "user", "问题"), Message(2, "s", "assistant", "回答")]
        client = self.client()
        url = "/api/sessions/s/messages/2/regenerate"
        self.assertEqual(client.post(url).status_code, 401)
        with main.app.state.runs.acquire("s"):
            self.assertEqual(client.post(url, headers={"x-user-id": "u"}).status_code, 409)
        self.assertEqual(client.post(url, headers={"x-user-id": "u"}).status_code, 422)
        self.assertEqual(client.post(url.replace('/2/', '/1/'), headers={"x-user-id": "u"}).status_code, 404)
        self.repo.get_session.return_value = None
        self.assertEqual(client.post(url, headers={"x-user-id": "other"}).status_code, 404)
        self.repo.replace_answer.assert_not_called()
        self.repo.add_message.assert_not_called()
        self.runtime.stream.assert_not_called()
        self.assertFalse(main.app.state.runs._active)
        self.assertEqual(self.pools[1].active, 0)

    def test_document_chunks_expose_stable_primary_ids(self):
        self.kb_repo.get.return_value = dict(file_md5="hash", file_name="手册.pdf", file_type="pdf",
                                              status="ready", chunk_count=23)
        self.knowledge.list_chunks.return_value = [{"id": "stable-uuid", "chunk_index": 21, "text": "分片快照", "page": 3}]
        response = self.client().get("/api/knowledge/documents/hash/chunks?page=2&page_size=20")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["chunk_id"], "stable-uuid")
        self.knowledge.list_chunks.assert_called_once_with("hash", offset=20, limit=20)

    def test_concurrent_http_send_accepts_only_one_request(self):
        client = self.client()
        entered, release = threading.Event(), threading.Event()
        def stream(*a, **kw):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("test timeout")
            yield DONE
        self.runtime.stream.side_effect = stream
        def send():
            return client.post("/api/chat", headers={"x-user-id": "u"},
                               json={"session_id": "s", "text": "问题"})
        with ThreadPoolExecutor(1) as pool:
            first = pool.submit(send)
            try:
                self.assertTrue(entered.wait(2))
                self.assertEqual(send().status_code, 409)
                self.assertEqual(self.repo.add_message.call_count, 1)
            finally:
                release.set()
            self.assertEqual(first.result(3).status_code, 200)
        self.assertFalse(main.app.state.runs._active)

    def test_main_initialization_failure_releases_knowledge_and_both_pools(self):
        self.runtime_factory.side_effect = RuntimeError("model failure")
        with self.assertRaises(RuntimeError):
            with TestClient(main.app):
                pass
        self.knowledge.close.assert_called_once()
        for pool in self.pools:
            pool.close.assert_called_once()

    def test_pool_startup_failure_closes_both_pools(self):
        self.pools[0].wait.side_effect = RuntimeError("database unavailable")
        with self.assertRaises(RuntimeError):
            with TestClient(main.app):
                pass
        for pool in self.pools:
            pool.close.assert_called_once()
        self.factory.assert_not_called()

    def test_atomic_duplicate_upload_cleans_temporary_file(self):
        client = self.client()
        self.kb_repo.get.return_value = {"status": "ready"}
        self.kb_repo.upsert_pending.return_value = False
        with tempfile.TemporaryDirectory() as folder, patch.object(main, "KNOWLEDGE_UPLOAD_DIR", Path(folder)):
            response = client.post("/api/knowledge/upload", files={"file": ("x.md", b"content")})
            self.assertEqual(response.status_code, 409)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_failed_upload_claim_schedules_only_one_retry(self):
        client = self.client()
        self.kb_repo.get.return_value = {"status": "failed"}
        self.kb_repo.upsert_pending.side_effect = [True, False]
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(main, "KNOWLEDGE_UPLOAD_DIR", Path(folder)), \
             patch.object(main, "run_ingest_job") as job:
            first = client.post("/api/knowledge/upload", files={"file": ("x.md", b"content")})
            second = client.post("/api/knowledge/upload", files={"file": ("x.md", b"content")})
            self.assertEqual((first.status_code, second.status_code), (202, 409))
            job.assert_called_once()
            self.assertTrue(job.call_args.args[-1])
            self.assertEqual(len(list(Path(folder).iterdir())), 1)

    def test_upload_returns_request_connection_before_ingest_job(self):
        client = self.client()
        self.kb_repo.get.return_value = None
        self.kb_repo.upsert_pending.return_value = True
        def job(*a):
            self.assertEqual(self.pools[1].active, 0)
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(main, "KNOWLEDGE_UPLOAD_DIR", Path(folder)), \
             patch.object(main, "run_ingest_job", side_effect=job) as ingest:
            response = client.post("/api/knowledge/upload", files={"file": ("x.md", b"content")})
            self.assertEqual(response.status_code, 202)
            ingest.assert_called_once()


class IngestJobTests(unittest.TestCase):
    def setUp(self):
        self.pool = FakePool()
        self.repo = Mock()
        self.service = Mock(registry_lock=RLock())
        self.service.load_document.return_value = {"file_md5": "hash", "chunk_count": 2, "file_name": "文档"}
        patcher = patch.object(main, "KbDocumentRepository", return_value=self.repo)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_job(self, retry=False):
        main.run_ingest_job(self.pool, self.service, "hash", Path("example.pdf"), None, "example.pdf", retry)

    def test_ready_uses_verified_result_without_weak_query(self):
        self.run_job()
        self.repo.mark_ready.assert_called_once_with("hash", 2, file_name="文档")
        self.service.get_document.assert_not_called()

    def test_empty_or_failed_result_marks_failed_never_ready(self):
        self.service.load_document.return_value = {"chunk_count": 0}
        self.run_job()
        self.service.load_document.side_effect = RuntimeError("校验失败")
        self.run_job()
        self.repo.mark_ready.assert_not_called()
        self.assertEqual(self.repo.mark_failed.call_count, 2)

    def test_retry_rebuild_flag_passed(self):
        self.run_job(True)
        self.assertTrue(self.service.load_document.call_args.kwargs["replace_existing"])

    def test_sync_finishes_before_ready_transition(self):
        scanning, finish_scan, loaded = threading.Event(), threading.Event(), threading.Event()
        order = []
        def scan():
            scanning.set()
            if not finish_scan.wait(3):
                raise RuntimeError("test timeout")
            return []
        def load(*a, **kw):
            loaded.set()
            return {"chunk_count": 2, "file_name": "文档"}
        self.service.list_documents.side_effect = scan
        self.service.load_document.side_effect = load
        self.repo.delete_missing.side_effect = lambda *a: order.append("sync") or 0
        self.repo.mark_ready.side_effect = lambda *a, **k: order.append("ready")
        with ThreadPoolExecutor(2) as pool:
            syncing = pool.submit(main.sync_knowledge, self.service, self.repo)
            self.assertTrue(scanning.wait(2))
            job = pool.submit(self.run_job)
            try:
                self.assertTrue(loaded.wait(2))
                self.repo.mark_ready.assert_not_called()
            finally:
                finish_scan.set()
            syncing.result(3)
            job.result(3)
        self.assertEqual(order, ["sync", "ready"])


class StreamingResponseTests(unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_waits_for_worker_before_unlocking(self):
        entered, finish = threading.Event(), threading.Event()
        disconnected = asyncio.Event()
        locks = KeyedLocks()
        def events():
            entered.set()
            if not finish.wait(3):
                raise RuntimeError("test timeout")
            yield {"type": "text_delta"}
        run = RunStream(events(), locks.acquire("s"))
        def content():
            for event in run:
                yield str(event)
        cleanup = Mock()
        response = ChatStreamingResponse(content(), run=run, cleanup=cleanup)
        async def send(message):
            pass
        async def receive():
            await disconnected.wait()
            return {"type": "http.disconnect"}
        task = asyncio.create_task(response({"type": "http", "asgi": {"spec_version": "2.0"}}, receive, send))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            disconnected.set()
            await asyncio.sleep(0)
            from session.runs import SessionBusyError
            with self.assertRaises(SessionBusyError):
                locks.acquire("s")
            cleanup.assert_not_called()
        finally:
            finish.set()
            await asyncio.wait_for(task, 3)
        self.assertFalse(locks._active)
        cleanup.assert_called_once()

    async def test_header_failure_closes_unconsumed_run_and_connection(self):
        locks = KeyedLocks()
        def events():
            yield {}
        run = RunStream(events(), locks.acquire("s"))
        cleanup = Mock()
        response = ChatStreamingResponse(iter(()), run=run, cleanup=cleanup)
        async def send(message):
            raise OSError("connection lost before headers")
        with self.assertRaises(ClientDisconnect):
            await response({"type": "http", "asgi": {"spec_version": "2.4"}}, None, send)
        cleanup.assert_called_once()
        self.assertFalse(locks._active)

    async def test_final_body_and_cleanup_precede_slow_background(self):
        frames, order = [], []
        entered, release = asyncio.Event(), asyncio.Event()
        jobs = BackgroundTasks()
        async def background():
            order.append("background")
            entered.set()
            await release.wait()
        jobs.add_task(background)
        response = ChatStreamingResponse(iter(["data: done\n\n"]), run=Mock(),
                                         cleanup=lambda: order.append("cleanup"), background=jobs)
        async def send(message):
            frames.append(message)
        task = asyncio.create_task(response({"type": "http", "asgi": {"spec_version": "2.4"}}, None, send))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            self.assertFalse(frames[-1].get("more_body"))
            self.assertEqual(order, ["cleanup", "background"])
            self.assertFalse(task.done())
        finally:
            release.set()
            await task


if __name__ == "__main__":
    unittest.main()
