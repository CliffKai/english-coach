"""TopicSuggestionAgent —— F2 话题练习的可选随机话题生成。

话题生成发生在练习开始前，只填充可编辑的 topic 字段；不纠错、不打分、不落库。
这是轻量生成任务，调用方按 ADR-006 注入 conversation 档模型。
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from app.adapters.llm import ChatMessage, LLMProvider, Role
from app.agents.base import parse_json_object
from app.models import PracticeMode


class SuggestedTopic(BaseModel):
    """一个可编辑的练习话题。"""

    topic: str


class TopicSuggestionAgent:
    """为 F2 练习生成一个可选话题。"""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def suggest(
        self,
        *,
        mode: PracticeMode = PracticeMode.FREE_WRITE,
        baseline: str | None = None,
    ) -> SuggestedTopic:
        """调用 LLM 生成一个话题；解析异常时尽量从纯文本中提取一句可用话题。"""
        resp = await self._llm.chat(
            [
                ChatMessage(role=Role.SYSTEM, content=_system_prompt()),
                ChatMessage(role=Role.USER, content=_user_prompt(mode, baseline)),
            ],
            temperature=0.9,
            max_tokens=120,
        )
        return SuggestedTopic(topic=_extract_topic(resp.content, mode))


def _system_prompt() -> str:
    return (
        "You generate concise English practice topics for an English-learning app. "
        "Return JSON only. Do not include explanations, hints, rubrics, or answers."
    )


def _user_prompt(mode: PracticeMode, baseline: str | None) -> str:
    mode_hint = {
        PracticeMode.GUIDED_WRITE: "guided writing practice with immediate coaching",
        PracticeMode.GUIDED_SPEAK: "guided speaking practice with immediate coaching",
        PracticeMode.FREE_WRITE: "exam-style free writing with deferred scoring",
        PracticeMode.DIALOGUE: "exam-style spoken dialogue with deferred scoring",
    }[mode]
    baseline_line = f"Learner CEFR baseline: {baseline}.\n" if baseline else ""
    return (
        f"{baseline_line}"
        f"Mode: {mode_hint}.\n"
        "Generate one fresh, natural practice topic in English. Requirements:\n"
        "- One sentence only.\n"
        "- Suitable for IELTS/TOEFL-style English practice.\n"
        "- Specific enough to start writing or speaking, but not obscure.\n"
        "- Do not give advice, vocabulary, outlines, or sample answers.\n"
        'Output exactly: {"topic": "<topic sentence>"}'
    )


def _extract_topic(content: str, mode: PracticeMode) -> str:
    try:
        obj = parse_json_object(content)
        topic = str(obj.get("topic", "")).strip()
    except ValueError:
        topic = content.strip()
    cleaned = _clean_topic(topic)
    if cleaned:
        return cleaned
    return _fallback_topic(mode)


def _clean_topic(topic: str) -> str:
    topic = topic.strip()
    topic = re.sub(r"^```(?:json)?|```$", "", topic).strip()
    topic = re.sub(r"^[\s\-*•\d.)]+", "", topic).strip()
    topic = topic.strip("\"'“”‘’")
    topic = " ".join(topic.split())
    if len(topic) > 180:
        topic = topic[:180].rsplit(" ", 1)[0].rstrip(" ,;:")
    return topic


def _fallback_topic(mode: PracticeMode) -> str:
    if mode is PracticeMode.DIALOGUE:
        return "Talk about a small decision that changed your daily routine."
    return "Do small daily habits matter more than major life changes?"
