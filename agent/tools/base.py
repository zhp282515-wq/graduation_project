from abc import ABC, abstractmethod
from typing import Any, Literal
from dataclasses import dataclass

class ToolError(Exception):
    pass

@dataclass
class ToolResult:
    """工具执行的返回值。

    run() 返回 str 时，executor 包成 ToolResult(content=str)；
    run() 返回 ToolResult 时，可额外携带 sources 等结构化数据。
    status 默认 completed —— 工具报错照旧用 raise ToolError。
    """
    content: str
    status: Literal["completed", "error"] = "completed"
    sources: list[dict[str, Any]] | None = None


class BaseTool(ABC):

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        pass

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        pass

    def to_schema(self) -> dict[str, Any]:
        schema = {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }

        return schema

    @abstractmethod
    def run(self, **kwargs) -> Any:
        pass