import json
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

import httpx

from models.base import ChatMessage, ToolCall
from models.deepseek import DeepSeekProvider
from models.deepseek.deepseek import _iter_sse_data, _to_api_message


QUERY = [ChatMessage(role="user", content=[{"type": "text", "text": "南昌天气"}])]
TOOLS = [{"type": "function", "function": {"name": "weather", "parameters": {"type": "object"}}}]
USAGE = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "prompt_cache_hit_tokens": 3}


def chunk(delta=None, finish_reason=None, **extra):
    return {"choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish_reason}], **extra}


@contextmanager
def stream_response(events, *, done=True, status=200):
    body = ": keep-alive\n\n" + "".join(
        f"data: {json.dumps(event, ensure_ascii=False)}\n\n" for event in events
    )
    if done:
        body += "data: [DONE]\n\n"
    yield httpx.Response(status, text=body)


class DeepSeekTests(unittest.TestCase):
    def setUp(self):
        self.model = DeepSeekProvider(model="deepseek-flash", api_key="test-key")

    def test_configuration_and_reasoning_switch(self):
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "env-key"}):
            self.assertEqual(DeepSeekProvider("deepseek-flash").api_key, "env-key")
            self.assertEqual(DeepSeekProvider("deepseek-flash", api_key="explicit").api_key, "explicit")
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": ""}):
            with self.assertRaisesRegex(ValueError, "DEEPSEEK_API_KEY"):
                DeepSeekProvider("deepseek-flash")
        self.assertEqual(self.model.reasoning_kwargs(), {"enable_thinking": False})
        self.assertEqual(self.model.reasoning_kwargs(True), {"enable_thinking": True})
        self.assertEqual(self.model.reasoning_kwargs(False), {"enable_thinking": False})

    def test_message_conversion_preserves_tools_and_reasoning(self):
        message = ChatMessage(
            role="assistant", content=[], reasoning="需要查询天气",
            tool_calls=[ToolCall(id="call-1", name="weather", arguments={"city": "南昌"})],
        )
        restored = ChatMessage.model_validate_json(message.model_dump_json())
        converted = _to_api_message(restored)
        self.assertEqual(converted["content"], "")
        self.assertEqual(converted["reasoning_content"], "需要查询天气")
        self.assertEqual(json.loads(converted["tool_calls"][0]["function"]["arguments"]), {"city": "南昌"})
        tool = ChatMessage(role="tool", tool_call_id="call-1", content=[{"type": "text", "text": "晴"}])
        self.assertEqual(_to_api_message(tool), {"role": "tool", "content": "晴", "tool_call_id": "call-1"})
        legacy = ChatMessage.model_validate({"role": "assistant", "content": []})
        self.assertNotIn("reasoning_content", _to_api_message(legacy))

    def test_user_images_remain_content_parts(self):
        parts = [{"type": "text", "text": "识图"}, {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}}]
        self.assertEqual(_to_api_message(ChatMessage(role="user", content=parts))["content"], parts)
        with self.assertRaisesRegex(ValueError, "只支持文本"):
            _to_api_message(ChatMessage(role="system", content=parts))

    @patch("models.deepseek.deepseek.httpx.post")
    def test_invoke_request_and_response(self, post):
        post.return_value = httpx.Response(200, json={
            "choices": [{"message": {"content": "南昌晴", "reasoning_content": "已查询"}, "finish_reason": "stop"}],
            "usage": USAGE,
        })
        self.model.base_url = "https://example.com/v1"
        response = self.model.invoke(QUERY, timeout=12, max_tokens=100, temperature=0.4)
        self.assertEqual((response.content, response.reasoning, response.finish_reason), ("南昌晴", "已查询", "stop"))
        self.assertEqual(response.token_usage, USAGE)
        self.assertEqual(post.call_args.args, ("https://example.com/v1/chat/completions",))
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["timeout"], 12)
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(kwargs["json"]["messages"], [{"role": "user", "content": "南昌天气"}])
        self.assertEqual(kwargs["json"]["thinking"], {"type": "disabled"})
        self.assertEqual(kwargs["json"]["temperature"], 0.4)
        self.assertEqual(kwargs["json"]["max_tokens"], 100)
        self.assertNotIn("tools", kwargs["json"])

    @patch("models.deepseek.deepseek.httpx.post")
    def test_invoke_tools_thinking_and_invalid_arguments(self, post):
        for raw in ('{"city":"南昌"}', '{"city":', '[]'):
            with self.subTest(raw=raw):
                post.return_value = httpx.Response(200, json={"choices": [{
                    "message": {"content": None, "tool_calls": [{"id": "call-1", "function": {"name": "weather", "arguments": raw}}]},
                    "finish_reason": "tool_calls",
                }]})
                response = self.model.invoke(QUERY, TOOLS, enable_thinking=True, reasoning_effort="high")
                self.assertEqual(response.content, "")
                call = response.tool_calls[0]
                self.assertEqual(call.name, "weather")
                self.assertEqual(call.parse_error is None, raw.startswith('{"city":"'))
                payload = post.call_args.kwargs["json"]
                self.assertEqual(payload["thinking"], {"type": "enabled"})
                self.assertEqual(payload["reasoning_effort"], "high")
                self.assertEqual(payload["tools"], TOOLS)
                self.assertNotIn("temperature", payload)

    @patch("models.deepseek.deepseek.httpx.post")
    def test_invoke_errors(self, post):
        cases = [
            (httpx.Response(401, text="unauthorized"), "401"),
            (httpx.Response(200, text="not-json"), "JSON"),
            (httpx.Response(200, json=[]), "JSON 对象"),
            (httpx.Response(200, json={"error": {"message": "余额不足"}}), "余额不足"),
            (httpx.Response(200, json={"choices": []}), "choices"),
            (httpx.Response(200, json={"choices": [{}]}), "message"),
        ]
        for response, error in cases:
            with self.subTest(error=error):
                post.return_value = response
                with self.assertRaisesRegex(RuntimeError, error):
                    self.model.invoke(QUERY)

    @patch("models.deepseek.deepseek.httpx.stream")
    def test_stream_text_reasoning_and_separate_usage(self, stream):
        stream.return_value = stream_response([
            chunk({"role": "assistant", "reasoning_content": "先查询"}),
            chunk({"content": "南昌"}), chunk({"content": "晴"}),
            chunk(finish_reason="stop"), {"choices": [], "usage": USAGE},
        ])
        events = list(self.model.stream(QUERY, enable_thinking=True))
        self.assertEqual([event["type"] for event in events], ["reasoning_delta", "text_delta", "text_delta", "done"])
        self.assertEqual(events[-1], {"type": "done", "finish_reason": "stop", "token_usage": USAGE})
        payload = stream.call_args.kwargs["json"]
        self.assertTrue(payload["stream"])
        self.assertEqual(payload["stream_options"], {"include_usage": True})
        self.assertEqual(payload["thinking"], {"type": "enabled"})

    @patch("models.deepseek.deepseek.httpx.stream")
    def test_stream_reassembles_interleaved_tools_in_index_order(self, stream):
        stream.return_value = stream_response([
            chunk({"tool_calls": [
                {"index": 1, "id": "call-2", "function": {"name": "clock", "arguments": "{"}},
                {"index": 0, "id": "call-1", "function": {"name": "wea", "arguments": '{"ci'}},
            ]}),
            chunk({"tool_calls": [
                {"index": 0, "function": {"name": "ther", "arguments": 'ty":"南昌"}'}},
                {"index": 1, "function": {"arguments": "}"}},
            ]}),
            chunk(finish_reason="tool_calls", usage=USAGE),
        ])
        events = list(self.model.stream(QUERY, TOOLS))
        calls = [event["tool_call"] for event in events if event["type"] == "tool_call"]
        self.assertEqual([(call.id, call.name, call.arguments) for call in calls], [
            ("call-1", "weather", {"city": "南昌"}), ("call-2", "clock", {}),
        ])
        self.assertEqual(events[-1]["token_usage"], USAGE)

    def test_sse_comments_multiline_and_unterminated_last_event(self):
        response = httpx.Response(200, text=': heartbeat\nevent: message\ndata: {"choices":\ndata: []}\n\ndata: [DONE]')
        self.assertEqual(list(_iter_sse_data(response)), ['{"choices":\n[]}', '[DONE]'])

    @patch("models.deepseek.deepseek.httpx.stream")
    def test_stream_accepts_finish_reason_without_done_sentinel(self, stream):
        stream.return_value = stream_response([chunk({"content": "回答"}, "stop", usage=USAGE)], done=False)
        self.assertEqual(list(self.model.stream(QUERY))[-1]["finish_reason"], "stop")

    @patch("models.deepseek.deepseek.httpx.stream")
    def test_stream_never_dispatches_truncated_tool_calls(self, stream):
        for reason in (None, "length", "content_filter", "insufficient_system_resource"):
            with self.subTest(reason=reason):
                stream.return_value = stream_response([chunk({"tool_calls": [{
                    "index": 0, "id": "call-1", "function": {"name": "weather", "arguments": '{"city":'},
                }]}, reason)])
                iterator = self.model.stream(QUERY, TOOLS)
                if reason is None:
                    with self.assertRaisesRegex(RuntimeError, "finish_reason"):
                        list(iterator)
                else:
                    self.assertEqual([event["type"] for event in iterator], ["done"])

    @patch("models.deepseek.deepseek.httpx.stream")
    def test_stream_errors(self, stream):
        for data, error in [
            ({"error": {"message": "服务不可用"}}, "服务不可用"),
            ({"choices": "invalid"}, "choices"),
            (chunk({"tool_calls": [{"function": {"arguments": "{}"}}]}), "index"),
            (chunk(finish_reason="tool_calls"), "没有工具调用"),
        ]:
            with self.subTest(error=error):
                stream.return_value = stream_response([data])
                with self.assertRaisesRegex(RuntimeError, error):
                    list(self.model.stream(QUERY))
        for status, body, error in [(429, "限流", "429"), (200, "data: invalid\n\n", "JSON")]:
            with self.subTest(error=error):
                manager = Mock()
                manager.__enter__ = Mock(return_value=httpx.Response(status, text=body))
                manager.__exit__ = Mock(return_value=False)
                stream.return_value = manager
                with self.assertRaisesRegex(RuntimeError, error):
                    list(self.model.stream(QUERY))

    @patch("models.deepseek.deepseek.httpx.post")
    def test_invalid_effort_fails_before_request(self, post):
        with self.assertRaisesRegex(ValueError, "reasoning_effort"):
            self.model.invoke(QUERY, enable_thinking=True, reasoning_effort="invalid")
        post.assert_not_called()


class DeepSeekAgentTests(unittest.TestCase):
    @patch("models.deepseek.deepseek.httpx.stream")
    def test_agent_replays_reasoning_after_tool_result(self, stream):
        from agent.nodes import create_nodes
        from agent.tools.registry import ToolRegistry

        stream.side_effect = [
            stream_response([
                chunk({"reasoning_content": "查询南昌天气"}),
                chunk({"tool_calls": [{"index": 0, "id": "call-1", "function": {"name": "weather", "arguments": "{}"}}]}, "tool_calls"),
            ]),
            stream_response([chunk({"content": "南昌晴"}, "stop")]),
        ]
        registry = ToolRegistry([])
        registry.get_schemas = Mock(return_value=TOOLS)
        nodes = create_nodes(DeepSeekProvider("deepseek-flash", api_key="test-key"), registry, "", 10, Mock(), 10000)
        with patch("agent.nodes.get_stream_writer", return_value=Mock()):
            first = nodes["llm_node"]({"messages": QUERY, "reasoning": True})
            assistant = ChatMessage.model_validate_json(first["messages"][0].model_dump_json())
            self.assertEqual(assistant.reasoning, "查询南昌天气")
            tool = ChatMessage(role="tool", tool_call_id="call-1", content=[{"type": "text", "text": "晴"}])
            second = nodes["llm_node"]({"messages": [*QUERY, assistant, tool], "reasoning": True})
        self.assertEqual(second["last_response"].content, "南昌晴")
        replay = stream.call_args.kwargs["json"]["messages"][-2]
        self.assertEqual(replay["reasoning_content"], "查询南昌天气")
        self.assertEqual(replay["tool_calls"][0]["id"], "call-1")


if __name__ == "__main__":
    unittest.main()
