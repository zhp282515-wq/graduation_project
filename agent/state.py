from operator import add
from typing import TypedDict, Annotated, Any, NotRequired

from models.base import ChatMessage, ChatResponse


class AgentInput(TypedDict):
    """调用 Agent 时传入的字段。"""
    query: list[dict[str, Any]]
    max_turns: NotRequired[int]
    timeout: NotRequired[int]
    enable_thinking: NotRequired[bool]
    reasoning_effort: NotRequired[str]


class MessagesState(TypedDict):
    # LangGraph 用 add 把每个节点新产生的消息追加到 messages。
    messages: Annotated[list[ChatMessage], add]


class AgentState(MessagesState):
    """图运行期间使用的完整状态。"""
    query: list[dict[str, Any]]
    last_response: NotRequired[ChatResponse]
    max_turns: NotRequired[int]
    turn_count: NotRequired[int]
    timeout: NotRequired[int]
    enable_thinking: NotRequired[bool]
    reasoning_effort: NotRequired[str]


class OutputState(MessagesState):
    """图的输出字段。"""
    final_answer: ChatResponse