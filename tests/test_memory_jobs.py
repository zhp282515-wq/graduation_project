import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

from session.memory_jobs import MemoryJobs


class Pool:
    def __init__(self):
        self.borrowed = 0

    @contextmanager
    def connection(self):
        self.borrowed += 1
        try:
            yield self
        finally:
            self.borrowed -= 1


class MemoryJobTests(unittest.TestCase):
    def setUp(self):
        self.pool = Pool()
        self.memories = []
        self.repo = Mock()
        self.repo.list_memories.side_effect = lambda uid: [SimpleNamespace(content=x) for x in self.memories]
        self.repo.add_memory.side_effect = lambda uid, content, category: self.memories.append(content)
        self.extractor = Mock()
        self.worker = MemoryJobs(self.pool, self.extractor)
        patcher = patch("session.memory_jobs.PostgresSessionRepository", return_value=self.repo)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_model_runs_without_connection_and_duplicates_are_skipped(self):
        def extract(**kwargs):
            self.assertEqual(self.pool.borrowed, 0)
            return [{"content": "偏好", "category": "preference"}] * 2
        self.extractor.extract.side_effect = extract
        self.worker.run("u", "喜欢", "回答")
        self.worker.run("u", "喜欢", "回答")
        self.assertEqual(self.memories, ["偏好"])
        self.assertEqual(self.pool.borrowed, 0)

    def test_extraction_failure_does_not_escape(self):
        self.extractor.extract.side_effect = RuntimeError("API unavailable")
        self.worker.run("u", "输入", "回答")
        self.repo.add_memory.assert_not_called()
        self.assertFalse(self.worker._users._active)
        self.assertEqual(self.pool.borrowed, 0)

    def test_write_rechecks_memories_added_during_model_call(self):
        def extract(**kwargs):
            self.memories.append("新增")
            return [{"content": "新增", "category": "fact"}]
        self.extractor.extract.side_effect = extract
        self.worker.run("u", "输入", "回答")
        self.repo.add_memory.assert_not_called()

    def test_same_user_jobs_are_serial(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def extract(**kwargs):
            calls.append(kwargs["known"])
            if len(calls) == 1:
                entered.set()
                if not release.wait(3):
                    raise RuntimeError("test timeout")
            return [{"content": "偏好", "category": "fact"}]
        self.extractor.extract.side_effect = extract
        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(self.worker.run, "u", "输入", "回答")
            self.assertTrue(entered.wait(2))
            second = pool.submit(self.worker.run, "u", "输入", "回答")
            release.set()
            first.result(3)
            second.result(3)
        self.assertEqual(calls, [[], ["偏好"]])
        self.assertEqual(self.memories, ["偏好"])


if __name__ == "__main__":
    unittest.main()
