from typing import Literal

from agent.state import AgentState


def route_after_llm(
    state: AgentState,
) -> Literal["tool_node", "output_node", "fallback_node"]:
    response = state.get("last_response")

    if response is None or not response.tool_calls:
        return "output_node"

    if state.get("turn_count", 0) < state.get("max_turns", 10):
        return "tool_node"

    return "fallback_node"