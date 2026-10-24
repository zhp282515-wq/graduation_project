import unittest
from unittest.mock import Mock

from agent.nodes import create_nodes
from agent.tools.registry import ToolRegistry
from models.base import ChatMessage, ChatResponse
from session.repository import PostgresSessionRepository


class GraphTests(unittest.TestCase):
    def test_compaction_failure_preserves_summary_and_window(self):
        summarizer = Mock()
        summarizer.run.side_effect = RuntimeError("summary model failure")
        nodes = create_nodes(Mock(), ToolRegistry([]), "", 10, summarizer, 10)
        messages = []
        for i in range(6):
            messages.extend([
                ChatMessage(role="user", content=[{"type": "text", "text": str(i)}]),
                ChatMessage(role="assistant", content=[{"type": "text", "text": "answer"}]),
            ])
        state = {"messages": messages, "summary": "旧摘要", "summary_upto": 0,
                 "last_response": ChatResponse(content="answer", finish_reason="stop", token_usage={"prompt_tokens": 100})}
        self.assertEqual(nodes["compact_node"](state), {})
        self.assertEqual(state["summary"], "旧摘要")
        self.assertEqual(state["summary_upto"], 0)
        summarizer.run.assert_called_once()

    def test_answer_and_touch_share_transaction_and_failure_exits_with_error(self):
        from unittest.mock import MagicMock
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.rowcount = 1
        repo = PostgresSessionRepository(conn)
        repo.complete_turn("s", "回答", token_usage={"total_tokens": 2})
        conn.transaction.assert_called_once()
        self.assertEqual(cur.execute.call_count, 2)
        conn.commit.assert_called_once()
        conn.commit.reset_mock()
        cur.execute.side_effect = [None, RuntimeError("touch failed")]
        with self.assertRaises(RuntimeError):
            repo.complete_turn("s", "回答")
        args = conn.transaction.return_value.__exit__.call_args.args
        self.assertIs(args[0], RuntimeError)
        conn.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
