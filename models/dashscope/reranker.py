"""DashScope 文本重排适配器。

qwen3.7-text-rerank 走 DashScope 专用 rerank 端点，不是 compatible-mode。
只做"给一批候选打分排序"，怎么用由调用方决定。
"""

import os
import time
from typing import Any, Sequence

import httpx
from dotenv import load_dotenv

from utils.logger_tool import logger

load_dotenv(override=True)

_RERANK_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/"
    "rerank/text-rerank/text-rerank"
)


class DashScopeReranker:
    def __init__(
        self,
        model: str = "qwen3.7-text-rerank",
        *,
        api_key: str | None = None,
        url: str = _RERANK_URL,
        timeout: float = 60,
    ):
        key = api_key or os.getenv("DASHSCOPE_API_KEY")
        if not key:
            logger.error("[配置] 未找到 DASHSCOPE_API_KEY")
            raise ValueError("缺少 API Key：请设置环境变量 DASHSCOPE_API_KEY 或在 .env 中配置")
        self.api_key = key
        self.model = model
        self.url = url
        self.timeout = timeout

    def rerank(
        self,
        query: str,
        documents: Sequence[str],
        *,
        top_n: int | None = None,
    ) -> list[dict[str, Any]]:
        """按与 query 的相关性重排候选，返回 [{index, score}, ...]（降序）。

        index 指向传入 documents 的下标。响应里只回传 text，调用方必须靠
        index 回查原始候选，才能拿回 file_name / page 等元数据。
        """
        if not documents:
            return []

        payload = {
            "model": self.model,
            "input": {"query": query, "documents": list(documents)},
            "parameters": {
                "return_documents": False,
                "top_n": top_n or len(documents),
            },
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        logger.info("[重排请求] %d 个候选, model=%s", len(documents), self.model)
        started = time.perf_counter()
        try:
            resp = httpx.post(self.url, headers=headers, json=payload, timeout=self.timeout)
        except httpx.HTTPError as exc:
            logger.error("[重排错误] 请求失败：%s", exc)
            raise RuntimeError(f"重排请求失败：{exc}") from exc

        logger.info("[重排响应] %s, 耗时 %.2fs", resp.status_code, time.perf_counter() - started)

        if resp.status_code != 200:
            logger.error("[重排错误] HTTP %s: %s", resp.status_code, resp.text[:300])
            raise RuntimeError(f"重排服务返回 {resp.status_code}: {resp.text[:300]}")

        try:
            data = resp.json()
        except Exception as exc:
            logger.error("[重排解析] 响应不是合法 JSON：%s", exc)
            raise RuntimeError(f"重排响应无法解析为 JSON：{exc}") from exc

        results = (data.get("output") or {}).get("results")
        if not isinstance(results, list):
            logger.error("[重排解析] 响应缺少 output.results: %s", str(data)[:300])
            raise RuntimeError("重排响应结构异常：缺少 output.results")

        return [
            {"index": item.get("index"), "score": item.get("relevance_score")}
            for item in results
        ]