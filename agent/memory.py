import json
import re
from typing import Any

from agent.summarizer import Summarizer
from utils.logger_tool import logger

_EXTRACT_INSTRUCTION = """
从下面这轮对话中，提取**值得长期记住**的关于用户的信息。

只提取这几类：
- 身份与背景：学院、专业、年级、家乡等
- 稳定偏好：喜欢的食物、作息、学习习惯、沟通偏好、爱好、性格
- 长期目标：考研、就业方向、正在准备的考试
- 明确的个人事实：姓名、年龄、昵称、联系方式

不要提取：
- 一次性的问题本身（"图书馆几点开门"）
- 从对话中推测出来的内容
- 已经存在于【已知记忆】里的重复信息
- 与用户本人无关的通用知识

输出严格 JSON 数组，每项形如 {"content": "用户是计算机学院大二学生", "category": "identity"}。
category 只能是：identity / preference / goal / fact。
【注意】 首先判断是否存在可提取的信息，如果没有可提取的信息，输出 []。

【已知记忆】
{known}

【本轮对话】
{conversation}
"""

_CATEGORIES = {"identity", "preference", "goal", "fact"}


def _strip_fence(text: str) -> str:
    """模型常把 JSON 包在 ```json ... ``` 里，剥掉围栏。"""
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    return fence.group(1) if fence else text


class MemoryExtractor:
    """用一个小模型从单轮对话里抽取长期记忆。

    与 Summarizer 同样走"纯文本生成 + 自己解析"的路线，
    不依赖模型的 function calling，换 Provider 时行为更稳定。
    出错一律返回空列表 —— 抽取失败不能影响主对话。
    """

    def __init__(self, model, *, min_turns: int = 1):
        self._summarizer = Summarizer(
            model,
            system_prompt="你是一个严格的信息抽取器，只输出 JSON，不输出任何解释。",
        )
        self._min_turns = min_turns

    def extract(
        self,
        *,
        user_text: str,
        assistant_text: str,
        known: list[str],
    ) -> list[dict[str, str]]:
        if not user_text.strip():
            return []

        conversation = f"用户：{user_text}\n\n助手：{assistant_text[:1500]}"
        # 不用 str.format：提示词里含有 JSON 示例的花括号
        instruction = (
            _EXTRACT_INSTRUCTION
            .replace("{known}", "\n".join(f"- {k}" for k in known) or "（暂无）")
            .replace("{conversation}", conversation)
        )

        try:
            raw, _ = self._summarizer.run(messages=[], instruction=instruction)
            data = json.loads(_strip_fence(raw))
        except Exception as exc:
            logger.warning("记忆抽取失败：%s", exc)
            return []

        if not isinstance(data, list):
            return []

        out: list[dict[str, str]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content", "")).strip()
            category = str(item.get("category", "fact")).strip()
            if not content or len(content) > 200:
                continue
            if category not in _CATEGORIES:
                category = "fact"
            out.append({"content": content, "category": category})
        return out
