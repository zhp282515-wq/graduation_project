import hashlib
from pathlib import Path
from typing import Any, Callable
from threading import RLock

from knowledge.chunking import chunk_content_list
from knowledge.mineru_parser import MineruParser
from milvus.client import MilvusVectorStore
from models.dashscope.embedding import DashScopeEmbedding
from models.dashscope.reranker import DashScopeReranker
from utils.logger_tool import logger

_SEARCH_FIELDS = ("text", "file_md5", "file_name", "file_type", "chunk_index", "section_path", "block_type", "page", "url")

# 三个 retriever 的召回数；重排后最终返回条数。
_RECALL_TOP_K = 20
_RERANK_TOP_N = 5

# 重排分数的截断阈值。PoC 实测：相关文档 0.85~0.89，无关 0.045~0.135，
# 中间断层干净，取 0.3 可挡掉 BM25 单字虚命中。这是"回答有没有依据"的关口。
_RERANK_MIN_SCORE = 0.3

# RRF 融合分数下限：重排前先滤掉明显无关的候选，省重排的 token 与延迟。
#
# 算式（rrf_k=60，每路候选数 = top_k * 4）：单路排第 r 名贡献 1/(60+r)；
# 0.01 相当于"单路至少进前 40 名"才保留。
#
# 两个坑：
# 1. 与 rrf_k 及 store.hybrid_search 的 candidate_limit 倍率耦合，改其一要重校；
# 2. RRF 是排名派生分，无法表达"一条都没命中"——挡无依据回答靠 _RERANK_MIN_SCORE。
_FUSION_MIN_SCORE = 0.01

class KnowledgeService:

    def __init__(self):
        self.registry_lock = RLock()
        self.store = None
        self.parser = None
        try:
            self.store = MilvusVectorStore()
            self.store.ensure_collection()
            self.embedder = DashScopeEmbedding()
            self.parser = MineruParser()
            self.reranker = DashScopeReranker()
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        for resource in (self.parser, getattr(self.store, "client", None)):
            try:
                if resource is not None:
                    resource.close()
            except Exception:
                logger.warning("关闭知识库资源失败", exc_info=True)

    def verify_document(self, file_md5: str, expected_count: int | None = None) -> dict[str, Any]:
        doc = self.store.get_doc_status(file_md5, consistency_level="Strong")
        count = int((doc or {}).get("chunk_count") or 0)
        if count <= 0 or (expected_count is not None and count != expected_count):
            raise RuntimeError(f"文档入库校验失败：预期 {expected_count} 块，实际 {count} 块")
        return doc

    def _get_md5_hex(self, file_path: str | Path) -> str:
        """计算并返回当前文档内容的 md5 十六进制串(不对库做判断)。"""
        with open(file_path, "rb") as f:
            return hashlib.file_digest(f, "md5").hexdigest()

    def check_md5_hex(self, file_md5: str) -> bool:
        """判断该文档是否已入库: 库中是否已有与该文件 md5 相同的块。"""
        return self.store.get_doc_status(file_md5) is not None

    def save_md5_hex(self, file_md5: str) -> bool:
        """文件内容已成功写入 collection 后调用,记录其 md5 去重状态。
        md5 随向量块持久化。强一致确认至少一个块；失败抛异常。
        完整入库还需通过 verify_document 比较预期块数。
        """
        # 刚 insert 完就查询，默认 Bounded 一致性可能还看不到新数据，必须用 Strong。
        self.verify_document(file_md5)
        return True

    def del_md5_hex(self, file_md5: str) -> bool:
        """删除某 md5 对应的全部向量块(入参是文件的 md5 值)。
        md5 作为 file_md5 字段存于 Milvus,删除这些块的瞬间其 md5 一并清除。
        """
        return self.store.delete_by_md5(file_md5) > 0

    def load_document(
        self,
        file_path: str | Path,
        *,
        content_list: list[dict[str, Any]] | None = None,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
        on_stage: Callable[[str], None] | None = None,
        replace_existing: bool = False,
    ) -> dict[str, Any]:
        """文档的解析、分片、入库。md5 相同则跳过。

        content_list 已给出时跳过解析（用于已解析好的产物）；
        否则调 MinerU 解析 file_path。
        title 覆盖块前缀用的标题（默认取文件名主干）。
        metadata 是整篇共用的元数据，写进动态字段；本地文档不传即为空。
        """
        path = Path(file_path)
        file_md5 = self._get_md5_hex(path)
        if replace_existing:
            # 仅用于登记表中失败任务的显式重试，清理该哈希的残留块。
            self.store.delete_by_md5(file_md5)
        elif self.store.get_doc_status(file_md5, consistency_level="Strong") is not None:
            logger.info("文档已入库，跳过：%s (file_md5=%s)", path.name, file_md5)
            return {**self.verify_document(file_md5), "inserted": 0, "skipped": True}

        if on_stage is not None:
            on_stage("parsing")
        if content_list is None:
            doc = self.parser.parse_file(path)
            content_list = doc.content_list

        chunks = chunk_content_list(content_list, doc_title=title or path.stem)
        texts = [chunk.text for chunk in chunks]
        if not texts or any(not text.strip() for text in texts):
            raise ValueError("文档没有有效切片")
        if on_stage is not None:
            on_stage("embedding")
        vectors = self.embedder.embed_texts(texts)
        if len(vectors) != len(texts):
            raise ValueError("嵌入向量数与切片数不一致")
        metadatas = [
            {"section_path": c.section_path, "block_type": c.block_type, "page": c.page}
            for c in chunks
        ]
        if on_stage is not None:
            on_stage("inserting")
        inserted = self.store.insert_chunks(
            texts,
            vectors,
            file_md5=file_md5,
            file_name=title or path.name,
            file_type=path.suffix.lower().lstrip("."),
            file_size=path.stat().st_size,
            metadatas=metadatas,
            doc_metadata=metadata,
        )
        if inserted != len(texts):
            raise RuntimeError(f"文档仅写入 {inserted}/{len(texts)} 块")
        doc = self.verify_document(file_md5, expected_count=len(texts))
        return {**doc, "inserted": inserted, "skipped": False}

    def list_documents(self) -> list[dict[str, Any]]:
        """列出库中所有文档"""
        docs: dict[str, dict[str, Any]] = {}
        # 迭代器按主键翻页，output_fields 必须包含 id
        iterator = self.store.client.query_iterator(
            collection_name=self.store.collection,
            filter="chunk_index >= 0",
            output_fields=["id", "file_md5", "file_name", "file_type", "file_size"],
            batch_size=1000,
            consistency_level="Strong",
        )
        try:
            while batch := iterator.next():
                for row in batch:
                    md5 = row["file_md5"]
                    if md5 not in docs:
                        docs[md5] = {
                            "file_md5": md5,
                            "file_name": row["file_name"],
                            "file_type": row["file_type"],
                            "file_size": row["file_size"],
                            "chunk_count": 0,
                        }
                    docs[md5]["chunk_count"] += 1
        finally:
            iterator.close()
        return list(docs.values())

    def list_chunks(
        self,
        file_md5: str,
        *,
        offset: int = 0,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """某文档按 chunk_index 顺序的一页切片。"""
        return self.store.list_chunks(file_md5, offset=offset, limit=limit)

    def get_document(self, file_md5: str) -> dict[str, Any] | None:
        """根据file_md5查找库中对应文档"""
        return self.store.get_doc_status(file_md5)

    def del_document(self, file_md5: str) -> bool:
        """根据file_md5删除库中对应文档"""
        return self.del_md5_hex(file_md5)

    @staticmethod
    def _with_source(hit: dict[str, Any]) -> dict[str, Any]:
        """把一条原始命中转成「正文 + 分数 + 来源」。

        三个 retriever 共用这个出口，输出结构一致 —— 评测脚本喂同一套解析。
        """
        return {
            "text": hit["text"],
            "score": hit["score"],
            "source": {
                "file_name": hit.get("file_name"),
                "file_md5": hit.get("file_md5"),
                "section_path": hit.get("section_path"),
                "page": hit.get("page") if hit.get("file_type") == "pdf" and type(hit.get("page")) is int and hit["page"] > 0 else None,
                "chunk_id": hit.get("id"),
                "chunk_index": hit.get("chunk_index"),
                "file_type": hit.get("file_type"),
                "url": hit.get("url"),
            },
        }

    def _dense_search(
        self,
        query: str,
        top_k: int,
        *,
        min_score: float = 0.0,
        expression: str = "",
    ) -> list[dict[str, Any]]:
        """纯稠密检索的原始命中。min_score 默认 0（不过滤）。

        余弦分与 RRF 分量纲不同，别把它改成 _FUSION_MIN_SCORE —— 那会误杀
        BM25 靠关键词捞回来的块。要按余弦过滤得单独校准。
        """
        hits = self.store.search(
            self.embedder.embed_query(query),
            limit=top_k,
            output_fields=_SEARCH_FIELDS,
            expression=expression,
        )
        if min_score <= 0:
            return hits
        return [hit for hit in hits if hit["score"] >= min_score]

    def _hybrid_search(
        self,
        query: str,
        top_k: int,
        *,
        min_score: float = _FUSION_MIN_SCORE,
        expression: str = "",
    ) -> list[dict[str, Any]]:
        """稠密 + BM25 混合检索（RRF 融合）+ 融合分下限过滤，返回原始命中。

        私有原语：mix_retriever 包装它，rerank_retriever 拿它当重排输入池。
        不对外暴露 —— service.search 会和 store.search（纯稠密）同名异义。

        这里不传 candidate_limit，用 store 默认的 limit*4：召回 20 条时每路
        各捞 80 条再融合，RRF 才有腾挪空间。
        """
        hits = self.store.hybrid_search(
            query,
            self.embedder.embed_query(query),
            limit=top_k,
            output_fields=_SEARCH_FIELDS,
            expression=expression,
        )
        if min_score <= 0:
            return hits

        kept = [hit for hit in hits if hit["score"] >= min_score]
        if len(kept) < len(hits):
            logger.info(
                "RRF 阈值 %.4f 过滤 %d/%d 条低分候选",
                min_score, len(hits) - len(kept), len(hits),
            )
        return kept

    def base_retriever(self, query: str, top_k: int = _RECALL_TOP_K) -> list[dict[str, Any]]:
        """① 纯稠密向量检索。对比实验的基线。"""
        return [self._with_source(hit) for hit in self._dense_search(query, top_k)]

    def mix_retriever(self, query: str, top_k: int = _RECALL_TOP_K) -> list[dict[str, Any]]:
        """② 混合检索（稠密 + BM25，RRF 融合），不重排。实验一的对照组。"""
        return [self._with_source(hit) for hit in self._hybrid_search(query, top_k)]

    def rerank_retriever(
        self,
        query: str,
        top_k: int = _RECALL_TOP_K,
        top_n: int = _RERANK_TOP_N,
        *, expression: str = "",
    ) -> list[dict[str, Any]]:
        """③ 混合检索 → 重排 → 阈值截断。生产链路用这个。

        先召回 top_k(20) 个候选再精排出 top_n(5)：只对最终条数重排等于没排。
        重排失败时退回混合检索顺序，不让整条链路挂掉。
        """
        candidates = self._hybrid_search(query, top_k, expression=expression)
        if not candidates:
            return []

        items, _ = self._rerank_candidates(query, candidates, top_n)
        return items

    def _rerank_candidates(
        self, query: str, candidates: list[dict[str, Any]], top_n: int,
    ) -> tuple[list[dict[str, Any]], str]:
        """对已有候选重排；失败时保留 RRF 顺序供调用方安全降级。"""

        try:
            ranked = self.reranker.rerank(
                query,
                [hit["text"] for hit in candidates],
                top_n=min(top_n, len(candidates)),
            )
        except Exception:
            logger.exception("重排失败，退回混合检索顺序")
            return [self._with_source(hit) for hit in candidates[:top_n]], "fallback"

        hits: list[dict[str, Any]] = []
        for item in ranked:
            index = item.get("index")
            score = item.get("score")
            if not isinstance(index, int) or not 0 <= index < len(candidates):
                logger.warning("重排返回越界下标 %s，已跳过", index)
                continue
            if isinstance(score, (int, float)) and score < _RERANK_MIN_SCORE:
                continue
            hit = dict(candidates[index])      # 浅拷贝：不污染候选列表
            hit["score"] = score               # 用重排分覆盖 RRF 分
            hits.append(self._with_source(hit))
        return hits[:top_n], "success"

    def debug_retriever(
        self, query: str, mode: str, top_k: int, top_n: int, *, expression: str,
    ) -> dict[str, Any]:
        """单次召回，返回调试指标；candidate_file_md5s 仅供权限复核使用。"""
        if mode == "vector":
            candidates = self._dense_search(query, top_k, expression=expression)
            score_type, status = "cosine", "not_requested"
        elif mode in ("hybrid", "hybrid_rerank"):
            candidates = self._hybrid_search(query, top_k, expression=expression)
            score_type = "rerank" if mode == "hybrid_rerank" else "rrf"
            status = "not_run" if mode == "hybrid_rerank" else "not_requested"
        else:
            raise ValueError(f"未知检索模式: {mode}")

        if mode == "hybrid_rerank" and candidates:
            items, status = self._rerank_candidates(query, candidates, top_n)
            if status == "fallback":
                score_type = "rrf"
        else:
            items = [self._with_source(hit) for hit in candidates[:top_n]]

        return {
            "items": items,
            "score_type": score_type,
            "rerank_status": status,
            "candidate_file_md5s": [hit.get("file_md5") for hit in candidates],
        }

if __name__ == '__main__':

    from pathlib import Path
    from rich import print as rprint
    service = KnowledgeService()
    rprint(service.list_documents())

    # print(server.del_document("aa66ee24152e9734259564daebc7c949"))
    # from rich import print as rprint
    # rprint(server.base_retriever("名单公布"))
