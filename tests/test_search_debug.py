"""管理员调试检索：真实服务编排，不依赖外部模型或 Milvus。"""
import unittest
from unittest.mock import Mock

from knowledge.server import KnowledgeService


class SearchDebugTests(unittest.TestCase):
    def setUp(self):
        self.service = KnowledgeService.__new__(KnowledgeService)
        self.service.store = Mock()
        self.service.embedder = Mock()
        self.service.reranker = Mock()
        self.service.embedder.embed_query.return_value = [0.2, 0.3]
        self.hits = [
            {'id': 'a', 'text': '一', 'score': 0.04, 'file_md5': 'public'},
            {'id': 'b', 'text': '二', 'score': 0.03, 'file_md5': 'admin'},
            {'id': 'c', 'text': '三', 'score': 0.001, 'file_md5': 'public'},
        ]
        self.service.store.search.return_value = self.hits
        self.service.store.hybrid_search.return_value = self.hits
        self.service.reranker.rerank.return_value = [
            {'index': 1, 'score': 0.9}, {'index': 0, 'score': 0.2},
        ]

    def run_mode(self, mode, top_k=7, top_n=2):
        return self.service.debug_retriever('校园', mode, top_k, top_n,
                                            expression='file_md5 in ["public"]')

    def test_vector_uses_only_dense_and_preserves_cosine(self):
        result = self.run_mode('vector')
        self.assertEqual((result['score_type'], result['rerank_status']), ('cosine', 'not_requested'))
        self.assertEqual([item['score'] for item in result['items']], [0.04, 0.03])
        self.assertEqual(result['candidate_file_md5s'], ['public', 'admin', 'public'])
        self.assertEqual(self.service.store.search.call_args.kwargs['limit'], 7)
        self.assertEqual(self.service.store.search.call_args.kwargs['expression'], 'file_md5 in ["public"]')
        self.service.store.hybrid_search.assert_not_called()
        self.service.reranker.rerank.assert_not_called()

    def test_hybrid_uses_threshold_and_never_reranks(self):
        result = self.run_mode('hybrid', top_n=1)
        self.assertEqual((result['score_type'], result['rerank_status']), ('rrf', 'not_requested'))
        self.assertEqual(result['candidate_file_md5s'], ['public', 'admin'])
        self.assertEqual(result['items'][0]['score'], 0.04)
        self.assertEqual(self.service.store.hybrid_search.call_args.kwargs['limit'], 7)
        self.assertEqual(self.service.store.hybrid_search.call_args.kwargs['expression'], 'file_md5 in ["public"]')
        self.service.store.search.assert_not_called()
        self.service.reranker.rerank.assert_not_called()

    def test_rerank_runs_once_clamps_count_and_uses_threshold(self):
        result = self.run_mode('hybrid_rerank', top_n=5)
        self.assertEqual((result['score_type'], result['rerank_status']), ('rerank', 'success'))
        self.assertEqual([item['text'] for item in result['items']], ['二'])
        self.service.reranker.rerank.assert_called_once_with('校园', ['一', '二'], top_n=2)
        self.service.store.hybrid_search.assert_called_once()

    def test_no_candidates_skips_rerank(self):
        self.service.store.hybrid_search.return_value = []
        result = self.run_mode('hybrid_rerank')
        self.assertEqual(result['items'], [])
        self.assertEqual(result['rerank_status'], 'not_run')
        self.service.reranker.rerank.assert_not_called()

    def test_rerank_threshold_also_filters_integer_zero(self):
        self.service.reranker.rerank.return_value = [
            {'index': 0, 'score': 0}, {'index': 1, 'score': 1},
        ]
        result = self.run_mode('hybrid_rerank')
        self.assertEqual([item['score'] for item in result['items']], [1])

    def test_failure_falls_back_and_existing_caller_contract_is_preserved(self):
        self.service.reranker.rerank.side_effect = RuntimeError('not available')
        result = self.run_mode('hybrid_rerank')
        self.assertEqual((result['score_type'], result['rerank_status']), ('rrf', 'fallback'))
        self.assertEqual([item['score'] for item in result['items']], [0.04, 0.03])
        self.assertEqual(self.service.rerank_retriever('校园', top_n=2), result['items'])

    def test_search_failure_does_not_fall_back(self):
        self.service.store.hybrid_search.side_effect = RuntimeError('database failed')
        with self.assertRaisesRegex(RuntimeError, 'database failed'):
            self.run_mode('hybrid_rerank')
        self.service.reranker.rerank.assert_not_called()


if __name__ == '__main__':
    unittest.main()
