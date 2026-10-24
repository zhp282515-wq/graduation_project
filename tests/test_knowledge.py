import tempfile
import unittest
from pathlib import Path
from threading import RLock
from unittest.mock import Mock, patch

from agent.tools.base import ToolError
from agent.tools.knowledge_search import KnowledgeSearchTool
from knowledge.documents import KbDocumentRepository
from knowledge.server import KnowledgeService


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "example.md"
        self.path.write_text("正文", encoding="utf-8")
        self.service = KnowledgeService.__new__(KnowledgeService)
        self.service.registry_lock = RLock()
        self.service.store = Mock()
        self.service.embedder = Mock()
        self.service.parser = Mock()
        self.doc = {"file_md5": self.service._get_md5_hex(self.path), "file_name": "示例", "chunk_count": 1}
        self.service.store.get_doc_status.side_effect = [None, self.doc]
        self.service.store.insert_chunks.return_value = 1
        self.service.embedder.embed_texts.return_value = [[0.1]]
        self.items = [{"type": "text", "text": "真实正文", "page_idx": 0}]

    def load(self, **kwargs):
        return self.service.load_document(self.path, content_list=self.items, **kwargs)

    def test_success_returns_strongly_verified_count(self):
        result = self.load()
        self.assertEqual(result["chunk_count"], 1)
        self.assertEqual(result["inserted"], 1)
        for call in self.service.store.get_doc_status.call_args_list:
            self.assertEqual(call.kwargs["consistency_level"], "Strong")

    def test_empty_document_fails_before_embedding(self):
        self.items = []
        with self.assertRaisesRegex(ValueError, "有效切片"):
            self.load()
        self.service.embedder.embed_texts.assert_not_called()

    def test_embedding_count_mismatch_fails_before_insert(self):
        self.service.embedder.embed_texts.return_value = []
        with self.assertRaisesRegex(ValueError, "向量数"):
            self.load()
        self.service.store.insert_chunks.assert_not_called()

    def test_partial_insert_and_strong_verification_failure(self):
        self.service.store.insert_chunks.return_value = 0
        with self.assertRaisesRegex(RuntimeError, "仅写入"):
            self.load()
        for actual in (None, {**self.doc, "chunk_count": 0}, {**self.doc, "chunk_count": 2}):
            with self.subTest(actual=actual):
                self.service.store.get_doc_status.side_effect = [None, actual]
                self.service.store.insert_chunks.return_value = 1
                with self.assertRaisesRegex(RuntimeError, "校验失败"):
                    self.load()

    def test_failed_retry_deletes_only_same_hash_then_rebuilds(self):
        self.service.store.get_doc_status.side_effect = [self.doc]
        result = self.load(replace_existing=True)
        self.service.store.delete_by_md5.assert_called_once_with(self.doc["file_md5"])
        self.assertFalse(result["skipped"])
        self.service.store.drop_collection.assert_not_called()

    def test_existing_document_is_not_deleted(self):
        self.service.store.get_doc_status.side_effect = [self.doc, self.doc]
        self.assertTrue(self.load()["skipped"])
        self.service.store.delete_by_md5.assert_not_called()
        self.service.embedder.embed_texts.assert_not_called()

    def test_explicit_unavailable_tool_does_not_initialize(self):
        with patch("agent.tools.knowledge_search.KnowledgeService") as factory:
            tool = KnowledgeSearchTool(None)
            with self.assertRaisesRegex(ToolError, "暂不可用"):
                tool.run(query="问题")
            factory.assert_not_called()
            KnowledgeSearchTool()
            factory.assert_called_once()

    def test_initialization_failure_closes_already_created_resources(self):
        store, parser = Mock(), Mock()
        with patch("knowledge.server.MilvusVectorStore", return_value=store), \
             patch("knowledge.server.DashScopeEmbedding"), \
             patch("knowledge.server.MineruParser", return_value=parser), \
             patch("knowledge.server.DashScopeReranker", side_effect=RuntimeError("reranker init")):
            with self.assertRaises(RuntimeError):
                KnowledgeService()
        store.client.close.assert_called_once()
        parser.close.assert_called_once()


class RegistrySqlTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import MagicMock
        self.conn = MagicMock()
        self.cur = self.conn.cursor.return_value.__enter__.return_value
        self.repo = KbDocumentRepository(self.conn)

    def test_claim_is_conditional_and_returns_actual_result(self):
        for row, expected in ((None, False), (("hash",), True)):
            self.cur.fetchone.return_value = row
            result = self.repo.upsert_pending("hash", file_name="x", original_name="x",
                                              file_type="md", file_size=1, source_path="x")
            self.assertEqual(result, expected)
            sql = self.cur.execute.call_args.args[0]
            self.assertIn("WHERE kb_documents.status = 'failed'", sql)
            self.assertIn("RETURNING file_md5", sql)
            self.assertIn("chunk_count = NULL", sql)

    def test_sync_only_deletes_ready(self):
        for alive in (set(), {"present"}):
            self.repo.delete_missing(alive)
            self.assertIn("status = 'ready'", self.cur.execute.call_args.args[0])

    def test_sync_counts_each_actual_insert(self):
        counts = iter([1, 0, 1])
        def execute(*a):
            self.cur.rowcount = next(counts)
        self.cur.execute.side_effect = execute
        self.assertEqual(self.repo.upsert_ready_from_milvus([
            {"file_md5": "a"}, {"file_md5": "b"}, {"file_md5": "c"},
        ]), 2)

    def test_ready_rejects_zero_chunks(self):
        with self.assertRaises(ValueError):
            self.repo.mark_ready("hash", 0)
        self.cur.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
