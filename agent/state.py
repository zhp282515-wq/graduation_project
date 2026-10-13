from operator import add
from typing import TypedDict, Annotated, Any, NotRequired

from models.base import ChatMessage, ChatResponse


class AgentInput(TypedDict):
    """调用 Agent 时传入的字段。"""
    query: list[dict[str, Any]]
    max_turns: NotRequired[int]
    timeout: NotRequired[int]
    reasoning: NotRequired[Any]        # 值域由所配 Provider 决定：Qwen 是 bool，OpenAI 是档位字符串


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
    reasoning: NotRequired[Any]
    summary: NotRequired[str]
    summary_upto: NotRequired[int]
    total_tokens: NotRequired[int]     # ← 本轮累计消耗
    started_at: NotRequired[float]     # ← 本轮起始时间


class OutputState(MessagesState):
    """图的输出字段。"""
    final_answer: ChatResponse