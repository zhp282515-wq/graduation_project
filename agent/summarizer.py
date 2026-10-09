from typing import Any, Callable

from models.base import BaseProvider, ChatMessage
from models.dashscope.Qwen_model import DashScopeProvider
from models.openai.ChatGPT import OpenAIProvider


class Summarizer:
    """把一段消息汇总成文本，供兜底总结和历史压缩复用。

    只负责“用模型生成摘要”，摘要怎么用由调用方决定。
    """

    def __init__(
        self,
        model: BaseProvider,
        *,
        system_prompt: str | None = None,
        reasoning_effort: str = "low",
        enable_thinking: bool = False,
    ):
        self.model = model
        self.system_prompt = system_prompt
        self.reasoning_effort = reasoning_effort
        self.enable_thinking = enable_thinking

    def run(
        self,
        *,
        messages: list[ChatMessage],
        instruction: str,
        on_delta: Callable[[str], None] | None = None,
    ) -> tuple[str, dict[str, Any] | None]:
        call_messages: list[ChatMessage] = []
        if self.system_prompt:
            call_messages.append(ChatMessage(
                role="system",
                content=[{"type": "text", "text": self.system_prompt}],
            ))
        call_messages.extend(messages)
        call_messages.append(ChatMessage(
            role="user",
            content=[{"type": "text", "text": instruction}],
        ))

        stream_kwargs: dict[str, Any] = {"messages": call_messages, "tools": []}
        if isinstance(self.model, DashScopeProvider):
            stream_kwargs["enable_thinking"] = self.enable_thinking
        elif isinstance(self.model, OpenAIProvider):
            stream_kwargs["reasoning_effort"] = self.reasoning_effort

        parts: list[str] = []
        token_usage: dict[str, Any] | None = None

        for event in self.model.stream(**stream_kwargs):
            event_type = event.get("type")
            if event_type == "text_delta":
                chunk = event.get("content", "")
                if chunk:
                    parts.append(chunk)
                    if on_delta is not None:
                        on_delta(chunk)
            elif event_type == "done":
                token_usage = event.get("token_usage")

        return "".join(parts), token_usage