from dataclasses import dataclass
from typing import Any, Literal

from agent.tools.base import ToolError
from agent.tools.registry import ToolRegistry
from models.base import ToolCall
from utils.logger_tool import logger

_TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
}


@dataclass(frozen=True)
class ToolResult:
    content: str
    status: Literal["completed", "error"]


def _find_argument_problem(schema: dict[str, Any], arguments: dict[str, Any]) -> str | None:
    for field in schema.get("required", []):
        if field not in arguments:
            return f"缺少必填参数 {field}"

    for field, value in arguments.items():
        json_type = schema.get("properties", {}).get(field, {}).get("type")
        check = _TYPE_CHECKS.get(json_type)
        if check and not check(value):
            return f"参数 {field} 应为 {json_type} 类型"

    return None


def execute_tool(registry: ToolRegistry, tool_call: ToolCall) -> ToolResult:
    if tool_call.parse_error:
        return ToolResult(
            content=f"工具参数解析失败：{tool_call.parse_error}。请严格按照该工具的参数 schema 重新生成 JSON 对象参数。",
            status="error",
        )

    tool = registry.get(tool_call.name)
    if tool is None:
        return ToolResult(content=f"找不到工具：{tool_call.name}", status="error")

    problem = _find_argument_problem(tool.parameters, tool_call.arguments)
    if problem:
        return ToolResult(content=f"工具 {tool_call.name} 的参数不符合要求：{problem}", status="error")

    try:
        return ToolResult(content=str(tool.run(**tool_call.arguments)), status="completed")
    except ToolError as exc:
        logger.warning("工具 %s 执行失败：%s", tool_call.name, exc)
        return ToolResult(content=str(exc), status="error")
    except Exception:
        logger.exception("工具 %s 发生未预期的异常", tool_call.name)
        return ToolResult(content="工具执行出现内部错误，请稍后重试。", status="error")