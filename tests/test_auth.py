"""Real PostgreSQL integration tests; every row lives in a disposable schema."""
import json
import os
import threading
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import jwt
import psycopg
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from api import main
from auth.bootstrap import bootstrap
from auth.policy import ScopedKnowledge, allowed_documents, principal
from auth.repository import UserRepository
from auth.security import COOKIE, PASSWORDS, Settings
from agent.tools.knowledge_search import KnowledgeSearchTool
from knowledge.documents import KbDocumentRepository
from session.repository import PostgresSessionRepository

ORIGIN = 'http://127.0.0.1:5173'
PASSWORD = 'test-password-2026'
PUBLIC = 'a' * 32
PRIVATE = 'b' * 32


class AuthIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_dotenv()
        dsn = os.getenv('LANGGRAPH_POSTGRES_URI')
        if not dsn:
            raise unittest.SkipTest('LANGGRAPH_POSTGRES_URI is required for isolated integration tests')
        cls.schema = 'test_auth_' + uuid.uuid4().hex
        cls.root_conn = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
        cls.root_conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(cls.schema)))
        cls.pool = ConnectionPool(dsn, min_size=1,max_size=6,kwargs={
            'autocommit':True,'row_factory':dict_row,'options':f'-csearch_path={cls.schema}'})
        cls.pool.wait()
        cls.hashed = PASSWORDS.hash(PASSWORD)
        with cls.pool.connection() as conn:
            UserRepository(conn).setup()
            PostgresSessionRepository(conn).setup()
            KbDocumentRepository(conn).setup()

    @classmethod
    def tearDownClass(cls):
        cls.pool.close()
        cls.root_conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(cls.schema)))
        cls.root_conn.close()

    def setUp(self):
        self.overrides = main.app.dependency_overrides.copy()
        self.addCleanup(lambda: (main.app.dependency_overrides.clear(), main.app.dependency_overrides.update(self.overrides)))
        with self.pool.connection() as conn:
            conn.execute('TRUNCATE app_users,auth_attempts,upload_owners,sessions,messages,memories,saved_notes,kb_documents,app_migrations CASCADE')
            repo=UserRepository(conn)
            self.admin=repo.create('administrator',self.hashed,'admin')
            self.alice=repo.create('alice',self.hashed)
            self.bob=repo.create('bobby',self.hashed)
            for md5,name,visibility in [(PUBLIC,'公开文档','public'),(PRIVATE,'管理文档','admin')]:
                conn.execute("INSERT INTO kb_documents(file_md5,file_name,file_type,status,chunk_count,visibility) VALUES (%s,%s,'md','ready',1,%s)",(md5,name,visibility))
            self.session=PostgresSessionRepository(conn).create_session(self.alice['id'],'个人会话')
            conn.execute("INSERT INTO memories(id,user_id,content) VALUES ('private-memory',%s,'私人记忆')",(self.alice['id'],))
            conn.execute("INSERT INTO upload_owners(name,user_id) VALUES ('private.png',%s)",(self.alice['id'],))
        self.knowledge=Mock(registry_lock=threading.RLock())
        self.knowledge.list_chunks.return_value=[{'id':'public-chunk','text':'文档正文','chunk_index':0}]
        self.knowledge.list_documents.return_value=[{'file_md5':PUBLIC,'file_name':'公开文档','chunk_count':1},{'file_md5':PRIVATE,'file_name':'管理文档','chunk_count':1}]
        self.knowledge.store.collection='test_knowledge'
        self.knowledge.store.iter_all_chunks.return_value=iter([{'file_md5':PUBLIC,'id':'p'},{'file_md5':PRIVATE,'id':'s'}])
        main.app.dependency_overrides[main.get_knowledge]=lambda:self.knowledge
        main.app.state.pg_pool=self.pool
        main.app.state.auth=Settings('s'*48,False,frozenset([ORIGIN]))
        main.app.state.runtime=Mock()
        main.app.state.runs=main.KeyedLocks()
        main.app.state.starmaps={}
        main.app.state.starmap_lock=threading.RLock()
        self.client=TestClient(main.app)
        self.client.headers['origin']=ORIGIN
        self.addCleanup(self.client.close)

    def login(self, name, client=None):
        client=client or self.client
        response=client.post('/api/auth/login',json={'username':name,'password':PASSWORD},headers={'origin':ORIGIN})
        self.assertEqual(response.status_code,200,response.text)
        client.headers['x-csrf-token']=response.json()['csrf_token']
        return response

    def test_register_uses_argon2_cookie_and_never_accepts_role(self):
        response=self.client.post('/api/auth/register',json={'username':'new_user','password':PASSWORD,'role':'admin'})
        self.assertEqual(response.status_code,422)
        response=self.client.post('/api/auth/register',json={'username':'new_user','password':PASSWORD})
        self.assertEqual(response.status_code,201,response.text)
        self.assertEqual(response.json()['user']['role'],'user')
        self.assertNotIn('password_hash',response.text)
        self.assertIn('HttpOnly',response.headers['set-cookie'])
        self.assertIn('SameSite=lax',response.headers['set-cookie'])
        with self.pool.connection() as conn:
            hashed=UserRepository(conn).by_name('NEW_USER')['password_hash']
        self.assertTrue(hashed.startswith('$argon2id$'))
        self.assertTrue(PASSWORDS.verify(hashed,PASSWORD))
        self.assertEqual(self.client.post('/api/auth/register',json={'username':'NEW_USER','password':PASSWORD}).status_code,409)

    def test_login_logout_and_legacy_header_rejection(self):
        self.assertEqual(self.client.get('/api/sessions',headers={'x-user-id':self.alice['id']}).status_code,401)
        self.login('alice')
        self.assertEqual(self.client.get('/api/auth/me').json()['user']['id'],self.alice['id'])
        token=self.client.cookies.get(COOKIE)
        self.assertEqual(self.client.post('/api/auth/logout').status_code,200)
        self.client.cookies.set(COOKIE,token)
        self.assertEqual(self.client.get('/api/auth/me').status_code,401)

    def test_bad_credentials_and_rate_limit(self):
        for _ in range(5):
            self.assertEqual(self.client.post('/api/auth/login',json={'username':'alice','password':'wrong-password'}).status_code,401)
        self.assertEqual(self.client.post('/api/auth/login',json={'username':'alice','password':PASSWORD}).status_code,429)

    def test_expired_tampered_and_wrong_algorithm_tokens(self):
        self.login('alice')
        valid=self.client.cookies.get(COOKIE)
        claims=main.app.state.auth.decode(valid)
        for token in [valid[:-5]+'abcde',jwt.encode({**claims,'exp':1},'s'*48,algorithm='HS256'),jwt.encode(claims,'s'*48,algorithm='HS384')]:
            self.client.cookies.clear();self.client.cookies.set(COOKIE,token)
            self.assertEqual(self.client.get('/api/auth/me').status_code,401)

    def test_origin_and_csrf(self):
        self.assertEqual(self.client.post('/api/auth/login',json={'username':'alice','password':PASSWORD},headers={'origin':'https://untrusted.invalid'}).status_code,403)
        self.login('alice')
        self.assertEqual(self.client.post('/api/sessions',headers={'x-csrf-token':''}).status_code,403)
        self.assertEqual(self.client.post('/api/sessions',headers={'origin':'https://untrusted.invalid'}).status_code,403)
        self.assertEqual(self.client.post('/api/sessions').status_code,200)

    def test_personal_sessions_and_memory_are_isolated_for_other_user_and_admin(self):
        for name in ['bobby','administrator']:
            self.client.cookies.clear();self.login(name)
            self.assertEqual(self.client.get(f'/api/sessions/{self.session.id}/messages').status_code,404)
            self.assertEqual(self.client.get('/api/memories').json(),[])
            self.assertEqual(self.client.put('/api/memories/private-memory',json={'content':'篡改'}).status_code,404)
            self.assertEqual(self.client.delete('/api/memories/private-memory').status_code,404)
            self.assertEqual(self.client.post(f'/api/sessions/{self.session.id}/messages/123/regenerate').status_code,404)

    def test_manual_memory_create_is_trimmed_and_user_scoped(self):
        self.login('alice')
        created = self.client.post('/api/memories', json={'content': '  我的学号是 20210001  '})
        self.assertEqual(created.status_code, 201, created.text)
        body = created.json()
        self.assertEqual(body['content'], '我的学号是 20210001')
        self.assertEqual(body['category'], 'fact')
        self.assertEqual(self.client.post('/api/memories', json={'content': '   '}).status_code, 400)
        self.assertEqual(
            self.client.post('/api/memories', json={'content': 'x' * 201}).status_code, 400
        )

        mine = [m['id'] for m in self.client.get('/api/memories').json()]
        self.assertIn('private-memory', mine)
        self.assertIn(body['id'], mine)

        for name in ['bobby', 'administrator']:
            self.client.cookies.clear()
            self.login(name)
            self.assertNotIn(body['id'], [m['id'] for m in self.client.get('/api/memories').json()])
            self.assertEqual(self.client.put(f"/api/memories/{body['id']}", json={'content': '改'}).status_code, 404)
            self.assertEqual(self.client.delete(f"/api/memories/{body['id']}").status_code, 404)

        # 新建的记忆没有被别人改走
        self.client.cookies.clear()
        self.login('alice')
        remaining = {m['id']: m['content'] for m in self.client.get('/api/memories').json()}
        self.assertEqual(remaining.get(body['id']), '我的学号是 20210001')

    def test_document_lists_chunks_and_admin_management(self):
        self.login('alice')
        data=self.client.get('/api/knowledge/documents').json()
        self.assertEqual([d['file_md5'] for d in data['items']],[PUBLIC])
        self.assertEqual(data['total'],1)
        self.assertEqual(self.client.get('/api/knowledge/overview').json()['documents'],1)
        self.assertEqual(self.client.get(f'/api/knowledge/documents/{PRIVATE}/chunks').status_code,404)
        self.assertEqual(self.client.get(f'/api/knowledge/documents/{PUBLIC}/chunks').status_code,200)
        self.assertEqual(self.client.post('/api/knowledge/sync').status_code,403)
        self.assertEqual(self.client.get('/api/admin/users').status_code,403)
        self.assertEqual(self.client.post('/api/admin/knowledge/search',json={'query':'校园'}).status_code,403)
        self.client.cookies.clear();self.login('administrator')
        self.assertEqual(self.client.get('/api/knowledge/documents').json()['total'],2)
        self.assertEqual(self.client.get(f'/api/knowledge/documents/{PRIVATE}/chunks').status_code,200)
        self.assertEqual(self.client.patch(f'/api/knowledge/documents/{PRIVATE}/visibility',json={'visibility':'public'}).status_code,200)
        self.client.cookies.clear();self.login('alice')
        self.assertEqual(self.client.get('/api/knowledge/documents').json()['total'],2)

    def test_role_disable_reset_password_and_last_admin(self):
        self.login('administrator')
        self.assertEqual(self.client.patch(f"/api/admin/users/{self.admin['id']}",json={'role':'user'}).status_code,409)
        other=TestClient(main.app);self.addCleanup(other.close);other.headers['origin']=ORIGIN
        self.login('alice',other)
        self.assertEqual(self.client.patch(f"/api/admin/users/{self.alice['id']}",json={'role':'admin'}).status_code,200)
        self.assertEqual(other.get('/api/auth/me').status_code,401)
        self.login('alice',other)
        self.assertEqual(other.get('/api/admin/users').status_code,200)
        self.assertEqual(self.client.patch(f"/api/admin/users/{self.alice['id']}",json={'enabled':False}).status_code,200)
        self.assertEqual(other.get('/api/auth/me').status_code,401)
        self.assertEqual(self.client.post(f"/api/admin/users/{self.bob['id']}/reset-password",json={'password':PASSWORD}).status_code,200)
        self.login('bobby',other)
        self.assertTrue(other.get('/api/auth/me').json()['user']['must_change_password'])
        self.assertEqual(other.get('/api/sessions').status_code,403)
        self.assertEqual(other.post('/api/auth/password',json={'current_password':PASSWORD,'new_password':'changed-password-2026'}).status_code,200)
        self.assertEqual(other.get('/api/auth/me').status_code,401)

    def test_admin_delete_user_cascades_and_guards(self):
        self.login('administrator')
        # 不能注销自己
        self.assertEqual(self.client.delete(f"/api/admin/users/{self.admin['id']}").status_code,409)
        # 仓储层同样兜底：最后一名启用的管理员不能删
        with self.pool.connection() as conn:
            with self.assertRaises(ValueError):
                with conn.transaction():
                    UserRepository(conn).delete(self.admin['id'])
        # 普通用户可以被注销，并连带清掉会话、记忆、上传归属、笔记
        with self.pool.connection() as conn:
            conn.execute("INSERT INTO saved_notes(id,user_id,title,content) VALUES ('alice-note',%s,'笔记','正文')",(self.alice['id'],))
            repo=UserRepository(conn)
            other_admin=repo.create('second_admin',self.hashed,'admin')
        self.assertEqual(self.client.delete(f"/api/admin/users/{self.alice['id']}").status_code,200)
        self.assertEqual(self.client.delete(f"/api/admin/users/{self.alice['id']}").status_code,404)
        with self.pool.connection() as conn:
            for table,column in [('sessions','user_id'),('memories','user_id'),('saved_notes','user_id'),('upload_owners','user_id'),('auth_sessions','user_id')]:
                left=conn.execute(f'SELECT count(*) AS n FROM {table} WHERE {column}=%s',(self.alice['id'],)).fetchone()['n']
                self.assertEqual(left,0,f'{table} 未清理')
            self.assertIsNone(UserRepository(conn).by_id(self.alice['id']))
        # 另一位管理员的凭据仍然可用
        other=TestClient(main.app);self.addCleanup(other.close);other.headers['origin']=ORIGIN
        self.login('second_admin',other)
        self.assertEqual(other.get('/api/admin/users').status_code,200)
        # 只剩一名启用管理员时，注销另一位管理员要 409
        self.assertEqual(self.client.delete(f"/api/admin/users/{other_admin['id']}").status_code,200)

    def test_ai_search_filters_before_reranking_and_rechecks_results(self):
        self.knowledge.rerank_retriever.return_value=[
            {'text':'公开正文','score':1,'source':dict(file_md5=PUBLIC,file_name='公开文档',section_path='',page=None)},
            {'text':'机密正文','score':1,'source':dict(file_md5=PRIVATE,file_name='管理文档',section_path='',page=None)},
        ]
        tool=KnowledgeSearchTool(self.knowledge,pool=self.pool)
        for name,expected in [('alice',False),('administrator',True)]:
            self.client.cookies.clear();self.login(name)
            claims=main.app.state.auth.decode(self.client.cookies.get(COOKIE))
            with self.pool.connection() as conn: user=UserRepository(conn).by_name(name)
            token=principal.set({'id':user['id'],'_sid':claims['jti']})
            try: result=tool.run(query='校园资料')
            finally: principal.reset(token)
            expression=self.knowledge.rerank_retriever.call_args.kwargs['expression']
            self.assertEqual(PRIVATE in expression,expected)
            self.assertEqual('机密正文' in result.content,expected)
        with self.assertRaises(Exception):tool.run(query='校园资料')

    def test_admin_search_modes_validation_and_current_document_permissions(self):
        self.login('administrator')
        def search(query, mode, top_k, top_n, *, expression):
            self.assertEqual(query, '校园')
            self.assertIn(PUBLIC, expression)
            self.assertIn(PRIVATE, expression)
            return {'items': [
                {'text': '公开', 'score': 0.8, 'source': {'file_md5': PUBLIC}},
                {'text': '管理', 'score': 0.7, 'source': {'file_md5': PRIVATE}},
            ], 'candidate_file_md5s': [PUBLIC, PRIVATE],
                'score_type': {'vector': 'cosine', 'hybrid': 'rrf', 'hybrid_rerank': 'rerank'}[mode],
                'rerank_status': 'success' if mode == 'hybrid_rerank' else 'not_requested'}
        self.knowledge.debug_retriever.side_effect = search
        for mode, score in [('vector', 'cosine'), ('hybrid', 'rrf'), ('hybrid_rerank', 'rerank')]:
            result = self.client.post('/api/admin/knowledge/search', json={
                'query': ' 校园 ', 'mode': mode, 'top_k': 8, 'top_n': 3,
            })
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual((result.json()['mode'], result.json()['score_type']), (mode, score))
            self.assertEqual(result.json()['candidate_count'], 2)
            self.assertGreaterEqual(result.json()['elapsed_ms'], 0)
            self.knowledge.debug_retriever.assert_called_with('校园', mode, 8, 3,
                expression='file_md5 in '+json.dumps(sorted([PUBLIC, PRIVATE])))
        response = self.client.post('/api/admin/knowledge/search', json={'query': '校园'})
        self.assertEqual(response.json()['mode'], 'hybrid_rerank')
        self.assertEqual(self.knowledge.debug_retriever.call_args.args[2:], (20, 5))
        for body in [
            {'query': ' '}, {'query': 'x' * 1001}, {'query': '校园', 'mode': 'bad'},
            {'query': '校园', 'top_k': 0}, {'query': '校园', 'top_k': 51},
            {'query': '校园', 'top_n': 0}, {'query': '校园', 'top_n': 51},
            {'query': '校园', 'top_k': 3, 'top_n': 4},
            {'query': '校园', 'top_k': True}, {'query': '校园', 'top_n': 1.5},
        ]:
            self.assertEqual(self.client.post('/api/admin/knowledge/search', json=body).status_code, 422, body)

        def deleted_during_search(*args, **kwargs):
            result = search(*args, **kwargs)
            with self.pool.connection() as conn:
                conn.execute('DELETE FROM kb_documents WHERE file_md5=%s', (PRIVATE,))
            return result
        self.knowledge.debug_retriever.side_effect = deleted_during_search
        response = self.client.post('/api/admin/knowledge/search', json={'query': '校园'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['text'] for item in response.json()['items']], ['公开'])
        self.assertEqual(response.json()['candidate_count'], 1)

    def test_admin_search_rechecks_revoked_session(self):
        self.login('administrator')
        def revoke_during_search(*args, **kwargs):
            with self.pool.connection() as conn:
                UserRepository(conn).revoke(self.admin['id'])
            return {'items': [], 'candidate_file_md5s': [], 'score_type': 'rrf',
                    'rerank_status': 'not_requested'}
        self.knowledge.debug_retriever.side_effect = revoke_during_search
        response = self.client.post('/api/admin/knowledge/search', json={'query': '校园', 'mode': 'hybrid'})
        self.assertEqual(response.status_code, 401)

    def test_admin_search_with_no_accessible_documents_still_rechecks_session(self):
        self.login('administrator')
        with self.pool.connection() as conn:
            conn.execute('DELETE FROM kb_documents')
        response = self.client.post('/api/admin/knowledge/search', json={'query': '校园'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['candidate_count'], 0)
        self.assertEqual(response.json()['rerank_status'], 'not_run')
        self.knowledge.debug_retriever.assert_not_called()

        from unittest.mock import patch
        def revoke_before_empty_result(conn, user):
            UserRepository(conn).revoke(user['id'], user['_sid'])
            return set()
        with patch('api.main.allowed_documents', side_effect=revoke_before_empty_result):
            response = self.client.post('/api/admin/knowledge/search', json={'query': '校园'})
        self.assertEqual(response.status_code, 401)

    def test_starmap_facade_filters_rows_documents_and_cache_identity(self):
        self.login('alice')
        a=self.client.get('/api/auth/me').json()['user']
        with self.pool.connection() as conn: allowed=allowed_documents(conn,a)
        scoped=ScopedKnowledge(self.knowledge,allowed)
        self.assertEqual([r['file_md5'] for r in scoped.list_documents()],[PUBLIC])
        self.assertEqual([r['file_md5'] for r in scoped.iter_all_chunks(include_vector=True)],[PUBLIC])

    def test_private_images_are_protected_for_read_and_chat(self):
        self.login('alice')
        response=self.client.post('/api/upload',files={'file':('private.png',b'image-fixture','image/png')})
        self.assertEqual(response.status_code,200,response.text)
        image=response.json()
        path=main.UPLOAD_DIR / Path(image['url']).name
        self.addCleanup(lambda:path.unlink(missing_ok=True))
        own=self.client.get(image['url'])
        self.assertEqual(own.status_code,200)
        self.assertIn('no-store',own.headers['cache-control'])
        self.client.cookies.clear();self.login('bobby')
        self.assertEqual(self.client.get(image['url']).status_code,404)
        self.assertEqual(self.client.post('/api/chat',json={'session_id':'other','text':'读图片','images':[image['path']]}).status_code,404)
        self.client.cookies.clear();self.login('administrator')
        self.assertEqual(self.client.get(image['url']).status_code,404)

    def test_concurrent_last_admin_changes_preserve_one_active_admin(self):
        from concurrent.futures import ThreadPoolExecutor
        with self.pool.connection() as conn:
            second=UserRepository(conn).create('second_admin',self.hashed,'admin')
        def demote(user_id):
            with self.pool.connection() as conn:
                try:
                    with conn.transaction(): UserRepository(conn).update(user_id,role='user')
                    return True
                except ValueError:return False
        with ThreadPoolExecutor(2) as executor:
            results=list(executor.map(demote,[self.admin['id'],second['id']]))
        self.assertEqual(sorted(results),[False,True])
        with self.pool.connection() as conn:
            self.assertEqual(conn.execute("SELECT count(*) AS n FROM app_users WHERE role='admin' AND enabled").fetchone()['n'],1)

    def test_shared_agent_runtime_keeps_parallel_tool_access_in_request_context(self):
        from concurrent.futures import ThreadPoolExecutor
        from langgraph.checkpoint.memory import InMemorySaver
        from agent.runtime import AgentRuntime
        from models.base import ToolCall
        self.knowledge.rerank_retriever.return_value=[
            {'text':'公开正文','score':1,'source':dict(file_md5=PUBLIC,file_name='公开文档',section_path='',page=None)},
            {'text':'机密正文','score':1,'source':dict(file_md5=PRIVATE,file_name='管理文档',section_path='',page=None)},
        ]
        def model_stream(messages,**kwargs):
            if messages[-1].role=='tool':
                yield {'type':'text_delta','content':'已根据文档回答'}
                yield {'type':'done','finish_reason':'stop'}
            else:
                yield {'type':'tool_call','tool_call':ToolCall(id='knowledge-1',name='knowledge_search',arguments={'query':'校园'})}
                yield {'type':'done','finish_reason':'tool_calls'}
        model=Mock();model.reasoning_kwargs.return_value={};model.stream.side_effect=model_stream
        saver=InMemorySaver()
        runtime=AgentRuntime(model,[KnowledgeSearchTool(self.knowledge,pool=self.pool)],checkpointer=saver)
        identities=[]
        for name in ['alice','administrator']:
            self.client.cookies.clear();self.login(name)
            claims=main.app.state.auth.decode(self.client.cookies.get(COOKIE))
            identities.append({'id':claims['sub'],'_sid':claims['jti']})
        def run(item):
            index,identity=item
            events=list(runtime.stream([{'type':'text','text':'校园'}],session_id=f'thread-{index}',principal=identity))
            return next(e for e in events if e['type']=='tool_finished')['sources']
        with ThreadPoolExecutor(2) as executor:results=list(executor.map(run,enumerate(identities)))
        self.assertEqual(len(results[0]),1)
        self.assertEqual(len(results[1]),2)
        for index in range(2):
            snapshot=runtime.graph.get_state({'configurable':{'thread_id':f'thread-{index}'}})
            self.assertNotIn('principal',json.dumps(snapshot.metadata))
            self.assertNotIn(identities[index]['_sid'],repr(snapshot.values))

    def test_tool_drops_results_when_session_is_revoked_during_remote_retrieval(self):
        from agent.tools.base import ToolError
        self.login('administrator')
        claims=main.app.state.auth.decode(self.client.cookies.get(COOKIE))
        def retrieve(*args,**kwargs):
            with self.pool.connection() as conn: UserRepository(conn).revoke(self.admin['id'])
            return [{'text':'机密正文','score':1,'source':dict(file_md5=PRIVATE,file_name='管理文档',section_path='',page=None)}]
        self.knowledge.rerank_retriever.side_effect=retrieve
        token=principal.set({'id':self.admin['id'],'_sid':claims['jti']})
        try:
            with self.assertRaisesRegex(ToolError,'登录已失效'):
                KnowledgeSearchTool(self.knowledge,pool=self.pool).run(query='校园')
        finally: principal.reset(token)

    def test_bootstrap_migrates_once_without_overwriting_password(self):
        with self.pool.connection() as conn:
            conn.execute('TRUNCATE app_users,auth_sessions,upload_owners,app_migrations CASCADE')
            conn.execute("UPDATE sessions SET user_id='user_001'")
            conn.execute("UPDATE memories SET user_id='user_001'")
            conn.execute("INSERT INTO messages(session_id,role,images) VALUES (%s,'user','[\"/uploads/old.png\"]')",(self.session.id,))
            self.assertTrue(bootstrap(conn,'first_admin',PASSWORD))
            admin=UserRepository(conn).by_name('first_admin')
            self.assertEqual(conn.execute('SELECT user_id FROM sessions').fetchone()['user_id'],admin['id'])
            self.assertEqual(conn.execute('SELECT user_id FROM memories').fetchone()['user_id'],admin['id'])
            self.assertTrue(UserRepository(conn).owns_upload('old.png',admin['id']))
            self.assertFalse(bootstrap(conn,'another_admin','different-password'))
            self.assertTrue(PASSWORDS.verify(UserRepository(conn).by_name('first_admin')['password_hash'],PASSWORD))


if __name__=='__main__': unittest.main()
