from datetime import datetime

from langgraph.checkpoint.base import BaseCheckpointSaver
from collections.abc import Iterator
from typing import Any

from models.base import BaseProvider, ChatMessage
from .graph import build_graph
from .nodes import create_nodes
from .state import AgentInput
from .tools.base import BaseTool
from .tools.registry import ToolRegistry
from agent.summarizer import Summarizer


class AgentRuntime:
    def __init__(
        self,
        model: BaseProvider,
        tools: list[BaseTool],
        prompts: str | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        default_max_turns: int = 10,
        summary_model: BaseProvider | None = None,
    ):
        self.default_max_turns = default_max_turns
        current_time = datetime.now().strftime("%Y年%m月%d日 %H时%M分%S秒")

        if prompts is None:
            prompt = f"- 【重要背景】当前会话创建时间戳：{current_time}"
        else:
            prompt = prompts + f"\n- 【重要背景】当前会话创建时间戳：{current_time}"

        system_message = ChatMessage(
            role="system",
            content=[{"type": "text", "text": prompt}],
        )

        summarizer = Summarizer(
            summary_model or model,
            system_prompt="你是一个严谨的总结助手，只依据给定材料作答，不补充或编造材料中没有的信息。",
        )

        registry = ToolRegistry(tools)
        nodes = create_nodes(
            model=model,
            registry=registry,
            system_message=system_message,
            default_max_turns=default_max_turns,
            summarizer=summarizer,
        )
        self.graph = build_graph(nodes, checkpointer=checkpointer)

    def stream(
            self,
            input: AgentInput,
            *,
            session_id: str,
            cancel_event=None,
    ) -> Iterator[dict[str, Any]]:
        """流式执行编译后的 LangGraph，并返回 custom 模式事件。"""
        max_turns = input.get("max_turns", self.default_max_turns)
        # 每个 turn 最多消耗 llm_node + tool_node 两步；再加 input_node、
        # output/fallback_node 的固定开销，留 6 步余量。
        recursion_limit = max_turns * 2 + 6

        yield from self.graph.stream(
            input,
            config={
                "configurable": {
                    "thread_id": session_id,
                },
                "recursion_limit": recursion_limit,
            },
            stream_mode="custom",
        )

    def delete_thread(self, session_id: str) -> None:
        """删除该会话在 LangGraph 里的全部 checkpoint。"""
        checkpointer = self.graph.checkpointer
        if checkpointer is None:
            return
        checkpointer.delete_thread(session_id)