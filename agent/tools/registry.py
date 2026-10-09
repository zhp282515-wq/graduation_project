import re
from typing import Any

from agent.tools.base import BaseTool
from utils.logger_tool import logger

_TOOL_NAME_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")


class ToolRegistry:
    def __init__(self, tools: list[BaseTool]):
        self._tools: dict[str, BaseTool] = {}
        for tool in tools:
            name = tool.name
            schema = tool.parameters
            if not _TOOL_NAME_PATTERN.fullmatch(name):
                raise ValueError(f"工具名称不合法：{name!r}，只允许字母、数字、下划线和短横线，长度 1 到 64")
            if name in self._tools:
                logger.warning("工具 %s 已注册，跳过重复的同名工具", name)
                continue
            if schema.get("type") != "object":
                raise ValueError(f"工具 {name} 的参数 schema 顶层必须是 object")
            undefined = [f for f in schema.get("required", []) if f not in schema.get("properties", {})]
            if undefined:
                raise ValueError(f"工具 {name} 的 required 字段未在 properties 中定义：{undefined}")
            self._tools[name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def get_schemas(self) -> list[dict[str, Any]]:
        return [tool.to_schema() for tool in self._tools.values()]