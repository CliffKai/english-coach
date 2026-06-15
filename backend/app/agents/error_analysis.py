"""ErrorAnalysisAgent —— F2 收尾：汇总错误 → 模式识别 → 复盘 → 回填错题本（L3 第 5 步）。

紧跟 ExaminerAgent（07 红线：延迟纠错 buffer 是临时的，产出即消费）。职责（docs/02）：
  ① 把 ExaminerAgent 标注的本次错误 buffer（DetectedError[]）确定性转成 ErrorEntry[]
     —— 补上 session_id/topic 后由功能层落库（回填错题本）。
  ② 结合本次 + 历史错题做**模式识别**，产一段中文复盘（哪类错误反复出现、如何改进）。

两件事的分工：转换是确定性的（不调 LLM，纯字段搬运 + 补元数据）；模式识别/复盘文本
才调 LLM（reasoning 档）。这样「错题数据」与「复盘措辞」解耦——数据可靠、措辞可弃。

毕业（resolved）机制留待阶段2（roadmap 1d/阶段2「错题毕业」）：本层只产出与回填，
连续 N 次未再犯标 resolved 的判定届时再加，故新建 ErrorEntry 一律 resolved=False。
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel

from app.adapters.llm import ChatMessage, LLMProvider, Role
from app.agents.base import parse_json_object
from app.agents.examiner import DetectedError
from app.models import DEFAULT_USER_ID, ErrorEntry, ErrorType


class AnalysisReport(BaseModel):
    """复盘报告。summary 给用户看的整体复盘；type_counts 是本次错误按类型计数（确定性）。

    patterns 是 LLM 识别出的反复出现的错误模式（每条一句中文），可空。
    """

    summary: str = ""
    patterns: list[str] = []
    type_counts: dict[str, int] = {}


class ErrorAnalysisAgent:
    """F2 复盘 + 错题本回填。LLM 由功能层按 reasoning 任务解析后注入（ADR-006）。"""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    @staticmethod
    def to_entries(
        errors: list[DetectedError],
        *,
        session_id: str | None,
        topic: str | None,
        user_id: str = DEFAULT_USER_ID,
    ) -> list[ErrorEntry]:
        """把延迟纠错 buffer 确定性转成可落库的 ErrorEntry（回填错题本）。

        补 session_id/topic/user_id；新错一律 resolved=False（毕业机制属阶段2）。
        不调 LLM——字段搬运而已。
        """
        return [
            ErrorEntry(
                user_id=user_id,
                type=e.type,
                original=e.original,
                correction=e.correction,
                explanation=e.explanation,
                session_id=session_id,
                topic=topic,
                severity=e.severity,
                resolved=False,
            )
            for e in errors
        ]

    async def analyze(
        self,
        current: list[DetectedError],
        *,
        history: list[ErrorEntry] | None = None,
        topic: str | None = None,
    ) -> AnalysisReport:
        """据本次 + 历史错误产复盘。本次无错 → 直接给鼓励语，不烧 token。

        history：用户既往**未解决**错题（功能层从 ErrorRepository 取 resolved=False），
        用于识别「反复犯」的模式；为空也能只就本次给复盘。
        """
        type_counts = _count_types(current)
        if not current:
            return AnalysisReport(
                summary="本次未检测到明显语言错误，表达整体可用。继续保持。",
                patterns=[],
                type_counts={},
            )

        history = history or []
        resp = await self._llm.chat(
            [
                ChatMessage(role=Role.SYSTEM, content=_SYSTEM),
                ChatMessage(
                    role=Role.USER,
                    content=_user_prompt(current, history, topic, type_counts),
                ),
            ],
            temperature=0.3,  # 复盘措辞可略放松（非打分），但仍偏稳
        )
        return self._parse(resp.content, type_counts=type_counts)

    @staticmethod
    def _parse(content: str, *, type_counts: dict[str, int]) -> AnalysisReport:
        """解析复盘；解析失败回落「按类型计数」拼出的兜底复盘，保证总有可用输出。"""
        try:
            obj = parse_json_object(content)
        except ValueError:
            obj = {}
        summary = str(obj.get("summary", "")).strip()
        raw_patterns = obj.get("patterns")
        patterns = (
            [str(p).strip() for p in raw_patterns if str(p).strip()]
            if isinstance(raw_patterns, list)
            else []
        )
        if not summary:
            summary = _fallback_summary(type_counts)
        return AnalysisReport(summary=summary, patterns=patterns, type_counts=type_counts)


_SYSTEM = (
    "你是英语学习教练，负责赛后复盘。给定学习者本次写作的错误清单与既往未解决错题，"
    "识别**反复出现**的错误模式，写一段简短中文复盘（鼓励 + 指出 1–3 个最该改进处 + "
    "可操作建议）。不要逐条复述错误（用户另有错题清单），聚焦模式与改进。只输出 JSON。"
)


def _count_types(errors: list[DetectedError]) -> dict[str, int]:
    """本次错误按类型计数（确定性，供前端展示分布 + 兜底复盘）。"""
    return dict(Counter(e.type.value for e in errors))


def _user_prompt(
    current: list[DetectedError],
    history: list[ErrorEntry],
    topic: str | None,
    type_counts: dict[str, int],
) -> str:
    cur_lines = "\n".join(
        f"- [{e.type.value}] {e.original} → {e.correction}" for e in current
    )
    counts_line = "、".join(f"{t}×{n}" for t, n in type_counts.items())
    hist_block = ""
    if history:
        # 只喂历史的「类型 + 原句」，控制 token；模式识别看类型分布即可。
        hist_counts = Counter(e.type.value for e in history)
        hist_block = (
            "\n既往未解决错题类型分布："
            + "、".join(f"{t}×{n}" for t, n in hist_counts.items())
            + "\n"
        )
    topic_line = f"话题：{topic}\n" if topic else ""
    return (
        f"{topic_line}"
        f"本次错误（共 {len(current)} 条，类型分布：{counts_line}）：\n{cur_lines}\n"
        f"{hist_block}\n"
        "请输出 JSON：\n"
        '{"summary": "<中文复盘，3-5 句>", "patterns": ["<反复出现的模式，每条1句>"]}'
    )


def _fallback_summary(type_counts: dict[str, int]) -> str:
    """LLM 复盘解析失败时的兜底：用确定性的类型计数拼一句，不让前端拿到空复盘。"""
    if not type_counts:
        return "本次已记录错误，复盘文本生成失败，可查看错题清单逐条复习。"
    parts = "、".join(f"{_TYPE_ZH.get(t, t)} {n} 处" for t, n in type_counts.items())
    return f"本次共发现 {parts}。建议重点复习这些类型，详见错题清单。"


# 错误类型中文名（兜底复盘用；与 ErrorType 对齐）。
_TYPE_ZH: dict[str, str] = {
    ErrorType.GRAMMAR.value: "语法",
    ErrorType.COLLOCATION.value: "搭配",
    ErrorType.SPELLING.value: "拼写",
    ErrorType.LOGIC.value: "逻辑",
    ErrorType.VOCABULARY.value: "词汇",
    ErrorType.PRONUNCIATION.value: "发音",
}
