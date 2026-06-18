"""SentenceAnalysisAgent —— 句子精读：翻译 + 语法/用法讲解。

用户输入一个英文句子，Agent 调 reasoning 档模型产出结构化精读结果：
中文自然翻译、句子结构、语法点、词汇/短语用法、常见误区、改写与学习要点。

第一版不落库。结果只是即时讲解；若用户主动把词加入生词本，仍复用 F1 的
VocabEntry 入库链，只存「词 + 当前句子作为来源句」，不存这里生成的释义/讲解（ADR-004/017）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.adapters.llm import ChatMessage, LLMProvider, Role
from app.agents.base import parse_json_object


class LearningPoint(BaseModel):
    """一个可学习的语法/用法点。"""

    title: str
    explanation: str = ""
    example: str = ""


class LexicalNote(BaseModel):
    """词汇或短语在当前句子里的语境化说明。"""

    term: str
    meaning: str = ""
    note: str = ""


class RewriteOption(BaseModel):
    """一个改写版本，用来展示表达迁移。"""

    style: str
    text: str


class SentenceAnalysis(BaseModel):
    """句子精读结果。所有讲解均为即时生成，不持久化。"""

    original: str
    translation_zh: str = ""
    literal_translation: str = ""
    structure: str = ""
    grammar_points: list[LearningPoint] = Field(default_factory=list)
    vocabulary_notes: list[LexicalNote] = Field(default_factory=list)
    phrase_notes: list[LexicalNote] = Field(default_factory=list)
    common_pitfalls: list[str] = Field(default_factory=list)
    rewrites: list[RewriteOption] = Field(default_factory=list)
    takeaways: list[str] = Field(default_factory=list)
    exercise: str = ""
    estimated: bool = True


class SentenceAnalysisAgent:
    """句子精读。LLM 由功能层按 reasoning 任务解析后注入（ADR-006/017）。"""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def analyze(
        self,
        sentence: str,
        *,
        baseline: str | None = None,
        native_lang: str = "zh",
    ) -> SentenceAnalysis:
        """翻译并讲解一个英文句子。空输入不调 LLM，返回空结果。"""
        cleaned = sentence.strip()
        if not cleaned:
            return SentenceAnalysis(original="")

        resp = await self._llm.chat(
            [
                ChatMessage(role=Role.SYSTEM, content=_SYSTEM),
                ChatMessage(
                    role=Role.USER,
                    content=_user_prompt(cleaned, baseline=baseline, native_lang=native_lang),
                ),
            ],
            temperature=0.2,
        )
        return self._parse(resp.content, original=cleaned)

    @staticmethod
    def _parse(content: str, *, original: str) -> SentenceAnalysis:
        """解析模型 JSON；失败时保留原句并给可展示的降级说明。"""
        try:
            obj = parse_json_object(content)
        except ValueError:
            return SentenceAnalysis(
                original=original,
                structure="AI 返回内容未能解析为结构化结果，请稍后重试或换一个模型。",
                takeaways=["本次精读解析失败，未写入任何学习数据。"],
            )

        return SentenceAnalysis(
            original=original,
            translation_zh=_clean_str(obj.get("translation_zh")),
            literal_translation=_clean_str(obj.get("literal_translation")),
            structure=_clean_str(obj.get("structure")),
            grammar_points=_learning_points(obj.get("grammar_points"), max_items=6),
            vocabulary_notes=_lexical_notes(obj.get("vocabulary_notes"), key="term", max_items=8),
            phrase_notes=_lexical_notes(obj.get("phrase_notes"), key="phrase", max_items=6),
            common_pitfalls=_string_list(obj.get("common_pitfalls"), max_items=5),
            rewrites=_rewrites(obj.get("rewrites"), max_items=4),
            takeaways=_string_list(obj.get("takeaways"), max_items=5),
            exercise=_clean_str(obj.get("exercise")),
        )


_SYSTEM = (
    "你是面向中文母语学习者的英语句子精读教练。用户会给你一个英文句子。"
    "你的任务是帮助用户理解这个句子，并指出真正值得学习的英语知识点，而不是机械罗列。\n"
    "要求：\n"
    "1) 中文自然翻译优先准确、通顺；必要时给直译帮助看结构。\n"
    "2) 结构讲解要抓主干、从句、修饰关系、指代关系。\n"
    "3) 语法点只讲这个句子里确实出现且值得学的内容。\n"
    "4) 词汇/短语说明必须绑定当前语境，不要写成词典释义。\n"
    "5) 如果句子有歧义或上下文不足，要明确说不确定点。\n"
    "6) 输出 JSON 对象，不要 markdown，不要任何前后缀。"
)


def _user_prompt(sentence: str, *, baseline: str | None, native_lang: str) -> str:
    ctx = ""
    if baseline:
        ctx += f"学习者水平基线（CEFR）：{baseline}\n"
    ctx += f"学习者母语：{native_lang}\n"
    return (
        f"{ctx}"
        f"英文句子：\n{sentence}\n\n"
        "请输出 JSON，字段必须使用以下结构：\n"
        "{\n"
        '  "translation_zh": "<自然中文翻译>",\n'
        '  "literal_translation": "<可选：贴近英文结构的直译，帮助看结构>",\n'
        '  "structure": "<中文说明句子主干、从句、修饰关系>",\n'
        '  "grammar_points": [\n'
        '    {"title": "<语法点名称>", "explanation": "<中文解释>", "example": "<可选例子>"}\n'
        "  ],\n"
        '  "vocabulary_notes": [\n'
        '    {"term": "<重点词>", "meaning": "<当前语境意思>", "note": "<用法/搭配/易错点>"}\n'
        "  ],\n"
        '  "phrase_notes": [\n'
        '    {"phrase": "<短语或表达>", "meaning": "<当前语境意思>", "note": "<用法说明>"}\n'
        "  ],\n"
        '  "common_pitfalls": ["<中文说明常见误解或中式表达风险>"],\n'
        '  "rewrites": [\n'
        '    {"style": "<更简单|更正式|更口语|同义改写>", "text": "<英文改写句>"}\n'
        "  ],\n"
        '  "takeaways": ["<这句话最值得学的点，1-3 条优先>"],\n'
        '  "exercise": "<一个很短的跟练任务，例如仿写一句>"\n'
        "}\n"
        "数组没有内容时用空数组，不要编造不存在的语法点。"
    )


def _clean_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _string_list(value: Any, *, max_items: int) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value[:max_items]:
        text = _clean_str(item)
        if text:
            items.append(text)
    return items


def _learning_points(value: Any, *, max_items: int) -> list[LearningPoint]:
    if not isinstance(value, list):
        return []
    points: list[LearningPoint] = []
    for item in value[:max_items]:
        if not isinstance(item, dict):
            continue
        title = _clean_str(item.get("title"))
        explanation = _clean_str(item.get("explanation"))
        if not title and not explanation:
            continue
        points.append(
            LearningPoint(
                title=title or "学习点",
                explanation=explanation,
                example=_clean_str(item.get("example")),
            )
        )
    return points


def _lexical_notes(value: Any, *, key: str, max_items: int) -> list[LexicalNote]:
    if not isinstance(value, list):
        return []
    notes: list[LexicalNote] = []
    for item in value[:max_items]:
        if not isinstance(item, dict):
            continue
        term = _clean_str(item.get(key)) or _clean_str(item.get("term"))
        if not term:
            continue
        notes.append(
            LexicalNote(
                term=term,
                meaning=_clean_str(item.get("meaning")),
                note=_clean_str(item.get("note")),
            )
        )
    return notes


def _rewrites(value: Any, *, max_items: int) -> list[RewriteOption]:
    if not isinstance(value, list):
        return []
    rewrites: list[RewriteOption] = []
    for item in value[:max_items]:
        if not isinstance(item, dict):
            continue
        text = _clean_str(item.get("text"))
        if not text:
            continue
        rewrites.append(
            RewriteOption(style=_clean_str(item.get("style")) or "改写", text=text)
        )
    return rewrites
