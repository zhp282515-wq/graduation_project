import json
import os
import time
from typing import Any, Iterator

import httpx
from dotenv import load_dotenv

from models.base import BaseProvider, ChatMessage, ChatResponse, ToolCall, parse_tool_arguments
from utils.logger_tool import logger
from utils.second_tool import fmt_duration

load_dotenv(override=True)


def _to_api_message(message: ChatMessage) -> dict[str, Any]:
    """转换内部消息，并保留思考模式工具调用所需的 reasoning_content。"""
    parts = message.content
    if all(part.get("type") == "text" for part in parts):
        content: Any = "".join(part.get("text", "") for part in parts)
    elif message.role in ("user", "tool"):
        content = parts
    else:
        raise ValueError(f"DeepSeek 的 {message.role} 消息只支持文本内容")

    result: dict[str, Any] = {"role": message.role, "content": content}
    if message.role == "assistant" and message.reasoning is not None:
        result["reasoning_content"] = message.reasoning
    if message.tool_calls:
        result["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for call in message.tool_calls
        ]
    if message.tool_call_id:
        result["tool_call_id"] = message.tool_call_id
    return result


def _parse_tool_call(call: dict[str, Any]) -> ToolCall:
    function = call.get("function")
    if not isinstance(function, dict) or not function.get("name") or not call.get("id"):
        raise RuntimeError("DeepSeek 工具调用结构异常：缺少 id 或函数名称")
    arguments, parse_error = parse_tool_arguments(function.get("arguments"))
    if parse_error:
        logger.warning("[解析] %s 的参数无效: %s", function["name"], parse_error)
    return ToolCall(
        id=call["id"],
        name=function["name"],
        arguments=arguments,
        parse_error=parse_error,
    )


def _iter_sse_data(response: httpx.Response) -> Iterator[str]:
    """按 SSE 事件边界拼接 data 行，忽略保活注释及其他元数据。"""
    data_lines: list[str] = []
    for raw_line in response.iter_lines():
        line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else raw_line
        if not line:
            if data_lines:
                yield "\n".join(data_lines)
                data_lines.clear()
        elif line.startswith("data:"):
            data = line[5:]
            data_lines.append(data[1:] if data.startswith(" ") else data)
    # 兼容最后一个事件之后没有空行就关闭连接的服务。
    if data_lines:
        yield "\n".join(data_lines)


def _parse_json(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError(f"DeepSeek 响应无法解析为 JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("DeepSeek 响应结构异常：数据不是 JSON 对象")
    error = data.get("error")
    if error:
        detail = error.get("message", str(error)) if isinstance(error, dict) else str(error)
        raise RuntimeError(f"DeepSeek 请求失败: {detail}")
    return data


class DeepSeekProvider(BaseProvider):
    """通过 Chat Completions API 接入 DeepSeek，事件格式与其他供应商一致。"""

    provider_id = "deepseek"

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str = "https://api.deepseek.com",
    ):
        self.model = model
        key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not key:
            logger.error("[配置] 未找到 DEEPSEEK_API_KEY")
            raise ValueError("缺少 API Key：请设置环境变量 DEEPSEEK_API_KEY 或在 .env 中配置")
        self.api_key = key
        self.base_url = base_url.rstrip("/")

    def reasoning_kwargs(self, value: Any = None) -> dict[str, Any]:
        return {"enable_thinking": False if value is None else bool(value)}

    def _payload(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None,
        enable_thinking: bool,
        temperature: float,
        max_tokens: int,
        reasoning_effort: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [_to_api_message(message) for message in messages],
            "thinking": {"type": "enabled" if enable_thinking else "disabled"},
            "max_tokens": max_tokens,
        }
        if enable_thinking:
            if reasoning_effort is not None:
                if reasoning_effort not in ("low", "high", "max"):
                    raise ValueError("DeepSeek reasoning_effort 必须为 low、high 或 max")
                payload["reasoning_effort"] = reasoning_effort
        else:
            # 思考模式下 temperature 不生效；关闭思考时才发送。
            payload["temperature"] = temperature
        if tools:
            payload["tools"] = tools
        return payload

    def invoke(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        enable_thinking: bool = False,
        temperature: float = 0.7,
        timeout: float = 90,
        max_tokens: int = 4096,
        reasoning_effort: str | None = None,
    ) -> ChatResponse:
        payload = self._payload(messages, tools, enable_thinking, temperature, max_tokens, reasoning_effort)
        logger.info("[请求] DeepSeek %s, %d 条消息, %d 个工具", self.model, len(messages), len(tools or []))
        start = time.perf_counter()
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        )
        logger.info("[响应] DeepSeek HTTP %s, 耗时 %s", response.status_code, fmt_duration(time.perf_counter() - start))
        if response.status_code != 200:
            raise RuntimeError(f"DeepSeek 返回 {response.status_code}: {response.text[:300]}")

        data = _parse_json(response.text)
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise RuntimeError("DeepSeek 响应结构异常：choices 缺失或为空")
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, dict):
            raise RuntimeError("DeepSeek 响应结构异常：缺少 message")
        calls = [_parse_tool_call(call) for call in message.get("tool_calls") or []]
        logger.info("[模型] DeepSeek finish_reason=%s, 工具调用 %d 个", choice.get("finish_reason"), len(calls))
        return ChatResponse(
            content=message.get("content") or "",
            tool_calls=calls,
            finish_reason=choice.get("finish_reason") or "",
            reasoning=message.get("reasoning_content"),
            token_usage=data.get("usage"),
        )

    def stream(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        enable_thinking: bool = False,
        temperature: float = 0.7,
        timeout: float = 90,
        max_tokens: int = 4096,
        reasoning_effort: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """产出 reasoning_delta、text_delta、tool_call 和 done；不在供应商内执行工具。"""
        payload = self._payload(messages, tools, enable_thinking, temperature, max_tokens, reasoning_effort)
        payload.update({"stream": True, "stream_options": {"include_usage": True}})
        logger.info("[流式请求] DeepSeek %s, %d 条消息, %d 个工具", self.model, len(messages), len(tools or []))
        start = time.perf_counter()
        tool_parts: dict[int, dict[str, Any]] = {}
        finish_reason = ""
        token_usage: dict[str, Any] | None = None

        with httpx.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        ) as response:
            if response.status_code != 200:
                body = response.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"DeepSeek 返回 {response.status_code}: {body[:300]}")

            for raw in _iter_sse_data(response):
                if raw.strip() == "[DONE]":
                    break
                if not raw.strip():
                    continue
                chunk = _parse_json(raw)
                if isinstance(chunk.get("usage"), dict):
                    token_usage = chunk["usage"]
                choices = chunk.get("choices")
                if not isinstance(choices, list):
                    raise RuntimeError("DeepSeek 流式响应结构异常：choices 不是列表")
                # 兼容仅携带 usage、choices 为空的末尾统计事件。
                if not choices:
                    continue
                choice = choices[0]
                if not isinstance(choice, dict):
                    raise RuntimeError("DeepSeek 流式响应结构异常：choice 不是对象")
                if choice.get("finish_reason") is not None:
                    finish_reason = str(choice["finish_reason"])
                delta = choice.get("delta") or {}
                if not isinstance(delta, dict):
                    raise RuntimeError("DeepSeek 流式响应结构异常：delta 不是对象")
                for key, event_type in (("reasoning_content", "reasoning_delta"), ("content", "text_delta")):
                    content = delta.get(key)
                    if isinstance(content, str) and content:
                        yield {"type": event_type, "content": content}
                for call_delta in delta.get("tool_calls") or []:
                    if not isinstance(call_delta, dict) or not isinstance(call_delta.get("index"), int):
                        raise RuntimeError("DeepSeek 工具调用分片缺少有效 index")
                    part = tool_parts.setdefault(call_delta["index"], {"id": "", "function": {"name": "", "arguments": ""}})
                    if call_delta.get("id"):
                        part["id"] += call_delta["id"]
                    function = call_delta.get("function") or {}
                    if not isinstance(function, dict):
                        raise RuntimeError("DeepSeek 工具调用分片的 function 不是对象")
                    for key in ("name", "arguments"):
                        value = function.get(key)
                        if isinstance(value, str):
                            part["function"][key] += value

        # 连接中断时不能把不完整工具调用提交给 Agent 执行。
        if not finish_reason:
            raise RuntimeError("DeepSeek 流在收到 finish_reason 前结束")
        if finish_reason == "tool_calls":
            if not tool_parts:
                raise RuntimeError("DeepSeek 返回 tool_calls 结束状态，但没有工具调用")
            calls = [_parse_tool_call(tool_parts[index]) for index in sorted(tool_parts)]
            for call in calls:
                logger.info("  → %s(%s)", call.name, call.arguments)
                yield {"type": "tool_call", "tool_call": call}

        logger.info("[流式响应] DeepSeek 完成, 耗时 %s, finish_reason=%s", fmt_duration(time.perf_counter() - start), finish_reason)
        yield {"type": "done", "finish_reason": finish_reason, "token_usage": token_usage}


if __name__ == "__main__":
    model = DeepSeekProvider(model="deepseek-flash")
    messages = [ChatMessage(role="user", content=[{"type": "text", "text": "你好"}])]
    for event in model.stream(messages, enable_thinking=False):
        if event["type"] == "text_delta":
            print(event["content"], end="", flush=True)
        else:
            print("\n", event)
