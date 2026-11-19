import unittest
from datetime import date, datetime, timezone
from unittest.mock import Mock, patch
from api.usage import summarize
from scripts.seed_token_usage import require_development
from session.usage import Attribution, counts, metered_stream, observed
from models.base import ChatMessage


def row(day, role, amount):
    return dict(day=date.fromisoformat(day), user_id=role, role=role, total_tokens=amount,
                input_tokens=amount, output_tokens=0, calls=1)


class UsageTests(unittest.TestCase):
    def test_shanghai_midnight_month_and_period_edges(self):
        rows = [row('2026-09-02','user',80), row('2026-09-03','user',40),
                row('2026-09-25','admin',20), row('2026-09-26','user',10),
                row('2026-10-01','admin',4), row('2026-10-02','user',2)]
        before = datetime(2026,10,1,15,59,59,tzinfo=timezone.utc)
        after = datetime(2026,10,1,16,tzinfo=timezone.utc)
        self.assertEqual(summarize(rows,{},before,'all')['overview'][0]['total'],4)
        stats = summarize(rows,{},after,'all')
        self.assertEqual([c['total'] for c in stats['overview']], [2,16,76])
        self.assertEqual([c['previous'] for c in stats['overview']], [0,20,80])
        self.assertEqual(len(stats['trend']),30)
        self.assertIsNone(stats['trend'][1]['total'])
        for card in stats['overview']:
            self.assertEqual(card['user'] + card['admin'], card['total'])
            self.assertEqual(card['input'] + card['output'], card['total'])
        admin = summarize(rows,{'admin':3},after,'admin')['overview']
        self.assertEqual([c['total'] for c in admin],[0,4,24])
        self.assertEqual(admin[0]['previous'],3)

    def test_provider_usage_aliases_and_estimation(self):
        self.assertEqual(counts({'prompt_tokens':8,'completion_tokens':2},[],[]),(8,2,10,False))
        self.assertEqual(counts({'input_tokens':8,'total_tokens':10},[],[]),(8,2,10,False))
        self.assertEqual(counts({'total_tokens':15},[],[],True),(15,0,15,False))
        self.assertEqual(counts({},'校园','查询'),(2,2,4,True))
        self.assertEqual(counts({'total_tokens':17}, 'text', 'text'), (None,None,17,False))
        self.assertEqual(counts({'total_tokens':7,'input_tokens':9}, [], []), (None,None,7,False))

    def test_each_call_once_including_billable_failed_attempt(self):
        class Provider:
            model = 'test'
            @metered_stream
            def stream(self, messages, tools=None, mode='ok'):
                if mode == 'empty_error':
                    raise RuntimeError()
                observed({'total_tokens':2,'completion_tokens':1})
                observed({'total_tokens':8,'completion_tokens':3})
                if mode == 'billed_error':
                    raise RuntimeError()
                yield {'type':'text_delta','content':'result'}
                yield {'type':'done','token_usage':{'input_tokens':5,'output_tokens':3}}
        writer = Mock()
        actor = Attribution(writer,'u','admin','session')
        inputs = [ChatMessage(role='tool',content=[])]
        model = Provider()
        for mode in ('empty_error','billed_error'):
            with self.assertRaises(RuntimeError):
                actor.run(list,model.stream(inputs,[{}],mode))
        actor.run(list,model.stream(inputs,[{}]))
        self.assertEqual(writer.submit.call_count,2)
        for call in writer.submit.call_args_list:
            self.assertEqual(call.args[0][1:10],('u','admin','session','test',5,3,8,'tool_loop',False))
        list(model.stream(inputs))
        self.assertEqual(writer.submit.call_count,2)
        # Transport cleanup can close a suspended generator outside the request context.
        interrupted = model.stream(inputs, [{}])
        actor.run(next, interrupted)
        interrupted.close()
        self.assertEqual(writer.submit.call_count, 3)
        self.assertEqual(writer.submit.call_args.args[0][1:4], ('u', 'admin', 'session'))

    def test_graph_tool_and_summary_keep_attribution_across_stream_steps(self):
        from agent.runtime import AgentRuntime
        from agent.tools.base import BaseTool
        from models.deepseek.deepseek import DeepSeekProvider
        from tests.test_deepseek import chunk, stream_response
        from agent.summarizer import Summarizer

        class LocalTool(BaseTool):
            name, description = "lookup", "test lookup"
            parameters = {"type": "object", "properties": {}}
            def run(self, **kwargs):
                from session.usage import auxiliary
                auxiliary("embedding", {"input_tokens": 3}, "query")
                return "ok"

        provider = DeepSeekProvider("test", api_key="test")
        graph = AgentRuntime(provider,[LocalTool()])
        writer = Mock()
        actor = Attribution(writer, "alice", "user", "original-session")
        def events(delta, reason):
            return stream_response([chunk(delta, reason),
                {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9}}])
        with patch("models.deepseek.deepseek.httpx.stream", side_effect=[
            events({"tool_calls": [{"index":0,"id":"tc","function":{"name":"lookup","arguments":"{}"}}]}, "tool_calls"),
            events({"content":"answer"},"stop"), events({"content":"summary"},"stop")
        ]):
            run = graph.stream([{"type":"text","text":"question"}],session_id="original-session")
            while actor.run(next, run, None) is not None:
                pass
            actor.run(Summarizer(provider).run, messages=[], instruction="summarize")
        records = [c.args[0] for c in writer.submit.call_args_list]
        self.assertEqual([r[8] for r in records], ["chat","tool_loop","tool_loop","other"])
        self.assertTrue(all(r[1:4] == ("alice","user","original-session") for r in records))

    def test_seed_refuses_production_and_remote(self):
        good='host=localhost dbname=sample_dev'
        require_development(good,{'APP_ENV':'development'})
        for dsn, env in [(good,{}),(good,{'ENV':'production'}),('host=db dbname=sample_dev',{}),
                         ('host=localhost dbname=live',{})]:
            with self.assertRaises(SystemExit):
                require_development(dsn, {**({'APP_ENV':'development'} if dsn!=good or env else {}), **env})
