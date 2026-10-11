from typing import Any

from langgraph.cache.memory import InMemoryCache
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from agent.routers import route_after_llm
from agent.state import AgentState, OutputState


def build_graph(
    nodes: dict[str, Any],
    checkpointer: BaseCheckpointSaver | None = None,
):
    builder = StateGraph(
        state_schema=AgentState,
        output_schema=OutputState,
    )

    builder.add_node("input_node", nodes["input_node"])
    builder.add_node("llm_node", nodes["llm_node"])
    builder.add_node("tool_node", nodes["tool_node"])
    builder.add_node("fallback_node", nodes["fallback_node"])
    builder.add_node("output_node", nodes["output_node"])
    builder.add_node("compact_node", nodes["compact_node"])


    builder.add_edge(START, "input_node")
    builder.add_edge("input_node", "llm_node")
    builder.add_conditional_edges("llm_node", route_after_llm)
    builder.add_edge("tool_node", "llm_node")
    builder.add_edge("output_node", "compact_node")
    builder.add_edge("compact_node", END)

    return builder.compile(
        checkpointer=checkpointer
    )