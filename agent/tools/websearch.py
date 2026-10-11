import time
from typing import Any

import httpx
import os
from dotenv import load_dotenv

from utils.logger_tool import logger

load_dotenv(override=True)
from agent.tools.base import BaseTool, ToolError
from utils.second_tool import fmt_duration


class WebSearchTool(BaseTool):
    def __init__(self):
        self.api_key = os.getenv("FIRECRAWL_API_KEY")
        self.url = "https://api.firecrawl.dev/v2/search"

    @property
    def name(self) -> str:
        return "websearch"

    @property
    def description(self) -> str:
        return """
        互联网 Web 搜索工具。
        用于获取当前互联网中的公开信息，尤其适合：
        1. 本地知识库没有相关信息时；
        2. 用户明确要求联网查询、搜索最新信息时；
        3. 查询会随时间变化的信息，如学校通知、政策、活动、新闻等；
        4. 需要查找学校官网、政府网站、官方公告、PDF 文档等权威资料时；
        5. 需要通过多个来源验证事实时。
        使用原则：
        - 能够通过本地知识库可靠回答的问题，不要调用此工具。
        - 优先使用官方、政府、学校等权威来源。
        - 搜索 query 应该具体、清晰，包含必要的实体名称和限定条件。
        - 如果第一次搜索结果不足，可以修改 query 后再次搜索。
        - 不要为了简单闲聊或常识问题调用此工具。
        """

    @property
    def parameters(self) -> dict[str, Any]:
        schema = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "要搜索的问题"
                }
            },
            "required": ["query"]
        }
        return schema

    def run(self, **kwargs) -> str:

        query = kwargs.get("query")

        payload = {
            "query": query,
            "sources": ["web"],
            "categories": [],
            "limit": 5,
            "scrapeOptions": {
                "onlyMainContent": True,
                "maxAge": 172800000,
                "parsers": ["pdf"],
                "formats": []
            }
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        start = time.perf_counter()

        try:
            response = httpx.post(self.url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise ToolError(f"网络搜索请求失败：{exc}") from exc

        elapsed = time.perf_counter() - start
        logger.info(f"[响应] {response.status_code}, 耗时 {fmt_duration(elapsed)}")

        if response.status_code != 200:
            raise ToolError(f"网络搜索服务返回 HTTP {response.status_code}")

        body = response.json()
        if body.get("success") is False:
            raise ToolError(f"网络搜索失败：{body.get('error', '未知错误')}")

        data = body.get("data")
        if not data:
            return "未搜索到相关结果"
        return str(data)

if __name__ == '__main__':
    tool = WebSearchTool()
    from rich import print as rprint
    rprint(tool.run(**{"query": "gpt"}))