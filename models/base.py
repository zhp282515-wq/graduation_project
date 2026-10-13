import json
from abc import ABC, abstractmethod
from typing import Any
from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]
    parse_error: str | None = None

def parse_tool_arguments(raw: Any) -> tuple[dict[str, Any], str | None]:
    if isinstance(raw, dict):
        return raw, None
    if raw is None or raw == "":
        return {}, None
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        return {}, f"参数不是合法 JSON：{exc}"
    if not isinstance(value, dict):
        return {}, "参数必须是 JSON 对象"
    return value, None

class ChatMessage(BaseModel):
    role: str
    content: list[dict[str, Any]]
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    token_usage: dict[str, Any] | None = None

class ChatResponse(BaseModel):
    content: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: str
    reasoning: str | None = None
    token_usage: dict[str, Any] | None = None

class BaseProvider(ABC):

    @abstractmethod
    def reasoning_kwargs(self, value: Any = None) -> dict[str, Any]:
        """把调用方给的推理设置翻译成本 Provider stream() 的参数。
        value 对本层是不透明值，None 表示"用本 Provider 的默认"。"""
        pass

    @abstractmethod
    def invoke(self, messages: list[ChatMessage], tools: list[dict[str, Any]] | None = None, **kwargs) -> ChatResponse:
        pass

    @abstractmethod
    def stream(self):
        pass