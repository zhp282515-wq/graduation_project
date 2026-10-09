from typing import Any, Iterator

from models.base import BaseProvider, ChatMessage, parse_tool_arguments
from models.base import ChatResponse
import json
import httpx
from models.base import ToolCall
from utils.logger_tool import logger
import time
import os
from dotenv import load_dotenv
load_dotenv(override=True)


class ContentInspectionError(RuntimeError):
    """模型输出触发内容安全审核"""
    pass

def _to_api_message(message: ChatMessage) -> dict[str, Any]:

    result: dict[str, Any] = {
        "role": message.role,
        "content": message.content,
    }

    if message.tool_calls:
        tool_calls = []
        for tool_call in message.tool_calls:
            tool_calls.append({
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.name,
                    "arguments": json.dumps(tool_call.arguments),
                },
            })
        result["tool_calls"] = tool_calls

    if message.tool_call_id:
        result["tool_call_id"] = message.tool_call_id

    return result


class DashScopeProvider(BaseProvider):
    def __init__(
            self,
            model: str,
            api_key: str | None = None,
            base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
    ):
        self.model = model
        key = api_key or os.getenv("DASHSCOPE_API_KEY")
        if not key:
            logger.error("[配置] 未找到 DASHSCOPE_API_KEY")
            raise ValueError("缺少 API Key：请设置环境变量 DASHSCOPE_API_KEY 或在 .env 中配置")
        self.api_key = key
        self.base_url = base_url.rstrip("/")

    def invoke(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        enable_thinking: bool = True,
        temperature: float = 0.7,
        timeout: float = 90,
        max_tokens: int = 4096,
    ) -> ChatResponse:

        tools = tools if tools is not None else []

        logger.info(f"[请求] {len(messages)} 条消息, {len(tools)} 个工具")

        payload = {
            "model": self.model,
            "messages": [_to_api_message(m) for m in messages],
            "enable_thinking": enable_thinking,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools

        logger.debug(f"[配置] model={self.model} thinking={enable_thinking} temp={temperature}")

        start = time.perf_counter()
        resp = httpx.post(
            f"{self.base_url}/chat/completions",
            headers = {"Authorization": f"Bearer {self.api_key}"},
            json = payload,
            timeout = timeout,
        )
        elapsed = time.perf_counter() - start
        logger.info(f"[响应] {resp.status_code}, 耗时 {elapsed:.2f}s")

        if resp.status_code != 200:
            logger.error(
                f"[错误] HTTP {resp.status_code}: {resp.text[:300]}"
            )

            if resp.status_code == 400:
                try:
                    error_data = resp.json()
                    error = error_data.get("error", {})

                    if error.get("code") == "data_inspection_failed":
                        raise ContentInspectionError(
                            f"DashScope 内容安全审核失败: {error.get('message')}"
                        )

                except ValueError:
                    pass

            raise RuntimeError(
                f"DashScope 返回 {resp.status_code}: {resp.text[:300]}"
            )

        try:
            data = resp.json()
        except Exception as e:
            logger.error(f"[解析] 响应不是合法 JSON: {e} | 原文: {resp.text[:300]}")
            raise RuntimeError(f"DashScope 响应无法解析为 JSON: {e}") from e
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            logger.error(f"[解析] 响应缺少 choices 或为空: {json.dumps(data, ensure_ascii=False)[:300]}")
            raise RuntimeError(f"DashScope 响应结构异常：choices 缺失或为空")

        choice = choices[0]
        msg = choice.get("message")
        if not isinstance(msg, dict):
            logger.error(f"[解析] choice 里没有 message: {json.dumps(choice, ensure_ascii=False)[:300]}")
            raise RuntimeError("DashScope 响应结构异常：缺少 message")

        tool_calls = []
        for c in msg.get("tool_calls") or []:
            raw_args = c["function"]["arguments"]
            args, parse_error = parse_tool_arguments(raw_args)
            if parse_error:
                logger.warning(f"[解析] {c['function']['name']} 的参数无效: {parse_error} | 原文: {str(raw_args)[:200]}")

            tool_calls.append(
                ToolCall(
                    id=c["id"],
                    name=c["function"]["name"],
                    arguments=args,
                    parse_error=parse_error,
                )
            )

        token = data.get("usage")

        logger.info(f"[模型] finish_reason={choice.get('finish_reason', '')}, 工具调用 {len(tool_calls)} 个")
        for c in tool_calls:
            logger.info(f"  → {c.name}({c.arguments})")

        return ChatResponse(
            content=msg.get("content") or "",
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason", ""),
            reasoning=msg.get("reasoning_content"),
            token_usage=token,
        )

    def stream(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        enable_thinking: bool = True,
        temperature: float = 0.7,
        timeout: float = 90,
        max_tokens: int = 4096,
    ) -> Iterator[dict[str, Any]]:
        """流式调用 DashScope，产出文本增量、完整工具调用和结束事件。

        工具调用只负责解析并返回，不会在 Provider 内执行。事件类型为：
        ``text_delta``（content）、``tool_call``（tool_call）、``reasoning_delta``（content）和
        ``done``（finish_reason、token_usage）。
        """
        tools = tools if tools is not None else []
        logger.info(f"[流式请求] {len(messages)} 条消息, {len(tools)} 个工具")

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [_to_api_message(message) for message in messages],
            "enable_thinking": enable_thinking,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            payload["tools"] = tools

        # Chat Completions streams may split a tool call across many chunks.
        tool_call_parts: dict[int, dict[str, str]] = {}
        finish_reason = ""
        token_usage: dict[str, Any] | None = None
        stream_finished = False
        start = time.perf_counter()

        with httpx.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
            timeout=timeout,
        ) as resp:
            if resp.status_code != 200:
                # Read the streaming response before accessing .text.
                body = resp.read().decode("utf-8", errors="replace")
                logger.error(f"[流式错误] HTTP {resp.status_code}: {body[:300]}")
                raise RuntimeError(f"DashScope 返回 {resp.status_code}: {body[:300]}")

            data_lines: list[str] = []

            def process_event(raw_data: str) -> bool:
                """处理一个 SSE data 字段；返回是否收到 [DONE]。"""
                nonlocal finish_reason, token_usage
                if raw_data.strip() == "[DONE]":
                    return True
                if not raw_data.strip():
                    return False

                try:
                    chunk = json.loads(raw_data)
                except json.JSONDecodeError as exc:
                    logger.error(f"[流式解析] SSE 数据不是合法 JSON: {exc} | 原文: {raw_data[:300]}")
                    raise RuntimeError(f"DashScope 流式响应无法解析为 JSON: {exc}") from exc

                if not isinstance(chunk, dict):
                    raise RuntimeError("DashScope 流式响应结构异常：数据块不是 JSON 对象")
                error = chunk.get("error")
                if error:
                    detail = error.get("message", str(error)) if isinstance(error, dict) else str(error)
                    logger.error(f"[流式错误] DashScope 服务端错误: {detail}")
                    raise RuntimeError(f"DashScope 流式请求失败: {detail}")

                usage = chunk.get("usage")
                if isinstance(usage, dict):
                    token_usage = usage

                choices = chunk.get("choices") or []
                if not isinstance(choices, list):
                    raise RuntimeError("DashScope 流式响应结构异常：choices 不是列表")

                for choice in choices:
                    if not isinstance(choice, dict):
                        continue
                    reason = choice.get("finish_reason")
                    if reason is not None:
                        finish_reason = str(reason)

                    delta = choice.get("delta") or {}
                    if not isinstance(delta, dict):
                        continue

                    # Intentionally ignore reasoning_content so it is never
                    # exposed through the user-facing stream.
                    reasoning = delta.get("reasoning_content")
                    if isinstance(reasoning, str) and reasoning:
                        pending_events.append({
                            "type": "reasoning_delta",
                            "content": reasoning,
                        })

                    content = delta.get("content")
                    if isinstance(content, str) and content:
                        yield_event = {"type": "text_delta", "content": content}
                        pending_events.append(yield_event)

                    for call_delta in delta.get("tool_calls") or []:
                        if not isinstance(call_delta, dict):
                            continue
                        index = call_delta.get("index")
                        if not isinstance(index, int):
                            logger.warning(f"[流式解析] 工具调用分片缺少有效 index: {call_delta}")
                            continue

                        part = tool_call_parts.setdefault(index, {"id": "", "name": "", "arguments": ""})
                        call_id = call_delta.get("id")
                        if isinstance(call_id, str) and call_id:
                            part["id"] += call_id

                        function = call_delta.get("function") or {}
                        if not isinstance(function, dict):
                            continue
                        name = function.get("name")
                        if isinstance(name, str) and name:
                            part["name"] += name
                        arguments = function.get("arguments")
                        if isinstance(arguments, str):
                            part["arguments"] += arguments
                        elif isinstance(arguments, dict):
                            part["arguments"] += json.dumps(arguments, ensure_ascii=False)

                return False

            # Keep the SSE parser local to this request. Events are buffered
            # per packet so tool-call fragments can be merged before yielding.
            pending_events: list[dict[str, Any]] = []

            def consume_event(raw_data: str) -> bool:
                # process_event queues text deltas while updating shared state.
                return process_event(raw_data)

            for raw_line in resp.iter_lines():
                if isinstance(raw_line, bytes):
                    line = raw_line.decode("utf-8", errors="replace")
                else:
                    line = raw_line

                if not line:
                    if data_lines:
                        stream_finished = consume_event("\n".join(data_lines))
                        data_lines.clear()
                        for event in pending_events:
                            yield event
                        pending_events.clear()
                        if stream_finished:
                            break
                    continue

                # Ignore SSE comments, event names, and other metadata lines.
                if line.startswith(":") or not line.startswith("data:"):
                    continue
                data = line[5:]
                if data.startswith(" "):
                    data = data[1:]
                data_lines.append(data)

            # Some servers close the connection without the final blank line.
            if data_lines and not stream_finished:
                stream_finished = consume_event("\n".join(data_lines))
                for event in pending_events:
                    yield event
                pending_events.clear()

        elapsed = time.perf_counter() - start
        logger.info(f"[流式响应] 完成，耗时 {elapsed:.2f}s, finish_reason={finish_reason}")

        tool_calls: list[ToolCall] = []

        for index in sorted(tool_call_parts):
            part = tool_call_parts[index]
            arguments, parse_error = parse_tool_arguments(part["arguments"])
            if parse_error:
                logger.warning(
                    f"[流式解析] {part['name']} 的参数无效: {parse_error} | 原文: {part['arguments'][:200]}"
                )

            tool_call = ToolCall(
                id=part["id"],
                name=part["name"],
                arguments=arguments,
                parse_error=parse_error,
            )
            tool_calls.append(tool_call)

            logger.info(f"  → {tool_call.name}({tool_call.arguments})")
            yield {
                "type": "tool_call",
                "tool_call": tool_call,
            }

        logger.info(
            f"[模型] finish_reason={finish_reason}, 工具调用 {len(tool_calls)} 个"
        )

        yield {
            "type": "done",
            "finish_reason": finish_reason,
            "token_usage": token_usage,
        }



if __name__ == '__main__':
    from agent.tools.weather import WeatherTool
    from rich import print as rprint

    model = DashScopeProvider(model="qwen3.7-flash")
    message = [
        ChatMessage(
            role="user",
            content=[
                {"type": "text", "text": "帮我查一查今天南昌的天气"}
            ]
        )
    ]
    # rprint(model.invoke(message, tools=[WeatherTool().to_schema()], enable_thinking=False))
    chunks = model.stream(message, tools=[WeatherTool().to_schema()], enable_thinking=False)
    # rprint(chunks)
    for chunk in chunks:
        # rprint(chunk)
        if chunk["type"] == "reasoning_delta":
            print(chunk.get("content"), end="", flush=True)
        elif chunk["type"] == "text_delta":
            print(chunk.get("content"), end="", flush=True)
        else:
            print()
            rprint(chunk)
        # if chunk.get("type") == "done":
        #     rprint(chunk)