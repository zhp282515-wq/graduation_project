from typing import Any, Iterator
import json
import time

from models.base import BaseProvider, ChatMessage, ChatResponse, ToolCall, parse_tool_arguments
import httpx
from utils.logger_tool import logger
import os
from dotenv import load_dotenv
load_dotenv(override=True)
from rich import print as rprint


def _content_text(content: Any) -> str:
    """从内部消息内容中提取文本，供 Responses API 的工具结果使用。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )
    return str(content or "")


def _to_responses_input(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    """将内部消息转换为 Responses API 的 input 项。"""
    items: list[dict[str, Any]] = []

    for message in messages:
        # Responses API 使用 function_call_output 表示工具执行结果。
        if message.tool_call_id:
            items.append({
                "type": "function_call_output",
                "call_id": message.tool_call_id,
                "output": _content_text(message.content),
            })
            continue

        text_parts: list[str] = []
        other_parts: list[dict[str, Any]] = []
        for part in message.content or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                text_parts.append(part.get("text", ""))
            elif part.get("type") == "image_url":
                image_url = part.get("image_url", {})
                other_parts.append({
                    "type": "input_image",
                    "image_url": image_url.get("url", "") if isinstance(image_url, dict) else image_url,
                })
            else:
                other_parts.append(part)

        content: Any = "".join(text_parts)
        if other_parts:
            content = ([{"type": "input_text", "text": content}] if content else []) + other_parts

        if content or not message.tool_calls:
            items.append({"role": message.role, "content": content})

        # Responses API uses standalone function_call input items.
        for tool_call in message.tool_calls or []:
            items.append({
                "type": "function_call",
                "call_id": tool_call.id,
                "name": tool_call.name,
                "arguments": json.dumps(tool_call.arguments, ensure_ascii=False),
            })

    return items


def _to_responses_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """将 Chat Completions 函数工具 Schema 转为 Responses API 格式。"""
    converted = []
    for tool in tools:
        function = tool.get("function") or {}
        if tool.get("type") == "function" and function:
            converted.append({
                "type": "function",
                "name": function.get("name", ""),
                "description": function.get("description", ""),
                "parameters": function.get("parameters", {"type": "object", "properties": {}}),
                **({"strict": function["strict"]} if "strict" in function else {}),
            })
        else:
            converted.append(tool)
    return converted


class OpenAIProvider(BaseProvider):
    def __init__(
            self,
            model: str,
            api_key: str | None = None,
            base_url: str = "https://api.openai-proxy.org/v1",
    ):
        self.model = model
        key = api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            logger.error("[配置] 未找到 OPENAI_API_KEY")
            raise ValueError("缺少 API Key：请设置环境变量 OPENAI_API_KEY 或在 .env 中配置")
        self.api_key = key
        self.base_url = base_url.rstrip("/")

    def invoke(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        timeout: float = 90,
        reasoning_effort: str = "high",
    ) -> ChatResponse:

        tools = tools if tools is not None else []
        logger.info(f"[请求] {len(messages)} 条消息, {len(tools)} 个工具")

        payload = {
            "model": self.model,
            "input": _to_responses_input(messages),
            "reasoning": {"effort": reasoning_effort},
        }
        if tools:
            payload["tools"] = _to_responses_tools(tools)

        logger.debug(f"[配置] model={self.model} reasoning_effort={reasoning_effort}")

        start = time.perf_counter()
        resp = httpx.post(
            f"{self.base_url}/responses",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout,
        )
        elapsed = time.perf_counter() - start
        logger.info(f"[响应] {resp.status_code}, 耗时 {elapsed:.2f}s")

        if resp.status_code != 200:
            logger.error(f"[错误] HTTP {resp.status_code}: {resp.text[:300]}")
            raise RuntimeError(f"OpenAI Responses API 返回 {resp.status_code}: {resp.text[:300]}")

        try:
            data = resp.json()
        except Exception as e:
            logger.error(f"[解析] 响应不是合法 JSON: {e} | 原文: {resp.text[:300]}")
            raise RuntimeError(f"OpenAI Responses API 响应无法解析为 JSON: {e}") from e

        output = data.get("output")
        if not isinstance(output, list):
            logger.error(f"[解析] 响应缺少 output: {json.dumps(data, ensure_ascii=False)[:300]}")
            raise RuntimeError("OpenAI Responses API 响应结构异常：缺少 output")

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls = []
        for item in output:
            item_type = item.get("type")
            if item_type == "message":
                for part in item.get("content") or []:
                    if part.get("type") == "output_text":
                        content_parts.append(part.get("text", ""))
            elif item_type == "reasoning":
                for summary in item.get("summary") or []:
                    if summary.get("type") == "summary_text":
                        reasoning_parts.append(summary.get("text", ""))
            elif item_type == "function_call":
                arguments, parse_error = parse_tool_arguments(item.get("arguments"))
                if parse_error:
                    logger.warning(f"[解析] {item.get('name', '')} 的参数无效: {parse_error}")

                tool_calls.append(ToolCall(
                    id=item.get("call_id", item.get("id", "")),
                    name=item.get("name", ""),
                    arguments=arguments,
                    parse_error=parse_error,
                ))

        finish_reason = "tool_calls" if tool_calls else (
            "stop" if data.get("status") == "completed" else data.get("status", "")
        )
        logger.info(f"[模型] finish_reason={finish_reason}, 工具调用 {len(tool_calls)} 个")
        for call in tool_calls:
            logger.info(f"  → {call.name}({call.arguments})")

        return ChatResponse(
            content="".join(content_parts),
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            reasoning="\n".join(reasoning_parts) or None,
            token_usage=data.get("usage"),
        )

    def stream(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        timeout: float = 90,
        reasoning_effort: str = "high",
    ) -> Iterator[dict[str, Any]]:
        """Stream Responses API output using the provider-neutral event shape.

        Events are ``reasoning_delta`` (content), ``text_delta`` (content),
        ``tool_call`` (tool_call), and ``done`` (finish_reason, token_usage).
        Tool calls are emitted only after their arguments have been assembled.
        """
        tools = tools if tools is not None else []
        logger.info(f"[流式请求] {len(messages)} 条消息, {len(tools)} 个工具")

        payload: dict[str, Any] = {
            "model": self.model,
            "input": _to_responses_input(messages),
            "reasoning": {
                "effort": reasoning_effort,
                "summary": "auto",
            },
            "stream": True,
        }
        if tools:
            payload["tools"] = _to_responses_tools(tools)

        def parse_sse_data(raw_data: str) -> dict[str, Any] | None:
            if not raw_data.strip():
                return None
            if raw_data.strip() == "[DONE]":
                return {"type": "__done_sentinel__"}

            try:
                event = json.loads(raw_data)
            except json.JSONDecodeError as exc:
                logger.error(
                    "[流式解析] SSE 数据不是合法 JSON: %s | 原文: %s",
                    exc,
                    raw_data[:300],
                )
                raise RuntimeError(
                    f"OpenAI Responses API 流式数据无法解析为 JSON: {exc}"
                ) from exc

            if not isinstance(event, dict):
                raise RuntimeError("OpenAI Responses API 流式响应结构异常：事件不是 JSON 对象")
            return event

        def iter_sse_events(response: httpx.Response) -> Iterator[dict[str, Any]]:
            """Parse SSE data fields, including events split across data lines."""
            data_lines: list[str] = []

            for raw_line in response.iter_lines():
                line = (
                    raw_line.decode("utf-8", errors="replace")
                    if isinstance(raw_line, bytes)
                    else raw_line
                )

                if not line:
                    if data_lines:
                        event = parse_sse_data("\n".join(data_lines))
                        data_lines.clear()
                        if event is not None:
                            yield event
                    continue

                # SSE comments, event labels, IDs, and retry metadata do not
                # carry the JSON payload used by the Responses API parser.
                if line.startswith(":") or not line.startswith("data:"):
                    continue

                data = line[5:]
                if data.startswith(" "):
                    data = data[1:]
                data_lines.append(data)

            # Some compatible endpoints close without a trailing blank line.
            if data_lines:
                event = parse_sse_data("\n".join(data_lines))
                if event is not None:
                    yield event

        tool_call_parts: dict[str, dict[str, Any]] = {}
        tool_call_order: list[str] = []
        finish_reason = ""
        token_usage: dict[str, Any] | None = None
        response_status = ""
        terminal_event_received = False
        start = time.perf_counter()

        def get_tool_call_part(
            item_id: Any,
            output_index: Any = None,
        ) -> tuple[str, dict[str, Any]]:
            if isinstance(item_id, str) and item_id:
                key = item_id
            elif isinstance(output_index, int):
                key = f"output:{output_index}"
            else:
                raise RuntimeError(
                    "OpenAI Responses API 工具调用事件缺少 item_id 和 output_index"
                )

            if key not in tool_call_parts:
                tool_call_parts[key] = {
                    "item_id": item_id if isinstance(item_id, str) else "",
                    "output_index": output_index if isinstance(output_index, int) else None,
                    "call_id": "",
                    "name": "",
                    "argument_deltas": [],
                    "complete_arguments": None,
                }
                tool_call_order.append(key)

            return key, tool_call_parts[key]

        def register_function_call_item(
            item: Any,
            output_index: Any = None,
            *,
            complete: bool = False,
        ) -> None:
            if not isinstance(item, dict) or item.get("type") != "function_call":
                return

            item_id = item.get("id")
            item_index = item.get("output_index", output_index)
            _, part = get_tool_call_part(item_id, item_index)

            call_id = item.get("call_id")
            name = item.get("name")
            if isinstance(call_id, str) and call_id:
                part["call_id"] = call_id
            if isinstance(name, str) and name:
                part["name"] = name

            arguments = item.get("arguments")
            if complete and arguments is not None:
                part["complete_arguments"] = arguments
            elif (
                arguments not in (None, "")
                and not part["argument_deltas"]
                and part["complete_arguments"] is None
            ):
                # Accommodate compatible endpoints that include arguments in
                # output_item.added instead of sending argument delta events.
                part["complete_arguments"] = arguments

        def apply_api_event(event: dict[str, Any]) -> list[dict[str, Any]]:
            nonlocal finish_reason, token_usage, response_status
            nonlocal terminal_event_received

            event_type = event.get("type")
            if event_type == "error":
                error = event.get("error", event)
                detail = error.get("message", str(error)) if isinstance(error, dict) else str(error)
                raise RuntimeError(f"OpenAI Responses API 流式请求失败: {detail}")

            if event_type == "response.failed":
                failed_response = event.get("response") or {}
                error = failed_response.get("error") if isinstance(failed_response, dict) else None
                detail = error.get("message", str(error)) if isinstance(error, dict) else str(error or event)
                raise RuntimeError(f"OpenAI Responses API 生成失败: {detail}")

            output_events: list[dict[str, Any]] = []

            if event_type == "response.reasoning_summary_text.delta":
                delta = event.get("delta")
                if isinstance(delta, str) and delta:
                    output_events.append({"type": "reasoning_delta", "content": delta})

            elif event_type == "response.output_text.delta":
                delta = event.get("delta")
                if isinstance(delta, str) and delta:
                    output_events.append({"type": "text_delta", "content": delta})

            elif event_type in ("response.output_item.added", "response.output_item.done"):
                register_function_call_item(
                    event.get("item"),
                    event.get("output_index"),
                    complete=event_type == "response.output_item.done",
                )

            elif event_type == "response.function_call_arguments.delta":
                _, part = get_tool_call_part(
                    event.get("item_id"),
                    event.get("output_index"),
                )
                delta = event.get("delta")
                if isinstance(delta, str):
                    part["argument_deltas"].append(delta)

            elif event_type == "response.function_call_arguments.done":
                _, part = get_tool_call_part(
                    event.get("item_id"),
                    event.get("output_index"),
                )
                if "arguments" in event:
                    part["complete_arguments"] = event["arguments"]

            elif event_type in ("response.completed", "response.incomplete"):
                response_data = event.get("response") or {}
                if not isinstance(response_data, dict):
                    raise RuntimeError("OpenAI Responses API 结束事件缺少 response 对象")

                response_status = response_data.get("status") or (
                    "incomplete" if event_type == "response.incomplete" else "completed"
                )
                usage = response_data.get("usage")
                if isinstance(usage, dict):
                    token_usage = usage

                for output_index, item in enumerate(response_data.get("output") or []):
                    register_function_call_item(item, output_index, complete=True)

                terminal_event_received = True

            return output_events

        with httpx.stream(
            "POST",
            f"{self.base_url}/responses",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout,
        ) as response:
            if response.status_code != 200:
                body = response.read().decode("utf-8", errors="replace")
                logger.error("[流式错误] HTTP %s: %s", response.status_code, body[:300])
                raise RuntimeError(
                    f"OpenAI Responses API 返回 {response.status_code}: {body[:300]}"
                )

            for event in iter_sse_events(response):
                if event.get("type") == "__done_sentinel__":
                    break

                for output_event in apply_api_event(event):
                    yield output_event

                if terminal_event_received:
                    break

        if not terminal_event_received:
            raise RuntimeError("OpenAI Responses API 流在收到完成或 incomplete 事件前结束")

        elapsed = time.perf_counter() - start

        # A function call is usable only after the response has completed.
        # Incomplete responses still produce a done event, but never dispatch
        # partially generated tool arguments to the Agent.
        if response_status == "completed":
            ordered_parts = sorted(
                tool_call_order,
                key=lambda key: (
                    tool_call_parts[key]["output_index"] is None,
                    tool_call_parts[key]["output_index"]
                    if tool_call_parts[key]["output_index"] is not None
                    else tool_call_order.index(key),
                ),
            )

            for key in ordered_parts:
                part = tool_call_parts[key]
                raw_arguments = part["complete_arguments"]
                if raw_arguments is None:
                    raw_arguments = "".join(part["argument_deltas"])

                arguments, parse_error = parse_tool_arguments(raw_arguments)
                if parse_error:
                    logger.warning(
                        "[流式解析] %s 的参数无效: %s | 原文: %s",
                        part["name"], parse_error, str(raw_arguments)[:200],
                    )

                if not part["name"]:
                    raise RuntimeError("OpenAI Responses API 工具调用缺少函数名称")

                tool_call = ToolCall(
                    id=part["call_id"] or part["item_id"],
                    name=part["name"],
                    arguments=arguments,
                    parse_error=parse_error,
                )
                logger.info("  → %s(%s)", tool_call.name, tool_call.arguments)
                yield {
                    "type": "tool_call",
                    "tool_call": tool_call,
                }

        finish_reason = (
            "incomplete"
            if response_status == "incomplete"
            else "tool_calls"
            if tool_call_parts
            else "stop"
        )
        logger.info(
            "[流式响应] 完成，耗时 %.2fs, finish_reason=%s",
            elapsed,
            finish_reason,
        )
        yield {
            "type": "done",
            "finish_reason": finish_reason,
            "token_usage": token_usage,
        }



if __name__ == '__main__':
    from agent.tools.weather import WeatherTool

    model = OpenAIProvider(model="gpt-6-luna")
    message = [
        ChatMessage(
            role="user",
            content=[
                {"type": "text", "text": "你好"}
            ]
        )
    ]
    rprint(model.invoke(message, tools=[WeatherTool().to_schema()]))
    # rprint(WeatherTool().to_schema())
