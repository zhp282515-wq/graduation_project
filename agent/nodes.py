from typing import Any
from langgraph.config import get_stream_writer
from models.base import BaseProvider, ChatMessage, ChatResponse
from agent.state import AgentState, OutputState
from agent.tools.registry import ToolRegistry
from agent.tools.executor import execute_tool
from models.dashscope.Qwen_model import DashScopeProvider
from models.openai.ChatGPT import OpenAIProvider
from .summarizer import Summarizer
from utils.logger_tool import logger


def create_nodes(
    model: BaseProvider,
    registry: ToolRegistry,
    system_message: ChatMessage,
    default_max_turns: int,
    summarizer: Summarizer,
) -> dict[str, Any]:

    def input_node(state: AgentState) -> AgentState:
        user_message = ChatMessage(
            role="user",
            content=state["query"],
        )

        return {
            "messages": [user_message],
            "max_turns": state.get("max_turns", default_max_turns),
            "turn_count": 0,
            "timeout": state.get("timeout", 60),
            "enable_thinking": state.get("enable_thinking", False),
            "reasoning_effort": state.get("reasoning_effort", "none"),
        }

    def llm_node(state: AgentState) -> AgentState:
        writer = get_stream_writer()

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls = []
        finish_reason = ""
        token_usage = None

        messages = [system_message, *state["messages"]]

        stream_kwargs = {
            "messages": messages,
            "tools": registry.get_schemas(),
        }

        if isinstance(model, DashScopeProvider):
            stream_kwargs["enable_thinking"] = state.get(
                "enable_thinking", False
            )

        elif isinstance(model, OpenAIProvider):
            stream_kwargs["reasoning_effort"] = state.get(
                "reasoning_effort", "none"
            )

        else:
            raise TypeError(
                f"不支持的模型 Provider: {type(model).__name__}"
            )

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
        }

    def tool_node(state: AgentState) -> AgentState:
        writer = get_stream_writer()
        tool_messages = []

        for tool_call in state["last_response"].tool_calls:
            writer({
                "type": "tool_started",
                "name": tool_call.name,
            })

            outcome = execute_tool(registry, tool_call)

            writer({
                "type": "tool_finished",
                "name": tool_call.name,
                "status": outcome.status,
            })

            tool_messages.append(
                ChatMessage(
                    role="tool",
                    content=[{"type": "text", "text": outcome.content}],
                    tool_call_id=tool_call.id,
                )
            )

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

        summary, token_usage = summarizer.run(
            messages=[*state["messages"], *placeholder_messages],
            instruction=(
                "本轮任务已经达到最大工具调用轮数，不能再调用任何工具。"
                "【强约束】首先必须告知用户：本轮任务已达到最大工具调用轮数，以下是本轮已执行得到的结果等字样"
                "请只依据上面的工具执行结果，用简洁的中文总结本轮到目前为止查到的信息，"
                "直接给出对用户有用的结论；缺少的信息要说明缺什么，不要编造。"
            ),
            on_delta=lambda chunk: writer({"type": "text_delta", "content": chunk}),
        )

        final_answer = ChatResponse(
            content=summary,
            tool_calls=[],
            finish_reason="max_turns_exceeded",
            reasoning=None,
            token_usage=token_usage,
        )

        writer({
            "type": "done",
            "final_answer": {
                "content": final_answer.content,
                "reasoning": final_answer.reasoning,
                "finish_reason": final_answer.finish_reason,
                "token_usage": final_answer.token_usage,
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
                "token_usage": response.token_usage,
            },
        })

        return {
            "final_answer": response,
        }

    return {
        "input_node": input_node,
        "llm_node": llm_node,
        "tool_node": tool_node,
        "fallback_node": fallback_node,
        "output_node": output_node,
    }