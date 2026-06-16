"""L4 验证（docs/07）：F2d 口语打分维度 + 发音空缺/真分（ADR-013）、ExaminerAgent.converse 零纠错、
TutorAgent 即时纠错、MemoryWordAgent F3b 造句 + 逐词检验。全程离线 mock LLM。
"""

from __future__ import annotations

import json

import pytest

from app.adapters.llm import LLMResponse
from app.adapters.speech import PronunciationResult
from app.agents.examiner import ExaminerAgent
from app.agents.memory_word import MemoryWordAgent
from app.agents.tutor import TutorAgent
from app.models import PracticeMode, ScoringStandard
from app.scheduling import ReviewRating


class FakeLLM:
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


# ── F2d 口语打分：维度集 + 发音空缺/真分（ADR-013）─────────────────
_SPEAKING_REPLY = json.dumps(
    {
        "dimensions": [
            {"key": "fluency_coherence", "score": 6, "comment": "流利"},
            {"key": "lexical_resource", "score": 6, "comment": "词汇"},
            {"key": "grammatical_range_accuracy", "score": 6, "comment": "语法"},
        ],
        "errors": [
            {"type": "grammar", "original": "technology make", "correction": "technology makes",
             "explanation": "主谓一致", "severity": 2}
        ],
    }
)


@pytest.mark.asyncio
async def test_dialogue_uses_speaking_dims_and_withholds_pronunciation():
    """口语用口语维度集；无发音评估 → 发音/流利度空缺(None)且 estimated（ADR-013）。

    注意：LLM 回的 fluency_coherence 分被忽略——它是声学维度，由系统据发音评估处理。
    """
    result = await ExaminerAgent(FakeLLM(_SPEAKING_REPLY)).score(
        "I think technology make life better.",
        mode=PracticeMode.DIALOGUE,
        standard=ScoringStandard.IELTS,
        pronunciation=None,
    )
    by_key = {d.key: d for d in result.dimensions}
    assert set(by_key) == {
        "fluency_coherence",
        "lexical_resource",
        "grammatical_range_accuracy",
        "pronunciation",
    }
    # 声学维度（发音 + 流利连贯）空缺并标注。
    assert by_key["pronunciation"].score is None and by_key["pronunciation"].estimated
    assert by_key["fluency_coherence"].score is None and by_key["fluency_coherence"].estimated
    # 文本维度仍有分；overall 只对有分维度均值（6,6）→ 6.0，不被 None 拖低。
    assert by_key["lexical_resource"].score == 6.0
    assert result.overall == 6.0
    # 口语放行 pronunciation 错误类型；本例错误是 grammar。
    assert result.errors[0].type.value == "grammar"


@pytest.mark.asyncio
async def test_dialogue_with_real_pronunciation_fills_acoustic_dims():
    """配了发音评估（estimated=False）→ 发音/流利度据其填真分（0–100 映射到 band）。"""
    pron = PronunciationResult(accuracy=80.0, fluency=70.0, estimated=False)
    result = await ExaminerAgent(FakeLLM(_SPEAKING_REPLY)).score(
        "I think technology makes life better.",
        mode=PracticeMode.DIALOGUE,
        standard=ScoringStandard.IELTS,
        pronunciation=pron,
    )
    by_key = {d.key: d for d in result.dimensions}
    # 80/100 * 9 = 7.2 → 0.5 步长 → 7.0；70/100 * 9 = 6.3 → 6.5。
    assert by_key["pronunciation"].score == 7.0
    assert by_key["pronunciation"].estimated is False
    assert by_key["fluency_coherence"].score == 6.5


@pytest.mark.asyncio
async def test_converse_returns_reply_and_does_not_score():
    """对话单轮只回自然对话（驱动 TTS），不打分/不纠错（ADR-005 零脚手架）。"""
    llm = FakeLLM("Interesting! Can you give an example?")
    result = await ExaminerAgent(llm).converse("I like travel.", topic="travel")
    assert result.reply == "Interesting! Can you give an example?"
    # converse 的 system 提示明确要求绝不纠错（考试模式零脚手架）。
    system_text = llm.calls[0][0].content
    assert "NEVER correct" in system_text


# ── F2a/2b TutorAgent：即时纠错 + 脚手架 ──────────────────────────
@pytest.mark.asyncio
async def test_tutor_returns_corrections_and_scaffold():
    reply = json.dumps(
        {
            "corrections": [
                {"original": "I goes", "correction": "I go", "explanation": "主谓一致"},
                {"original": "", "correction": "x"},  # 缺原句 → 跳过
            ],
            "encouragement": "开头不错！",
            "scaffold": "可以补一个例子说明原因。",
            "follow_up": "Why do you think so?",
        }
    )
    turn = await TutorAgent(FakeLLM(reply)).tutor(
        "I goes to school.", mode=PracticeMode.GUIDED_WRITE
    )
    assert len(turn.corrections) == 1  # 缺原句的被丢
    assert turn.corrections[0].correction == "I go"
    assert turn.encouragement and turn.scaffold and turn.follow_up


@pytest.mark.asyncio
async def test_tutor_empty_input_gives_opening_without_llm():
    llm = FakeLLM("should-not-be-called")
    turn = await TutorAgent(llm).tutor("   ", topic="travel")
    assert turn.scaffold and turn.follow_up
    assert llm.calls == []  # 空输入不烧 token


# ── F3b 语境造句背：造短文 + 逐词检验 ─────────────────────────────
@pytest.mark.asyncio
async def test_make_passage_returns_text_and_words_used():
    reply = json.dumps(
        {
            "text": "The ubiquitous gadget changed our serendipity.",
            "words_used": ["ubiquitous", "serendipity"],
        }
    )
    p = await MemoryWordAgent(FakeLLM(reply)).make_passage(
        ["ubiquitous", "serendipity", "obscure"]
    )
    assert "ubiquitous" in p.text.lower()
    # words_used 只保留确属请求集的词。
    assert set(p.words_used) == {"ubiquitous", "serendipity"}


@pytest.mark.asyncio
async def test_make_passage_empty_words_short_circuits():
    llm = FakeLLM("nope")
    p = await MemoryWordAgent(llm).make_passage([])
    assert p.text == "" and p.words_used == []
    assert llm.calls == []


@pytest.mark.asyncio
async def test_check_translation_maps_verdicts_to_ratings():
    reply = json.dumps(
        {
            "checks": [
                {"word": "ubiquitous", "verdict": "correct", "feedback": "对"},
                {"word": "serendipity", "verdict": "wrong", "feedback": "理解错"},
            ]
        }
    )
    checks = await MemoryWordAgent(FakeLLM(reply)).check_translation(
        passage="...", words=["ubiquitous", "serendipity"], translation="无处不在的小工具…"
    )
    by_word = {c.word: c for c in checks}
    assert by_word["ubiquitous"].rating is ReviewRating.GOOD
    assert by_word["serendipity"].rating is ReviewRating.AGAIN


@pytest.mark.asyncio
async def test_check_translation_empty_is_all_again_without_llm():
    llm = FakeLLM("nope")
    checks = await MemoryWordAgent(llm).check_translation(
        passage="...", words=["a", "b"], translation="   "
    )
    assert all(c.rating is ReviewRating.AGAIN for c in checks)
    assert llm.calls == []


@pytest.mark.asyncio
async def test_check_translation_missing_word_defaults_partial():
    """LLM 漏判某词 → 保守归 partial(HARD)，宁可多复习（同 ADR-011 兜底）。"""
    reply = json.dumps({"checks": [{"word": "a", "verdict": "correct"}]})
    checks = await MemoryWordAgent(FakeLLM(reply)).check_translation(
        passage="...", words=["a", "b"], translation="某翻译"
    )
    by_word = {c.word: c for c in checks}
    assert by_word["a"].rating is ReviewRating.GOOD
    assert by_word["b"].verdict == "partial" and by_word["b"].rating is ReviewRating.HARD
