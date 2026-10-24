import time
from typing import Any

from agent.tools.base import BaseTool, ToolError, ToolResult
from knowledge.server import KnowledgeService
from utils.logger_tool import logger
from utils.second_tool import fmt_duration


_UNSET = object()


class KnowledgeSearchTool(BaseTool):
    def __init__(self, service=_UNSET):
        # 不传参数保持脚本用法；显式 None 表示服务不可用，禁止重试初始化。
        self.service = KnowledgeService() if service is _UNSET else service

    @property
    def name(self) -> str:
        return "knowledge_search"

    @property
    def description(self) -> str:
        return """
        本地校园知识库检索工具。
        用于查询已入库的校园文档，如学校通知、规章制度、活动安排、办事流程等。
        使用原则：
        - 涉及学校内部信息时，优先使用此工具；本地知识库没有相关内容时，再考虑 websearch。
        - 搜索 query 应该具体，包含关键实体名称和限定条件。
        - 每次只返回最相关的前几条，结果不足时应换关键词再检索，而不是要求返回更多条。
        - 回答时注明信息来源的文件名和页码。
        """

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "要检索的问题或关键词",
                }
            },
            "required": ["query"],
        }

    def run(self, **kwargs) -> ToolResult:
        if self.service is None:
            raise ToolError("校园知识库暂不可用，请稍后联系维护者恢复服务。")
        query = kwargs.get("query", "")
        if not query:
            raise ToolError("未提供检索内容")

        start = time.perf_counter()
        results = self.service.rerank_retriever(query)
        if not results:
            return ToolResult(content="知识库中没有找到相关内容")

        elapsed = time.perf_counter() - start
        logger.info(f"[响应] 查询完成, 耗时 {fmt_duration(elapsed)}")

        content = "\n\n".join(
            f"[{index}] {self._format_source(result['source'])}\n{result['text']}"
            for index, result in enumerate(results, start=1)
        )
        sources = [
            {
                "index": index,
                "file_name": r["source"]["file_name"],
                "file_md5": r["source"]["file_md5"],
                "section_path": r["source"]["section_path"],
                "page": r["source"]["page"],
                "score": r["score"],
                "chunk_id": r["source"].get("chunk_id"),
                "chunk_index": r["source"].get("chunk_index"),
                "file_type": r["source"].get("file_type"),
                "url": r["source"].get("url"),
                "text": r["text"],
            }
            for index, r in enumerate(results, start=1)
        ]
        return ToolResult(content=content, sources=sources)

    @staticmethod
    def _format_source(source: dict[str, Any]) -> str:
        parts = [f"来源：{source['file_name'] or '未知文件'}"]
        if source["page"] is not None:
            parts.append(f"第{source['page']}页")
        if source["section_path"]:
            parts.append(f"章节：{source['section_path']}")
        return "，".join(parts)

if __name__ == '__main__':
    tool = KnowledgeSearchTool()
    print(tool.run(**{"query": "活动人员"}))
