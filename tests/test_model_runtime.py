import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock, patch

from langgraph.checkpoint.memory import InMemorySaver

from agent.runtime import AgentRuntime
from models.base import ChatMessage, ToolCall
from models.dashscope.Qwen_model import _to_api_message as dashscope_message
from models.deepseek.deepseek import _to_api_message as deepseek_message
from models.openai.ChatGPT import OpenAIProvider
from session.models import Message
from session.runs import KeyedLocks
from session.service import ModelCapabilityError, SessionService
from tests.test_sessions import QUERY, DONE, repository


def model(name):
    result = Mock()
    result.reasoning_kwargs.return_value = {}
    result.stream.side_effect = lambda **kwargs: iter([
        {"type": "text_delta", "content": name},
        {"type": "done", "finish_reason": "stop"},
    ])
    return result


class ModelRuntimeTests(unittest.TestCase):
    def test_request_model_is_fixed_before_stream_and_regenerate(self):
        repo = repository()
        old, new = model('old'), model('new')
        selected = [old]
        runtime = Mock()
        runtime.stream.side_effect = lambda *args, **kwargs: iter([DONE])
        service = SessionService(repo, runtime, runs=KeyedLocks(),
            model_resolver=lambda: (selected[0], {"images": True, "reasoning": True}))
        first = service.send_message('u', 'first', QUERY, text='问题')
        selected[0] = new
        second = service.send_message('u', 'second', QUERY, text='问题')
        list(first)
        list(second)
        self.assertIs(runtime.stream.call_args_list[0].kwargs['model'], old)
        self.assertIs(runtime.stream.call_args_list[1].kwargs['model'], new)
        repo.get_messages.return_value = [Message(1, 's', 'user', '问题'),
                                          Message(2, 's', 'assistant', '回答', reply_to_message_id=1)]
        repo.replace_answer.return_value = SimpleNamespace(id=2)
        regeneration = service.regenerate('u', 's', 2)
        selected[0] = old
        list(regeneration)
        self.assertIs(runtime.stream.call_args.kwargs['model'], new)

    def test_capability_failures_do_not_write_or_call_model(self):
        repo, runtime, runs = repository(), Mock(), KeyedLocks()
        caps = {'images': False, 'reasoning': False}
        service = SessionService(repo, runtime, runs=runs, model_resolver=lambda: (model('x'), caps))
        with self.assertRaisesRegex(ModelCapabilityError, '深度思考'):
            service.send_message('u', 's', QUERY, text='问题', reasoning=True)
        with self.assertRaisesRegex(ModelCapabilityError, '图片'):
            service.send_message('u', 's', [{'type': 'image_url'}], text='问题')
        repo.get_messages.return_value = [Message(1, 's', 'user', '原问题', images=['/uploads/a.png'])]
        with self.assertRaisesRegex(ModelCapabilityError, '历史'):
            service.send_message('u', 's', QUERY, text='问题')
        repo.get_messages.return_value.append(Message(2, 's', 'assistant', '旧回答', reply_to_message_id=1))
        service._history_builder = lambda messages: [{'role': m.role, 'content': [{'type': 'image_url'}]} for m in messages]
        with self.assertRaisesRegex(ModelCapabilityError, '图片'):
            service.regenerate('u', 's', 2)
        repo.add_message.assert_not_called()
        repo.replace_answer.assert_not_called()
        runtime.stream.assert_not_called()
        self.assertFalse(runs._active)

    def test_graph_uses_request_model_and_preserves_messages_across_switch(self):
        first, second, summary = model('一'), model('二'), model('摘要')
        graph = AgentRuntime(None, [], checkpointer=InMemorySaver(), summary_model=summary)
        list(graph.stream(QUERY, session_id='thread', model=first))
        list(graph.stream([{'type': 'text', 'text': '下一问'}], session_id='thread', model=second))
        self.assertEqual(first.stream.call_count, 1)
        self.assertEqual(second.stream.call_count, 1)
        messages = second.stream.call_args.kwargs['messages']
        self.assertIn('问题', [m.content[0].get('text') for m in messages if m.role == 'user'])
        self.assertIn('一', [m.content[0].get('text') for m in messages if m.role == 'assistant'])

    def test_parallel_requests_do_not_share_provider_or_checkpoint_secrets(self):
        first, second = model('一'), model('二')
        first.provider_id, second.provider_id = 'deepseek', 'dashscope'
        first.api_key, second.api_key = 'fixture-secret-one', 'fixture-secret-two'
        barrier = threading.Barrier(2)
        for provider, answer in ((first, '一'), (second, '二')):
            def stream(*, messages, tools, answer=answer, **kwargs):
                barrier.wait(timeout=5)
                return iter([{'type':'text_delta', 'content':answer}, {'type':'done', 'finish_reason':'stop'}])
            provider.stream.side_effect = stream
        graph = AgentRuntime(None, [], checkpointer=InMemorySaver(), summary_model=model('摘要'))
        with ThreadPoolExecutor(2) as executor:
            futures = [executor.submit(lambda p=p, sid=sid: list(graph.stream(QUERY, session_id=sid, model=p)))
                       for p, sid in ((first, 'one'), (second, 'two'))]
            results = [future.result() for future in futures]
        self.assertEqual([next(e['content'] for e in events if e['type'] == 'text_delta') for events in results], ['一', '二'])
        for sid in ('one', 'two'):
            checkpoint = graph.graph.get_state({'configurable': {'thread_id': sid}})
            self.assertNotIn('fixture-secret', repr(checkpoint.values))
            self.assertNotIn('fixture-secret', repr(checkpoint.metadata))

    def test_old_reasoning_is_removed_but_current_tool_reasoning_is_preserved(self):
        from agent.nodes import create_nodes
        from agent.tools.registry import ToolRegistry
        from unittest.mock import patch
        current = model('结果')
        current.provider_id = 'dashscope'
        nodes = create_nodes(current, ToolRegistry([]), '', 10, Mock(), 100000)
        call = ToolCall(id='call', name='search', arguments={})
        history = [ChatMessage(role='user', content=[{'type':'text', 'text':'旧问题'}]),
                   ChatMessage(role='assistant', content=[{'type':'text', 'text':'旧回答'}], reasoning='旧思考', reasoning_provider='deepseek'),
                   ChatMessage(role='user', content=[{'type':'text', 'text':'新问题'}]),
                   ChatMessage(role='assistant', content=[], tool_calls=[call], reasoning='本轮思考')]
        with patch('agent.nodes.get_stream_writer', return_value=lambda event: None):
            nodes['llm_node']({'messages': history, 'reasoning': True})
        sent = current.stream.call_args.kwargs['messages']
        self.assertIsNone(sent[2].reasoning)
        self.assertEqual(sent[4].reasoning, '本轮思考')
        self.assertEqual(history[1].reasoning, '旧思考')
        self.assertEqual(dashscope_message(sent[4])['reasoning_content'], '本轮思考')
        self.assertEqual(deepseek_message(sent[4])['reasoning_content'], '本轮思考')
        current.provider_id = 'deepseek'
        with patch('agent.nodes.get_stream_writer', return_value=lambda event: None):
            nodes['llm_node']({'messages': history, 'reasoning': True})
        self.assertEqual(current.stream.call_args.kwargs['messages'][2].reasoning, '旧思考')

    def test_openai_boolean_reasoning_and_default_official_endpoint(self):
        with patch.dict('os.environ', {'OPENAI_BASE_URL': ''}):
            provider = OpenAIProvider('gpt-6-luna', api_key='fixture')
            self.assertEqual(provider.base_url, 'https://api.openai.com/v1')
        with patch.dict('os.environ', {'OPENAI_BASE_URL': 'https://proxy.example/v1/'}):
            self.assertEqual(OpenAIProvider('gpt-6-luna', api_key='fixture').base_url, 'https://proxy.example/v1')
        self.assertEqual(provider.reasoning_kwargs(True), {'reasoning_effort': 'high'})
        self.assertEqual(provider.reasoning_kwargs(False), {'reasoning_effort': 'none'})
        self.assertEqual(provider.reasoning_kwargs(None), {'reasoning_effort': 'none'})


if __name__ == '__main__':
    unittest.main()
