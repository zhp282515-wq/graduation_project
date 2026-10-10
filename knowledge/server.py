import hashlib
from pathlib import Path
from typing import Any

from knowledge.chunking import chunk_content_list
from knowledge.mineru_parser import MineruParser
from milvus.client import MilvusVectorStore
from models.dashscope.embedding import DashScopeEmbedding
from utils.logger_tool import logger

_SEARCH_FIELDS = ("text", "file_md5", "file_name", "section_path", "block_type", "page")


class KnowledgeService:

    def __init__(self):
        self.store = MilvusVectorStore()
        self.store.ensure_collection()
        self.embedder = DashScopeEmbedding()
        self.parser = MineruParser()

    def _get_md5_hex(self, file_path: str | Path) -> str:
        """计算并返回当前文档内容的 md5 十六进制串(不对库做判断)。"""
        with open(file_path, "rb") as f:
            return hashlib.file_digest(f, "md5").hexdigest()

    def check_md5_hex(self, file_md5: str) -> bool:
        """判断该文档是否已入库: 库中是否已有与该文件 md5 相同的块。"""
        return self.store.get_doc_status(file_md5) is not None

    def save_md5_hex(self, file_md5: str) -> bool:
        """文件内容已成功写入 collection 后调用,记录其 md5 去重状态。
        md5 作为 file_md5 字段随向量块一起持久化在 Milvus,这里校验该文件
        确实已有块落库,若没有则提示(真正落库在 load_document 完成)。
        """
        # 刚 insert 完就查询，默认 Bounded 一致性可能还看不到新数据，必须用 Strong。
        if self.store.get_doc_status(file_md5, consistency_level="Strong") is None:
            logger.warning("未找到 file_md5=%s 的知识块，入库可能失败", file_md5)
            return False
        return True

    def del_md5_hex(self, file_md5: str) -> bool:
        """删除某 md5 对应的全部向量块(入参是文件的 md5 值)。
        md5 作为 file_md5 字段存于 Milvus,删除这些块的瞬间其 md5 一并清除。
        """
        return self.store.delete_by_md5(file_md5) > 0

    def load_document(self, file_path: str | Path) -> dict[str, Any]:
        """
        实现文档的解析、分片、入库
        文档入库时先进行去重操作，若file_md5相同，则跳过
        若是新文档则生成file_md5
        """
        path = Path(file_path)
        file_md5 = self._get_md5_hex(path)
        if self.check_md5_hex(file_md5):
            logger.info("文档已入库，跳过：%s (file_md5=%s)", path.name, file_md5)
            return {"file_md5": file_md5, "inserted": 0, "skipped": True}

        doc = self.parser.parse_file(path)
        chunks = chunk_content_list(doc.content_list, doc_title=path.stem)
        texts = [chunk.text for chunk in chunks]
        vectors = self.embedder.embed_texts(texts)
        metadatas = [
            {"section_path": c.section_path, "block_type": c.block_type, "page": c.page}
            for c in chunks
        ]
        # doc_id 与 file_md5 取同一值，按 md5 去重/删除直接复用 client 的 doc 级接口
        inserted = self.store.insert_chunks(
            texts,
            vectors,
            file_md5=file_md5,
            file_name=path.name,
            file_type=path.suffix.lower().lstrip("."),
            file_size=path.stat().st_size,
            metadatas=metadatas,
        )
        self.save_md5_hex(file_md5)
        return {"file_md5": file_md5, "inserted": inserted, "skipped": False}

    def list_documents(self) -> list[dict[str, Any]]:
        """列出库中所有文档"""
        docs: dict[str, dict[str, Any]] = {}
        # 迭代器按主键翻页，output_fields 必须包含 id
        iterator = self.store.client.query_iterator(
            collection_name=self.store.collection,
            filter="chunk_index >= 0",
            output_fields=["id", "file_md5", "file_name", "file_type", "file_size"],
            batch_size=1000,
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

    def get_document(self, file_md5: str) -> dict[str, Any] | None:
        """根据file_md5查找库中对应文档"""
        return self.store.get_doc_status(file_md5)

    def del_document(self, file_md5: str) -> bool:
        """根据file_md5删除库中对应文档"""
        return self.del_md5_hex(file_md5)

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        return self.store.search(
            self.embedder.embed_query(query),
            limit=top_k,
            output_fields=_SEARCH_FIELDS,
        )

    def base_retriever(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """包装 search，每条结果附带来源（文件名、页码、章节路径）。"""
        hits = self.search(query, top_k=top_k)
        return [
            {
                "text": hit["text"],
                "score": hit["score"],
                "source": {
                    "file_name": hit.get("file_name"),
                    "file_md5": hit.get("file_md5"),
                    "section_path": hit.get("section_path"),
                    "page": hit.get("page"),
                },
            }
            for hit in hits
        ]

if __name__ == '__main__':

    server = KnowledgeService()
    server.load_document("../data/暑期社会实践志愿服务.pdf")
    # print(server.del_document("aa66ee24152e9734259564daebc7c949"))
    # from rich import print as rprint
    # rprint(server.base_retriever("名单公布"))