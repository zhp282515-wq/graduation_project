"""Milvus 向量库客户端：知识块的写入与稠密检索。

RAG-1 只做稠密向量检索；BM25 稀疏索引、混合检索、重排属于 RAG-4。
元数据（category / page / section_path 等）走动态字段，等 RAG-4 需要过滤时
再提升为显式字段。
"""

import os
from typing import Any, Sequence
from uuid import uuid4

from dotenv import load_dotenv
from pymilvus import DataType, MilvusClient

from utils.logger_tool import logger

load_dotenv(override=True)

DEFAULT_COLLECTION = "campus_knowledge"
DEFAULT_URI = "http://localhost:19530"

# Milvus VARCHAR 单字段上限为 65535。
_TEXT_MAX_LEN = 65535
_ID_MAX_LEN = 64


class MilvusVectorStore:
    def __init__(
        self,
        *,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
        collection: str = DEFAULT_COLLECTION,
        dimension: int = 2560,
    ):
        self.collection = collection
        self.dimension = dimension
        self.uri = uri or os.getenv("MILVUS_URI") or DEFAULT_URI
        self.user = user or os.getenv("MILVUS_USER") or "root"
        self.password = password or os.getenv("MILVUS_PASSWORD") or "root"
        self.client = MilvusClient(
            uri=self.uri,
            user=self.user,
            password=self.password,
        )

    def ensure_collection(self) -> None:
        """集合不存在则创建（含索引并加载）；已存在则确保已加载。幂等，可重复调用。"""
        if self.client.has_collection(self.collection):
            self.client.load_collection(self.collection)
            return

        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=True)
        schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=_ID_MAX_LEN)
        schema.add_field("file_md5", DataType.VARCHAR, max_length=64)
        schema.add_field("file_name", DataType.VARCHAR, max_length=1024)
        schema.add_field("file_type", DataType.VARCHAR, max_length=32)
        schema.add_field("file_size", DataType.INT64)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=self.dimension)
        schema.add_field("text", DataType.VARCHAR, max_length=_TEXT_MAX_LEN)
        schema.add_field("chunk_index", DataType.INT64)

        index_params = MilvusClient.prepare_index_params()
        index_params.add_index(
            field_name="vector",
            index_type="HNSW",
            metric_type="COSINE",
            params={"M": 16, "efConstruction": 200},
        )

        self.client.create_collection(
            collection_name=self.collection,
            schema=schema,
            index_params=index_params,
        )
        logger.info("已创建 Milvus 集合 %s (dim=%d)", self.collection, self.dimension)

    def drop_collection(self) -> None:
        if self.client.has_collection(self.collection):
            self.client.drop_collection(self.collection)
            logger.warning("已删除 Milvus 集合 %s", self.collection)

    def insert_chunks(
        self,
        texts: Sequence[str],
        vectors: Sequence[Sequence[float]],
        *,
        file_md5: str,
        file_name: str,
        file_type: str,
        file_size: int,
        metadatas: Sequence[dict[str, Any]] | None = None,
    ) -> int:
        """写入一批知识块。texts 与 vectors 必须一一对应。"""
        if len(texts) != len(vectors):
            raise ValueError(f"texts({len(texts)}) 与 vectors({len(vectors)}) 数量不一致")
        if not texts:
            return 0

        rows: list[dict[str, Any]] = []
        for index, (text, vector) in enumerate(zip(texts, vectors)):
            row: dict[str, Any] = {
                "id": uuid4().hex,
                "file_md5": file_md5,
                "file_name": file_name,
                "file_type": file_type,
                "file_size": file_size,
                "vector": list(vector),
                "text": text,
                "chunk_index": index,
            }
            if metadatas is not None:
                # 额外字段进动态字段，不占 schema。
                row.update(metadatas[index])
            rows.append(row)

        result = self.client.insert(collection_name=self.collection, data=rows)
        count = result.get("insert_count", len(rows))
        logger.info("写入 %d 个知识块到 %s (doc=%s)", count, self.collection, file_md5)
        return count

    def delete_by_md5(self, file_md5: str) -> int:
        """按文件 md5 删除其全部知识块。"""
        result = self.client.delete(
            collection_name=self.collection,
            filter="file_md5 == {file_md5}",
            filter_params={"file_md5": file_md5},
        )
        count = result.get("delete_count", 0)
        logger.info("从 %s 删除 file_md5=%s 的 %d 个知识块", self.collection, file_md5, count)
        return count

    def get_doc_status(
        self,
        file_md5: str,
        *,
        consistency_level: str | None = None,
    ) -> dict[str, Any] | None:
        """返回该 file_md5 的文件信息与已入库块数；没入过库返回 None。

        默认跟随集合的一致性级别。刚写完就校验的场景（save_md5_hex）需要传
        "Strong"，否则新数据可能还没对本查询可见，误判为未入库。
        """
        base_kwargs = {
            "collection_name": self.collection,
            "filter": "file_md5 == {file_md5}",
            "filter_params": {"file_md5": file_md5},
        }
        if consistency_level is not None:
            base_kwargs["consistency_level"] = consistency_level

        rows = self.client.query(
            **base_kwargs,
            output_fields=["file_name", "file_type", "file_size"],
            limit=1,
        )
        if not rows:
            return None
        count = self.client.query(**base_kwargs, output_fields=["count(*)"])
        return {
            "file_md5": file_md5,
            "file_name": rows[0]["file_name"],
            "file_type": rows[0]["file_type"],
            "file_size": rows[0]["file_size"],
            "chunk_count": count[0]["count(*)"],
        }

    def search(
        self,
        query_vector: Sequence[float],
        *,
        limit: int = 5,
        expression: str = "",
        output_fields: Sequence[str] = ("text", "chunk_index"),
    ) -> list[dict[str, Any]]:
        """稠密向量检索，按余弦相似度返回 top-k。"""
        results = self.client.search(
            collection_name=self.collection,
            data=[list(query_vector)],
            limit=limit,
            filter=expression,
            output_fields=list(output_fields),
            search_params={"metric_type": "COSINE", "params": {"ef": 64}},
        )

        hits: list[dict[str, Any]] = []
        for hit in results[0]:
            row: dict[str, Any] = {"id": hit.get("id"), "score": hit.get("distance")}
            row.update(hit.get("entity", {}))
            hits.append(row)

        logger.info("检索到 %d 条 (limit=%d)", len(hits), limit)
        return hits


if __name__ == "__main__":
    from models.dashscope.embedding import DashScopeEmbedding
    from rich import print as rprint

    emb = DashScopeEmbedding()
    store = MilvusVectorStore()
    store.ensure_collection()
    # store.drop_collection()
    # store.drop_collection()
    # texts = [
    #     "江西师范大学图书馆开放时间为每天8:00至22:00，节假日另行通知。",
    #     "学校第一食堂位于大学生活动中心一楼，人均消费约10元。",
    #     "校车在南北校区之间运行，工作日每30分钟一班。",
    # ]
    # store.insert_chunks(texts, emb.embed_texts(texts), file_md5="demo-001")

    # store.delete_by_doc("demo-001")

    # query = "图书馆几点关门？"
    # for hit in store.search(emb.embed_query(query), limit=1):
    #     rprint(f"{hit['score']:.4f}  {hit['text']}")
