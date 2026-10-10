"""DashScope 多模态向量（Embedding）适配器。

qwen3-vl-embedding 走 DashScope 的专用多模态端点，不是 compatible-mode 那个。
本适配器目前只做文本嵌入；图片/视频嵌入等知识库需要图片块时再扩展。
"""

import json
import os
import time
from typing import Any, Sequence

import httpx
from dotenv import load_dotenv

from utils.logger_tool import logger

load_dotenv(override=True)

_EMBEDDING_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
    "multimodal-embedding/multimodal-embedding"
)

# 单次请求 contents 元素上限，DashScope 多模态 embedding 文档规定为 20。
_MAX_BATCH = 20


class DashScopeEmbedding:
    def __init__(
        self,
        model: str = "qwen3-vl-embedding",
        *,
        api_key: str | None = None,
        url: str = _EMBEDDING_URL,
        dimension: int = 2560,
        timeout: float = 60,
    ):
        key = api_key or os.getenv("DASHSCOPE_API_KEY")
        if not key:
            logger.error("[配置] 未找到 DASHSCOPE_API_KEY")
            raise ValueError("缺少 API Key：请设置环境变量 DASHSCOPE_API_KEY 或在 .env 中配置")

        self.api_key = key
        self.model = model
        self.url = url
        self.dimension = dimension
        self.timeout = timeout

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """把一批文本编码成向量，顺序与输入一致。"""
        if not texts:
            return []

        vectors: list[list[float]] = []
        for start in range(0, len(texts), _MAX_BATCH):
            vectors.extend(self._embed_batch(list(texts[start:start + _MAX_BATCH])))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        """单条查询文本的向量。"""
        return self._embed_batch([text])[0]

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        payload = {
            "model": self.model,
            "input": {"contents": [{"text": text} for text in texts]},
            "parameters": {"dimension": self.dimension},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        logger.info(
            "[嵌入请求] %d 条文本, model=%s, dim=%d",
            len(texts), self.model, self.dimension,
        )
        started = time.perf_counter()
        try:
            resp = httpx.post(self.url, headers=headers, json=payload, timeout=self.timeout)
        except httpx.HTTPError as exc:
            logger.error("[嵌入错误] 请求失败：%s", exc)
            raise RuntimeError(f"嵌入请求失败：{exc}") from exc

        elapsed = time.perf_counter() - started
        logger.info("[嵌入响应] %s, 耗时 %.2fs", resp.status_code, elapsed)

        if resp.status_code != 200:
            logger.error("[嵌入错误] HTTP %s: %s", resp.status_code, resp.text[:300])
            raise RuntimeError(f"嵌入服务返回 {resp.status_code}: {resp.text[:300]}")

        try:
            data = resp.json()
        except Exception as exc:
            logger.error("[嵌入解析] 响应不是合法 JSON：%s", exc)
            raise RuntimeError(f"嵌入响应无法解析为 JSON：{exc}") from exc

        embeddings = (data.get("output") or {}).get("embeddings")
        if not isinstance(embeddings, list) or not embeddings:
            logger.error(
                "[嵌入解析] 响应缺少 output.embeddings: %s",
                json.dumps(data, ensure_ascii=False)[:300],
            )
            raise RuntimeError("嵌入响应结构异常：缺少 output.embeddings")

        # 按 index 排序，保证顺序与输入严格对应。
        ordered = sorted(embeddings, key=lambda item: item.get("index", 0))
        return [item["embedding"] for item in ordered]

if __name__ == '__main__':
    ser = DashScopeEmbedding()
    emb = ser.embed_texts(["爸爸","法拉利","爸爸"])
    print(emb)
    print(f"条数：{len(emb)}")
    print(f"维度：{len(emb[0])}")

    import math
    def cos(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b)))


    print("相似(0,1):", round(cos(emb[0], emb[1]), 4))
    print("相似(0,2):", round(cos(emb[0], emb[2]), 4))