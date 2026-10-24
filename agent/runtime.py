
from langgraph.checkpoint.base import BaseCheckpointSaver
from collections.abc import Callable, Iterator
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
        context_window: int = 1000000
    ):
        self.default_max_turns = default_max_turns

        summarizer = Summarizer(
            summary_model or model,
            system_prompt="你是一个严谨的总结助手，只依据给定材料作答，不补充或编造材料中没有的信息。",
        )

        registry = ToolRegistry(tools)
        nodes = create_nodes(
            model=model,
            registry=registry,
            prompts=prompts,
            default_max_turns=default_max_turns,
            summarizer=summarizer,
            context_window=context_window,
        )
        self.graph = build_graph(nodes, checkpointer=checkpointer)

    def stream(
            self,
            query: list[dict[str, Any]],
            *,
            session_id: str,
            max_turns: int | None = None,
            reasoning: Any = None,
            memory: list[str] | None = None,
            cancel_event=None,
            history: Callable[[], list[dict[str, Any]]] | None = None,
            context_revision: int = 0,
    ) -> Iterator[dict[str, Any]]:
        effective_max_turns = max_turns if max_turns is not None else self.default_max_turns
        recursion_limit = effective_max_turns * 2 + 6

        agent_input: AgentInput = {
            "query": query,
            "max_turns": effective_max_turns,
            "reasoning": reasoning,
            "memory": memory or [],
            "context_revision": context_revision,
        }

        config = {"configurable": {"thread_id": session_id}, "recursion_limit": recursion_limit}
        values = self.graph.get_state(config).values if self.graph.checkpointer is not None else {}
        if values and values.get("context_revision", 0) != context_revision:
            # 不能用追加 reducer 改写旧答案，也不能保留含旧结论的摘要。
            self.delete_thread(session_id)
            values = {}
        if not values and history is not None:
            agent_input["messages"] = [ChatMessage.model_validate(m) for m in history()]

        yield from self.graph.stream(
            agent_input,
            config=config,
            stream_mode="custom"
        )

    def delete_thread(self, session_id: str) -> None:
        """删除该会话在 LangGraph 里的全部 checkpoint。"""
        checkpointer = self.graph.checkpointer
        if checkpointer is None:
            return
        checkpointer.delete_thread(session_id)
