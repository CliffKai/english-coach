"""L3 后半验证（docs/07）：F2c 自由写作打分 → ErrorAnalysis → 错题本。

覆盖「错误河」（F2c → ErrorAnalysis）：ExaminerAgent 打分 + 隐藏错误 buffer 的解析与
确定性聚合，ErrorAnalysisAgent 的 buffer→ErrorEntry 转换与复盘兜底。
全程离线：用 mock LLM（不发网络），不依赖 spaCy 模型。
"""

from __future__ import annotations

import json

import pytest

from app.adapters.llm import LLMResponse
from app.agents.error_analysis import ErrorAnalysisAgent
from app.agents.examiner import DetectedError, ExaminerAgent
from app.models import ErrorType, ScoringStandard


class FakeLLM:
    """可编程假 LLM：按预设回复，记录收到的消息（验证装配）。"""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[list] = []

    async def chat(self, messages, *, model=None, temperature=0.7, max_tokens=None):
        self.calls.append(messages)
        return LLMResponse(content=self.reply, model=model or "fake")

    def stream_chat(self, messages, *, model=None, temperature=0.7, max_tokens=None):
        async def _gen():
            yield self.reply

        return _gen()


# ── ExaminerAgent：打分 + 错误 buffer ───────────────────────────────
@pytest.mark.asyncio
async def test_examiner_ielts_scores_and_overall_is_computed():
    """雅思四维 + 综合分由 Python 确定性算（均值按 0.5 取整），不取 LLM 的聚合。"""
    reply = json.dumps(
        {
            "dimensions": [
                {"key": "task_response", "score": 6, "comment": "切题"},
                {"key": "coherence_cohesion", "score": 6, "comment": "连贯"},
                {"key": "lexical_resource", "score": 7, "comment": "词汇较好"},
                {"key": "grammatical_range_accuracy", "score": 7, "comment": "语法稳"},
            ],
            "errors": [
                {
                    "type": "grammar",
                    "original": "I has a dog",
                    "correction": "I have a dog",
                    "explanation": "主谓一致",
                    "severity": 2,
                }
            ],
        }
    )
    result = await ExaminerAgent(FakeLLM(reply)).score(
        "Some essay text.", standard=ScoringStandard.IELTS
    )
    assert result.standard is ScoringStandard.IELTS
    assert {d.key for d in result.dimensions} == {
        "task_response",
        "coherence_cohesion",
        "lexical_resource",
        "grammatical_range_accuracy",
    }
    # 均值 (6+6+7+7)/4 = 6.5 → 0.5 步长取整 6.5。
    assert result.overall == 6.5
    assert result.estimated is True  # 恒标 AI 估算（07 风险）
    assert len(result.errors) == 1
    assert result.errors[0].type is ErrorType.GRAMMAR


@pytest.mark.asyncio
async def test_examiner_toefl_uses_three_dimensions_and_0_5_scale():
    reply = json.dumps(
        {
            "dimensions": [
                {"key": "development", "score": 4},
                {"key": "organization", "score": 3},
                {"key": "language_use", "score": 4},
            ],
            "errors": [],
        }
    )
    result = await ExaminerAgent(FakeLLM(reply)).score(
        "essay", standard=ScoringStandard.TOEFL
    )
    assert {d.key for d in result.dimensions} == {
        "development",
        "organization",
        "language_use",
    }
    # 均值 (4+3+4)/3 = 3.67 → 0.5 步长取整 3.5。
    assert result.overall == 3.5


@pytest.mark.asyncio
async def test_examiner_overall_rounds_half_up_not_bankers():
    """综合分逢半向上：均值 6.25 → 6.5（内置 round 的银行家舍入会错成 6.0）。"""
    reply = json.dumps(
        {
            "dimensions": [
                {"key": "task_response", "score": 6},
                {"key": "coherence_cohesion", "score": 6},
                {"key": "lexical_resource", "score": 6.5},
                {"key": "grammatical_range_accuracy", "score": 6.5},
            ],
            "errors": [],
        }
    )
    result = await ExaminerAgent(FakeLLM(reply)).score("x", standard=ScoringStandard.IELTS)
    # 均值 (6+6+6.5+6.5)/4 = 6.25 → half-up → 6.5。
    assert result.overall == 6.5


@pytest.mark.asyncio
async def test_examiner_clamps_out_of_range_scores():
    """LLM 给越界分（>9 / 负）→ 夹到 [0,9]，不污染综合分。"""
    reply = json.dumps(
        {
            "dimensions": [
                {"key": "task_response", "score": 99},
                {"key": "coherence_cohesion", "score": -5},
                {"key": "lexical_resource", "score": 6},
                {"key": "grammatical_range_accuracy", "score": 6},
            ],
            "errors": [],
        }
    )
    result = await ExaminerAgent(FakeLLM(reply)).score("x", standard=ScoringStandard.IELTS)
    by_key = {d.key: d.score for d in result.dimensions}
    assert by_key["task_response"] == 9.0
    assert by_key["coherence_cohesion"] == 0.0


@pytest.mark.asyncio
async def test_examiner_empty_text_short_circuits_without_llm():
    """空文本（提前交卷且无内容，ADR-005）→ 最低分空 buffer，不烧 token。"""
    llm = FakeLLM("should-not-be-called")
    result = await ExaminerAgent(llm).score("   ", standard=ScoringStandard.IELTS)
    assert result.overall == 0.0
    assert result.errors == []
    assert llm.calls == []


@pytest.mark.asyncio
async def test_examiner_drops_invalid_error_types_and_incomplete_rows():
    """非法 type（pronunciation/未知）或缺原句/修正的错误条目 → 跳过，宁缺毋滥。"""
    reply = json.dumps(
        {
            "dimensions": [{"key": "task_response", "score": 6}],
            "errors": [
                {"type": "pronunciation", "original": "a", "correction": "b"},  # 写作不该有发音
                {"type": "made_up", "original": "a", "correction": "b"},  # 未知类型
                {"type": "grammar", "original": "", "correction": "b"},  # 缺原句
                {"type": "spelling", "original": "teh", "correction": "the"},  # 合法
            ],
        }
    )
    result = await ExaminerAgent(FakeLLM(reply)).score("x", standard=ScoringStandard.IELTS)
    assert len(result.errors) == 1
    assert result.errors[0].type is ErrorType.SPELLING


@pytest.mark.asyncio
async def test_examiner_unparseable_falls_back_to_floor_scores():
    """LLM 输出非 JSON → 各维度回落最低分、空 buffer（不炸）。"""
    result = await ExaminerAgent(FakeLLM("完全不是 JSON")).score(
        "x", standard=ScoringStandard.IELTS
    )
    assert all(d.score == 0.0 for d in result.dimensions)
    assert result.overall == 0.0
    assert result.errors == []


# ── ErrorAnalysisAgent：buffer→ErrorEntry + 复盘 ────────────────────
def test_to_entries_is_deterministic_and_fills_metadata():
    """buffer → ErrorEntry：补 session_id/topic，新错 resolved=False，不调 LLM。"""
    errors = [
        DetectedError(type=ErrorType.GRAMMAR, original="I has", correction="I have"),
        DetectedError(type=ErrorType.SPELLING, original="teh", correction="the"),
    ]
    entries = ErrorAnalysisAgent.to_entries(errors, session_id="s1", topic="travel")
    assert len(entries) == 2
    assert all(e.session_id == "s1" and e.topic == "travel" for e in entries)
    assert all(e.resolved is False for e in entries)
    assert {e.type for e in entries} == {ErrorType.GRAMMAR, ErrorType.SPELLING}


@pytest.mark.asyncio
async def test_analyze_empty_errors_short_circuits_without_llm():
    llm = FakeLLM("should-not-be-called")
    report = await ErrorAnalysisAgent(llm).analyze([])
    assert report.summary
    assert report.type_counts == {}
    assert llm.calls == []


@pytest.mark.asyncio
async def test_analyze_counts_types_and_parses_patterns():
    reply = json.dumps(
        {"summary": "时态反复出错，建议专项练习。", "patterns": ["一般现在时主谓一致"]}
    )
    errors = [
        DetectedError(type=ErrorType.GRAMMAR, original="I has", correction="I have"),
        DetectedError(type=ErrorType.GRAMMAR, original="he go", correction="he goes"),
        DetectedError(type=ErrorType.SPELLING, original="teh", correction="the"),
    ]
    report = await ErrorAnalysisAgent(FakeLLM(reply)).analyze(errors)
    assert report.type_counts == {"grammar": 2, "spelling": 1}
    assert report.patterns == ["一般现在时主谓一致"]
    assert "时态" in report.summary


@pytest.mark.asyncio
async def test_analyze_unparseable_falls_back_to_count_summary():
    """LLM 复盘非 JSON → 用确定性类型计数拼兜底复盘，不给前端空 summary。"""
    errors = [DetectedError(type=ErrorType.GRAMMAR, original="a", correction="b")]
    report = await ErrorAnalysisAgent(FakeLLM("not json")).analyze(errors)
    assert report.summary  # 非空
    assert report.type_counts == {"grammar": 1}
