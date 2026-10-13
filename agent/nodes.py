import re
import time
from typing import Any
from langgraph.config import get_stream_writer
from models.base import BaseProvider, ChatMessage, ChatResponse
from agent.state import AgentState, OutputState
from agent.tools.registry import ToolRegistry
from agent.tools.executor import execute_tool
# from models.dashscope.Qwen_model import DashScopeProvider
# from models.openai.ChatGPT import OpenAIProvider
from .summarizer import Summarizer
from utils.logger_tool import logger
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

_COMPACT_TRIGGER = 0.6
_KEEP_RECENT_TURNS = 3
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")



def _add_total(prev: int | None, usage: dict[str, Any] | None) -> int:
    """累加本轮 token 消耗。只取 total_tokens —— 它已含 prompt + completion，
    且是整数，顺带避开 prompt_tokens_details 这类嵌套结构。"""
    value = (usage or {}).get("total_tokens")
    return (prev or 0) + (value if isinstance(value, int) else 0)

def _dangling_results(messages: list[ChatMessage]) -> list[ChatMessage]:
    """补齐历史里“有 tool_calls、没 tool 结果”的缺口。

    客户端中断、tool_node 抛异常、fallback 总结失败等情况下，
    checkpoint 可能停在这种断裂状态，下一次请求会被模型接口拒绝。
    """
    answered = {m.tool_call_id for m in messages if m.role == "tool"}
    return [
        ChatMessage(
            role="tool",
            tool_call_id=tc.id,
            content=[{"type": "text", "text": "该工具调用被中断，未得到结果。"}],
        )
        for m in messages
        if m.role == "assistant"
        for tc in (getattr(m, "tool_calls", None) or [])
        if tc.id not in answered
    ]

def _estimate_tokens(messages: list[ChatMessage], start: int = 0) -> int:
    """没有 usage 时的粗略估算：CJK 约 1 token/字，其余约 1 token/4 字符。"""
    total = 0
    for message in messages[start:]:
        for part in message.content:
            text = part.get("text") if isinstance(part, dict) else None
            if not text:
                continue
            cjk = len(_CJK_RE.findall(text))
            total += cjk + (len(text) - cjk) // 4
        for tool_call in (message.tool_calls or []):
            total += len(str(tool_call.arguments)) // 4
    return total


def _find_compact_upto(messages: list[ChatMessage], keep_turns: int) -> int | None:
    """折叠边界：该下标起原样保留，之前的并入摘要。

    边界只能取 user 消息的下标。assistant 的 tool_calls 与紧随其后的
    tool 结果是一组，从中间切开会被模型接口拒绝——所以不能按消息计数切。
    """
    seen = 0
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].role != "user":
            continue
        seen += 1
        if seen > keep_turns:
            return i
    return None

def create_nodes(
    model: BaseProvider,
    registry: ToolRegistry,
    prompts: str | None,
    default_max_turns: int,
    summarizer: Summarizer,
    context_window: int,
) -> dict[str, Any]:

    def input_node(state: AgentState) -> AgentState:
        user_message = ChatMessage(
            role="user",
            content=state["query"],
        )

        return {
            "messages": [*_dangling_results(state.get("messages", [])), user_message],
            "max_turns": state.get("max_turns", default_max_turns),
            "turn_count": 0,
            "timeout": state.get("timeout", 60),
            "reasoning": state.get("reasoning"),
            "started_at": time.time(),
            "total_tokens": 0,
        }

    def llm_node(state: AgentState) -> AgentState:

        summary = state.get("summary")
        system_text = (
            f"# 【重要背景】当前会话时间戳："
            f"{datetime.now().strftime('%Y年%m月%d日 %H时%M分%S秒')}"
        )
        if prompts:
            system_text += f"\n{prompts}"
        if summary:
            system_text += (
                "\n\n# 【较早对话的摘要】\n"
                "以下是本次会话较早部分（已从上下文中省略）的摘要，仅作背景参考：\n"
                f"{summary}"
            )

        system_message = ChatMessage(
            role="system",
            content=[{"type": "text", "text": system_text}],
        )

        writer = get_stream_writer()

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls = []
        finish_reason = ""
        token_usage = None

        # 摘要放系统消息里，历史窗口从 summary_upto 起，前端拿到的完整历史不受影响
        messages = [system_message, *state["messages"][state.get("summary_upto", 0):]]

        stream_kwargs = {
            "messages": messages,
            "tools": registry.get_schemas(),
            **model.reasoning_kwargs(state.get("reasoning")),
        }

        events = model.stream(**stream_kwargs)

        for event in events:
            event_type = event.get("type")

            if event_type == "reasoning_delta":
                chunk = event.get("content", "")
                if chunk:
                    reasoning_parts.append(chunk)
                    writer({
                        "type": "reasoning_delta",
                        "content": chunk,
                    })

            elif event_type == "text_delta":
                chunk = event.get("content", "")
                if chunk:
                    content_parts.append(chunk)
                    writer({
                        "type": "text_delta",
                        "content": chunk,
                    })

            elif event_type == "tool_call":
                tool_call = event.get("tool_call", "")
                tool_calls.append(tool_call)

                writer({
                    "type": "tool_call",
                    "name": tool_call.name,
                    "arguments": tool_call.arguments,
                    "tool_call_id": tool_call.id
                })

            elif event_type == "done":
                finish_reason = event.get("finish_reason", "")
                token_usage = event.get("token_usage")

        response = ChatResponse(
            content="".join(content_parts),
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            reasoning="".join(reasoning_parts) or None,
            token_usage=token_usage,
        )

        assistant_message = ChatMessage(
            role="assistant",
            content=[{"type": "text", "text": response.content}],
            tool_calls=response.tool_calls,
            token_usage=response.token_usage,
        )

        return {
            "messages": [assistant_message],
            "last_response": response,
            "turn_count": state.get("turn_count", 0) + 1,
            "total_tokens": _add_total(state.get("total_tokens"), response.token_usage),  # ← 新增
        }

    def tool_node(state: AgentState) -> AgentState:
        writer = get_stream_writer()
        tool_calls = state["last_response"].tool_calls

        def run_one(tool_call):
            writer({
                "type": "tool_started",
                "name": tool_call.name,
                "tool_call_id": tool_call.id,
            })
            start = time.perf_counter()
            outcome = execute_tool(registry, tool_call)
            elapsed = time.perf_counter() - start
            writer({
                "type": "tool_finished",
                "name": tool_call.name,
                "status": outcome.status,
                "tool_call_id": tool_call.id,
                "elapsed_ms": int(elapsed * 1000),
                "sources": outcome.sources,
            })
            return ChatMessage(
                role="tool",
                content=[{"type": "text", "text": outcome.content}],
                tool_call_id=tool_call.id,
            )

        if len(tool_calls) <= 1:
            tool_messages = [run_one(tc) for tc in tool_calls]
        else:
            with ThreadPoolExecutor(max_workers=len(tool_calls)) as pool:
                tool_messages = list(pool.map(run_one, tool_calls))

        return {
            "messages": tool_messages
        }

    def fallback_node(state: AgentState) -> OutputState:
        writer = get_stream_writer()
        last = state["last_response"]

        logger.warning("达到 max_turns=%s，转入兜底总结", state.get("max_turns"))

        placeholder_messages = [
            ChatMessage(
                role="tool",
                content=[{"type": "text", "text": "达到最大轮数，该工具未被执行。"}],
                tool_call_id=tool_call.id,
            )
            for tool_call in last.tool_calls
        ]

        streamed: list[str] = []

        def _emit(chunk: str) -> None:
            streamed.append(chunk)
            writer({"type": "text_delta", "content": chunk})

        try:
            summary, token_usage = summarizer.run(
                messages=[*state["messages"], *placeholder_messages],
                instruction=(
                    "本轮任务已经达到最大工具调用轮数，不能再调用任何工具。"
                    "【强约束】首先必须告知用户：本轮任务已达到最大工具调用轮数，以下是本轮已执行得到的结果等字样"
                    "请只依据上面的工具执行结果，用简洁的中文总结本轮到目前为止查到的信息，"
                    "直接给出对用户有用的结论；缺少的信息要说明缺什么，不要编造。"
                ),
                on_delta=_emit,
            )
        except Exception:
            logger.exception("兜底总结失败")
            summary, token_usage = "".join(streamed), None

        if not summary.strip():
            summary = "这次查询的轮数已达上限，没能整理出结果。请换个问法，或稍后再试。"
            _emit(summary)

        final_answer = ChatResponse(
            content=summary,
            tool_calls=[],
            finish_reason="max_turns_exceeded",
            reasoning=None,
            token_usage=token_usage,
        )

        total_tokens = _add_total(state.get("total_tokens"), token_usage)
        writer({
            "type": "done",
            "final_answer": {
                "content": final_answer.content,
                "reasoning": final_answer.reasoning,
                "finish_reason": final_answer.finish_reason,
                "token_usage": final_answer.token_usage,
                "total_tokens": total_tokens,
                "elapsed_ms": int(
                    (time.time() - state.get("started_at", time.time())) * 1000
                ),
            },
        })

        return {
            "messages": [
                *placeholder_messages,
                ChatMessage(role="assistant", content=[{"type": "text", "text": final_answer.content}]),
            ],
            "final_answer": final_answer,
        }

    def output_node(state: AgentState) -> OutputState:
        response = state["last_response"]
        writer = get_stream_writer()

        writer({
            "type": "done",
            "final_answer": {
                "content": response.content,
                "reasoning": response.reasoning,
                "finish_reason": response.finish_reason,
                "token_usage": response.token_usage,                    # 最后一次调用（保留）
                "total_tokens": state.get("total_tokens", 0),           # ← 本轮累计
                "elapsed_ms": int(
                    (time.time() - state.get("started_at", time.time())) * 1000
                ),                                                      # ← 整轮耗时
            },
        })

        return {
            "final_answer": response,
        }

    def compact_node(state: AgentState) -> AgentState:
        messages = state.get("messages", [])
        summary_upto = state.get("summary_upto", 0)

        response = state.get("last_response")
        usage = (response.token_usage if response else None) or {}
        prompt_tokens = usage.get("prompt_tokens")

        used = (
            prompt_tokens
            if isinstance(prompt_tokens, int)
            else _estimate_tokens(messages, summary_upto)
        )
        if used < context_window * _COMPACT_TRIGGER:
            return {}

        boundary = _find_compact_upto(messages, _KEEP_RECENT_TURNS)
        if boundary is None or boundary <= summary_upto:
            return {}

        old_summary = state.get("summary") or ""
        start = time.perf_counter()
        logger.info(f"正在压缩摘要...")
        new_summary, _ = summarizer.run(
            messages=messages[summary_upto:boundary],
            instruction=(
                (f"【已有摘要】\n{old_summary}\n\n" if old_summary else "")
                + "请把【已有摘要】与上面的新增对话合并成一份新的滚动摘要。\n"
                "保留：用户目标与约束、已确认的结论、关键事实与数据、仍未解决的问题。\n"
                "丢弃：寒暄、重复表述、已被推翻的中间过程。\n"
                "直接输出摘要正文，不要加前缀，不要编造材料中没有的信息。"
            ),
        )
        if not new_summary.strip():
            return {}          # 摘要失败就保留旧摘要，下轮再试

        logger.info(
            "历史压缩：折叠 messages[%d:%d]，新摘要 %d 字，耗时 %d",
            summary_upto, boundary, len(new_summary), time.perf_counter() - start,
        )
        return {"summary": new_summary, "summary_upto": boundary}

    return {
        "input_node": input_node,
        "llm_node": llm_node,
        "tool_node": tool_node,
        "fallback_node": fallback_node,
        "output_node": output_node,
        "compact_node": compact_node,
    }