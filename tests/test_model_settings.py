"""Model settings authorization and persistence in an isolated PostgreSQL schema."""
import json
import os
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

import psycopg
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from api import main
from auth.repository import UserRepository
from auth.security import PASSWORDS, Settings
from models.settings import ModelSettingsError, ModelSettingsRepository, resolve_model_selection
from agent.runtime import AgentRuntime
from session.repository import PostgresSessionRepository
from session.runs import KeyedLocks

ORIGIN = 'http://127.0.0.1:5173'
PASSWORD = 'settings-test-password'


class ModelSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dsn = os.getenv('LANGGRAPH_POSTGRES_URI')
        if not dsn:
            raise unittest.SkipTest('LANGGRAPH_POSTGRES_URI is required')
        cls.schema = 'test_model_settings_' + uuid.uuid4().hex
        cls.root = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
        cls.root.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(cls.schema)))
        cls.pool = ConnectionPool(dsn, min_size=1, max_size=3, kwargs={
            'autocommit': True, 'row_factory': dict_row, 'options': f'-csearch_path={cls.schema}'})
        cls.pool.wait()
        with cls.pool.connection() as conn:
            UserRepository(conn).setup()
            ModelSettingsRepository(conn).setup()
            PostgresSessionRepository(conn).setup()
            repo = UserRepository(conn)
            repo.create('settings_admin', PASSWORDS.hash(PASSWORD), 'admin')
            repo.create('settings_user', PASSWORDS.hash(PASSWORD), 'user')

    @classmethod
    def tearDownClass(cls):
        cls.pool.close()
        cls.root.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(cls.schema)))
        cls.root.close()

    def setUp(self):
        with self.pool.connection() as conn:
            conn.execute('DELETE FROM chat_model_settings')
        self.env = patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'deep-secret', 'DASHSCOPE_API_KEY': 'dash-secret', 'OPENAI_API_KEY': ''})
        self.env.start()
        self.addCleanup(self.env.stop)
        main.app.state.pg_pool = self.pool
        main.app.state.auth = Settings('s' * 48, False, frozenset([ORIGIN]))
        self.client = TestClient(main.app, headers={'origin': ORIGIN})
        self.addCleanup(self.client.close)

    def login(self, username):
        response = self.client.post('/api/auth/login', json={'username': username, 'password': PASSWORD})
        self.assertEqual(response.status_code, 200, response.text)
        self.client.headers['x-csrf-token'] = response.json()['csrf_token']

    def test_defaults_save_persist_and_no_secrets(self):
        self.login('settings_admin')
        response = self.client.get('/api/admin/model-settings')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['current'], {'provider': 'deepseek', 'model': 'deepseek-flash'})
        self.assertIsNone(body['current_error'])
        self.assertNotIn('deep-secret', json.dumps(body))
        self.assertFalse(next(p for p in body['providers'] if p['id'] == 'openai')['configured'])
        response = self.client.put('/api/admin/model-settings', json={'provider': 'dashscope', 'model': 'qwen3.8-flash'})
        self.assertEqual(response.status_code, 200, response.text)
        with self.pool.connection() as conn:
            self.assertEqual(ModelSettingsRepository(conn).get(), {'provider': 'dashscope', 'model': 'qwen3.8-flash'})
            self.assertTrue(resolve_model_selection(conn)['reasoning'])
        self.assertEqual(self.client.get('/api/admin/model-settings').json()['current']['provider'], 'dashscope')

    def test_invalid_changes_do_not_replace_previous_selection(self):
        self.login('settings_admin')
        for selection in ({'provider': 'openai', 'model': 'gpt-6-luna'},
                          {'provider': 'deepseek', 'model': 'missing'},
                          {'provider': 'unknown', 'model': 'missing'}):
            self.assertEqual(self.client.put('/api/admin/model-settings', json=selection).status_code, 400)
        with self.pool.connection() as conn:
            self.assertEqual(ModelSettingsRepository(conn).get(), {'provider': 'deepseek', 'model': 'deepseek-flash'})

    def test_saved_model_missing_key_or_removed_is_reported_without_fallback(self):
        self.login('settings_admin')
        with self.pool.connection() as conn:
            repo = ModelSettingsRepository(conn)
            repo.set('openai', 'gpt-6-luna')
            with self.assertRaisesRegex(ModelSettingsError, 'API Key'):
                resolve_model_selection(conn)
        self.assertIn('API Key', self.client.get('/api/admin/model-settings').json()['current_error'])
        with self.pool.connection() as conn:
            ModelSettingsRepository(conn).set('deepseek', 'removed-model')
            with self.assertRaisesRegex(ModelSettingsError, '模型'):
                resolve_model_selection(conn)
        self.assertIn('模型', self.client.get('/api/admin/model-settings').json()['current_error'])

    def test_save_rolls_back_if_response_cannot_be_prepared(self):
        self.login('settings_admin')
        with patch.object(main, 'settings_response', side_effect=ModelSettingsError('配置目录已更改')):
            response = self.client.put('/api/admin/model-settings', json={'provider': 'dashscope', 'model': 'qwen3.8-flash'})
        self.assertEqual(response.status_code, 400)
        with self.pool.connection() as conn:
            self.assertEqual(ModelSettingsRepository(conn).get(), {'provider': 'deepseek', 'model': 'deepseek-flash'})

    def test_admin_only_and_csrf_required(self):
        self.assertEqual(self.client.get('/api/admin/model-settings').status_code, 401)
        self.login('settings_user')
        self.assertEqual(self.client.get('/api/admin/model-settings').status_code, 403)
        self.assertEqual(self.client.put('/api/admin/model-settings', json={'provider': 'deepseek', 'model': 'deepseek-flash'}).status_code, 403)
        self.client.cookies.clear()
        self.login('settings_admin')
        self.client.headers['x-csrf-token'] = ''
        self.assertEqual(self.client.put('/api/admin/model-settings', json={'provider': 'deepseek', 'model': 'deepseek-flash'}).status_code, 403)

    def test_running_chat_retains_model_across_switch_and_next_chat_and_regenerate_use_new_selection(self):
        self.login('settings_admin')
        with self.pool.connection() as conn:
            admin = UserRepository(conn).by_name('settings_admin')
            session = PostgresSessionRepository(conn).create_session(admin['id'], '模型切换测试')

        entered, release = threading.Event(), threading.Event()
        calls = []

        class FakeProvider:
            def __init__(self, model):
                self.model = model

            def reasoning_kwargs(self, value=None):
                return {}

            def stream(self, messages, **kwargs):
                calls.append((self.model, [m.content for m in messages]))
                if self.model == 'deepseek-flash':
                    entered.set()
                    if not release.wait(5):
                        raise RuntimeError('test timed out')
                yield {'type': 'text_delta', 'content': self.model}
                yield {'type': 'done', 'finish_reason': 'stop'}

        main.app.state.runtime = AgentRuntime(model=None, tools=[], summary_model=FakeProvider('summary'))
        main.app.state.runs = KeyedLocks()
        main.app.state.memory_jobs = Mock()
        factories = {'DeepSeekProvider': FakeProvider, 'DashScopeProvider': FakeProvider, 'OpenAIProvider': FakeProvider}
        with patch.multiple(main, **factories), patch.dict(os.environ, {'OPENAI_API_KEY': 'open-secret'}), ThreadPoolExecutor(1) as workers:
            first = workers.submit(self.client.post, '/api/chat', json={'session_id': session.id, 'text': '第一问'})
            try:
                self.assertTrue(entered.wait(5), 'first request did not reach the provider')
                response = self.client.put('/api/admin/model-settings', json={'provider': 'dashscope', 'model': 'qwen3.8-flash'})
                self.assertEqual(response.status_code, 200, response.text)
                with self.pool.connection() as other_conn:
                    self.assertEqual(resolve_model_selection(other_conn)['model'], 'qwen3.8-flash')
            finally:
                release.set()
            response = first.result(10)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIn('deepseek-flash', response.text)
            response = self.client.post('/api/chat', json={'session_id': session.id, 'text': '第二问'})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIn('qwen3.8-flash', response.text)
            history = self.client.get(f'/api/sessions/{session.id}/messages').json()
            second_answer = history[-1]
            self.assertEqual(second_answer['role'], 'assistant')
            self.assertEqual(self.client.put('/api/admin/model-settings', json={'provider': 'openai', 'model': 'gpt-6-luna'}).status_code, 200)
            response = self.client.post(f"/api/sessions/{session.id}/messages/{second_answer['id']}/regenerate")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIn('gpt-6-luna', response.text)
            self.assertEqual([model for model, _ in calls], ['deepseek-flash', 'qwen3.8-flash', 'gpt-6-luna'])
            self.assertIn('第一问', json.dumps(calls[-1][1], ensure_ascii=False))

    def test_invalid_selection_fails_chat_without_blocking_account_or_settings(self):
        self.login('settings_admin')
        with self.pool.connection() as conn:
            admin = UserRepository(conn).by_name('settings_admin')
            session = PostgresSessionRepository(conn).create_session(admin['id'], '失效配置测试')
            ModelSettingsRepository(conn).set('openai', 'gpt-6-luna')
        main.app.state.runtime = Mock()
        main.app.state.runs = KeyedLocks()
        main.app.state.memory_jobs = Mock()
        response = self.client.post('/api/chat', json={'session_id': session.id, 'text': '不会保存'})
        self.assertEqual(response.status_code, 503, response.text)
        self.assertIn('API Key', response.json()['detail'])
        self.assertEqual(self.client.get('/api/auth/me').status_code, 200)
        self.assertIn('API Key', self.client.get('/api/admin/model-settings').json()['current_error'])
        with self.pool.connection() as conn:
            self.assertEqual(PostgresSessionRepository(conn).get_messages(admin['id'], session.id), [])


if __name__ == '__main__':
    unittest.main()
