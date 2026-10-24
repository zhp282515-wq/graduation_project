import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

from session.runs import KeyedLocks, SessionBusyError
from session.service import SessionService


DONE = {"type": "done", "final_answer": {"content": "回答", "total_tokens": 8}}
SAVED_DONE = {"type": "done", "final_answer": {**DONE["final_answer"], "message_id": 2, "reply_to_message_id": 1, "sources": []}}
QUERY = [{"type": "text", "text": "问题"}]


def repository():
    repo = Mock()
    repo.get_session.return_value = SimpleNamespace(title="已有会话", context_revision=0)
    repo.list_memories.return_value = []
    repo.get_messages.return_value = []
    repo.add_message.return_value = SimpleNamespace(id=1)
    repo.complete_turn.return_value = SimpleNamespace(id=2)
    return repo


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.repo = repository()
        self.runtime = Mock()
        self.runtime.stream.side_effect = lambda *a, **k: iter([DONE])
        self.runs = KeyedLocks()
        self.jobs = Mock()
        self.service = SessionService(self.repo, self.runtime, runs=self.runs, on_complete=self.jobs)

    def send(self, sid="s"):
        return self.service.send_message("u", sid, QUERY, text="问题")

    def test_shared_lock_rejects_before_second_user_message(self):
        stream = self.send()
        other_repo = repository()
        other = SessionService(other_repo, self.runtime, runs=self.runs)
        with self.assertRaises(SessionBusyError):
            other.send_message("u", "s", QUERY, text="重复")
        other_repo.add_message.assert_not_called()
        self.runtime.stream.assert_not_called()
        with self.assertRaises(SessionBusyError):
            self.service.delete_session("u", "s")
        stream.close()  # 首次迭代前也必须解锁。
        list(self.send())
        self.assertTrue(self.service.delete_session("u", "s"))

    def test_different_sessions_can_run_and_double_close_is_safe(self):
        first, second = self.send("a"), self.send("b")
        first.close()
        first.close()
        second.close()
        self.assertFalse(self.runs._active)

    def test_answer_committed_before_only_done_and_memory_only_scheduled(self):
        def runtime(*a, **kw):
            yield {"type": "text_delta", "content": "回答"}
            yield DONE
            self.repo.complete_turn.assert_not_called()
        self.runtime.stream.side_effect = runtime
        stream = self.send()
        self.assertEqual(next(stream)["type"], "run_started")
        self.assertEqual(next(stream)["type"], "text_delta")
        self.assertEqual(next(stream), SAVED_DONE)
        self.repo.complete_turn.assert_called_once_with("s", "回答", token_usage={"total_tokens": 8}, sources=[], reply_to_message_id=1)
        self.jobs.assert_called_once_with("u", "问题", "回答")
        list(stream)
        self.assertFalse(self.runs._active)

    def test_error_after_agent_done_never_emits_success_or_saves(self):
        def broken(*a, **kw):
            yield DONE
            raise RuntimeError("checkpoint 写入失败")
        self.runtime.stream.side_effect = broken
        events = list(self.send())
        self.assertEqual([e["type"] for e in events], ["run_started", "run_failed"])
        self.repo.complete_turn.assert_not_called()
        self.jobs.assert_not_called()
        self.runtime.stream.side_effect = lambda *a, **k: iter([DONE])
        self.assertEqual(list(self.send())[-1], SAVED_DONE)

    def test_missing_invalid_duplicate_and_explicit_failure_terminate_once(self):
        for events in ([], [{"type": "done", "final_answer": {"content": ""}}],
                       [DONE, DONE], [{"type": "run_failed", "message": "失败"}]):
            with self.subTest(events=events):
                self.runtime.stream.side_effect = lambda *a, **k: iter(events)
                actual = list(self.send())
                self.assertEqual([e["type"] for e in actual], ["run_started", "run_failed"])
        self.repo.complete_turn.assert_not_called()

    def test_save_and_memory_read_failure_release_lock(self):
        for operation in (self.repo.complete_turn, self.repo.list_memories):
            operation.side_effect = RuntimeError("数据库失败")
            self.assertEqual(list(self.send())[-1]["type"], "run_failed")
            self.assertFalse(self.runs._active)
            operation.side_effect = None
        self.repo.list_memories.return_value = []

    def test_close_partial_does_not_save_or_schedule(self):
        stream = self.send()
        next(stream)
        stream.close()
        self.repo.complete_turn.assert_not_called()
        self.jobs.assert_not_called()
        self.assertFalse(self.runs._active)

    def test_user_save_failure_releases_and_foreign_session_never_acquires(self):
        self.repo.add_message.side_effect = RuntimeError("写入失败")
        with self.assertRaises(RuntimeError):
            self.send()
        self.assertFalse(self.runs._active)
        self.repo.get_session.return_value = None
        with self.assertRaises(ValueError):
            self.send()
        self.assertFalse(self.runs._active)

    def test_close_waits_for_running_next(self):
        entered, finish, close_called = threading.Event(), threading.Event(), threading.Event()
        def blocked(*a, **kw):
            entered.set()
            if not finish.wait(3):
                raise RuntimeError("test timed out")
            yield {"type": "text_delta", "content": "片段"}
        self.runtime.stream.side_effect = blocked
        stream = self.send()
        next(stream)
        def close():
            close_called.set()
            stream.close()
        with ThreadPoolExecutor(2) as pool:
            step = pool.submit(next, stream)
            try:
                self.assertTrue(entered.wait(2))
                closing = pool.submit(close)
                self.assertTrue(close_called.wait(2))
                with self.assertRaises(SessionBusyError):
                    self.send()
            finally:
                finish.set()
            step.result(3)
            closing.result(3)
        self.assertFalse(self.runs._active)

    def test_background_registration_error_does_not_change_saved_success(self):
        self.jobs.side_effect = RuntimeError("登记失败")
        self.assertEqual(list(self.send())[-1], SAVED_DONE)


if __name__ == "__main__":
    unittest.main()
