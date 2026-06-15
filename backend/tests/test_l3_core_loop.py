"""L3 验证（docs/07）：核心闭环 —— 水平基线 → F1 生词收集 → F3a 理解式背词。

全程离线：用 mock LLM（不发网络）+ 内存 SQLite + 真实 SpacyTokenizer/FsrsScheduler。
覆盖严格顺序的三步与两条数据河里的「生词河」（F1→F3a）。
缺 en_core_web_sm 时切词相关用例跳过（CI 未装 ML 栈不红）。
"""

from __future__ import annotations

import json

import pytest

from app.adapters.llm import LLMResponse
from app.adapters.local import (
    SqliteWordRepository,
)
from app.agents.base import LLMNotConfiguredError, parse_json_object, resolve_task_llm
from app.agents.leveling import LevelingAgent
from app.agents.memory_word import MemoryWordAgent
from app.agents.tokenizer_agent import CollectItem, TokenizerAgent
from app.config import AppConfig
from app.db.connection import Database
from app.models import Settings, VocabEntry, VocabStatus
from app.models.entities import ModelAssignment
from app.nlp.tokenizer import SpacyTokenizer
from app.scheduling import FsrsScheduler, ReviewRating

# ── 切词依赖 spaCy 模型，缺失则相关用例跳过 ─────────────────────────
spacy = pytest.importorskip("spacy")
_HAS_MODEL = spacy.util.is_package("en_core_web_sm")
_needs_model = pytest.mark.skipif(not _HAS_MODEL, reason="en_core_web_sm 未安装")


class FakeLLM:
    """可编程的假 LLM：按预设内容回复，记录收到的消息（验证装配）。"""

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


@pytest.fixture
def db() -> Database:
    database = Database(":memory:")
    yield database
    database.close()


# ── base：按任务挑模型 + JSON 解析 ──────────────────────────────────
def test_resolve_task_llm_prefers_assignment_then_default():
    default = FakeLLM("x")
    # 无分配 + 有默认 → 用默认。
    assert resolve_task_llm(
        "scoring", settings=Settings(), config=AppConfig(), default_llm=default
    ) is default
    # 无分配 + 无默认 → 抛错（提示去配模型）。
    with pytest.raises(LLMNotConfiguredError):
        resolve_task_llm("scoring", settings=None, config=AppConfig(), default_llm=None)


def test_resolve_task_llm_builds_from_assignment():
    from app.adapters.openai_compat import OpenAICompatAdapter
    from app.config import LLMProviderConnection

    settings = Settings()
    settings.model_config_.scoring = ModelAssignment(provider="deepseek", model="deepseek-chat")
    config = AppConfig(
        llm_providers={"deepseek": LLMProviderConnection(base_url="http://x/v1", api_key="k")}
    )
    llm = resolve_task_llm("scoring", settings=settings, config=config, default_llm=None)
    assert isinstance(llm, OpenAICompatAdapter)


def test_parse_json_object_handles_fences_and_prose():
    assert parse_json_object('{"a": 1}') == {"a": 1}
    assert parse_json_object('```json\n{"a": 2}\n```') == {"a": 2}
    assert parse_json_object('好的，结果是 {"a": 3} 仅供参考') == {"a": 3}
    with pytest.raises(ValueError):
        parse_json_object("no json here")


# ── L3-1 水平基线分级 ───────────────────────────────────────────────
@pytest.mark.asyncio
async def test_leveling_assess_parses_cefr_and_marks_estimated():
    llm = FakeLLM(json.dumps({"baseline": "B2", "rationale": "论证较完整，偶有错误"}))
    result = await LevelingAgent(llm).assess("My hometown is a quiet town...")
    assert result.baseline == "B2"
    assert result.estimated is True  # 恒标 AI 估算（07 可信度风险）
    assert result.estimated_band is not None
    # 零温度评分（要稳）。
    assert llm.calls, "应调用了 LLM"


@pytest.mark.asyncio
async def test_leveling_empty_sample_falls_back_b1_without_llm():
    llm = FakeLLM("should-not-be-called")
    result = await LevelingAgent(llm).assess("   ")
    assert result.baseline == "B1"
    assert llm.calls == []  # 空样本不烧 token


@pytest.mark.asyncio
async def test_leveling_invalid_level_falls_back_b1():
    llm = FakeLLM(json.dumps({"baseline": "Z9"}))
    result = await LevelingAgent(llm).assess("some sample text here")
    assert result.baseline == "B1"


# ── L3-2 F1 生词收集 ────────────────────────────────────────────────
@_needs_model
def test_tokenizer_agent_extract_uses_baseline():
    agent = TokenizerAgent(SpacyTokenizer(), SqliteWordRepository(Database(":memory:")))
    text = "The ubiquitous use of ephemeral apps is a serendipitous trend."
    cands = agent.extract(text, baseline="B1")
    lemmas = {c.lemma for c in cands}
    assert "ubiquitous" in lemmas and "ephemeral" in lemmas
    assert "the" not in lemmas


@pytest.mark.asyncio
async def test_collect_inserts_unknown_words_with_context(db: Database):
    repo = SqliteWordRepository(db)
    agent = TokenizerAgent(SpacyTokenizer() if _HAS_MODEL else None, repo)
    out = await agent.collect(
        [
            CollectItem(
                word="ephemeral", lemma="ephemeral", context_sentences=["A fad is ephemeral."]
            ),
            CollectItem(
                word="ubiquitous", lemma="ubiquitous", context_sentences=["Apps are ubiquitous."]
            ),
        ]
    )
    assert {e.lemma for e in out} == {"ephemeral", "ubiquitous"}
    stored = await repo.list()
    assert len(stored) == 2
    eph = await repo.get_by_lemma("ephemeral")
    assert eph.context_sentences == ["A fad is ephemeral."]
    assert eph.status == VocabStatus.NEW


@pytest.mark.asyncio
async def test_collect_dedups_by_lemma_and_merges_context(db: Database):
    repo = SqliteWordRepository(db)
    agent = TokenizerAgent(SpacyTokenizer() if _HAS_MODEL else None, repo)
    # 先入一次。
    await agent.collect(
        [CollectItem(word="ephemeral", lemma="ephemeral", context_sentences=["A fad is e."])]
    )
    # 同 lemma 再来一条新来源句 → 合并，不新建（ADR-004/010）。
    await agent.collect(
        [CollectItem(word="ephemeral", lemma="ephemeral", context_sentences=["Fame can be e."])]
    )
    stored = await repo.list()
    assert len(stored) == 1  # 仍只有一条
    assert len(stored[0].context_sentences) == 2


@pytest.mark.asyncio
async def test_collect_merges_within_single_batch(db: Database):
    repo = SqliteWordRepository(db)
    agent = TokenizerAgent(None, repo)
    # 同一批里同 lemma 两条 → 也只入一条、合并来源句（不撞唯一索引）。
    out = await agent.collect(
        [
            CollectItem(word="run", lemma="run", context_sentences=["I run fast."]),
            CollectItem(word="running", lemma="run", context_sentences=["He is running."]),
        ]
    )
    assert len(out) == 1
    assert len(out[0].context_sentences) == 2


# ── L3-3 F3a 理解式背词 ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_memory_word_maps_verdict_to_rating():
    # correct → GOOD
    agent = MemoryWordAgent(FakeLLM(json.dumps({"verdict": "correct", "feedback": "对"})))
    r = await agent.judge(
        word="ephemeral", context_sentences=["A fad is ephemeral."], understanding="短暂的"
    )
    assert r.rating == ReviewRating.GOOD

    # partial → HARD
    agent = MemoryWordAgent(FakeLLM(json.dumps({"verdict": "partial"})))
    r = await agent.judge(word="bank", context_sentences=["river bank"], understanding="银行?")
    assert r.rating == ReviewRating.HARD

    # wrong → AGAIN
    agent = MemoryWordAgent(FakeLLM(json.dumps({"verdict": "wrong"})))
    r = await agent.judge(word="x", context_sentences=["y"], understanding="不知道")
    assert r.rating == ReviewRating.AGAIN


@pytest.mark.asyncio
async def test_memory_word_too_easy_and_empty_short_circuit():
    llm = FakeLLM("should-not-be-called")
    agent = MemoryWordAgent(llm)
    # too_easy → EASY，不调 LLM。
    r = await agent.judge(word="w", context_sentences=["s"], understanding="x", too_easy=True)
    assert r.rating == ReviewRating.EASY
    # 空理解 → AGAIN，不调 LLM。
    r = await agent.judge(word="w", context_sentences=["s"], understanding="  ")
    assert r.rating == ReviewRating.AGAIN
    assert llm.calls == []


@pytest.mark.asyncio
async def test_memory_word_unparseable_falls_back_partial():
    agent = MemoryWordAgent(FakeLLM("完全不是 JSON"))
    r = await agent.judge(word="w", context_sentences=["s"], understanding="something")
    assert r.verdict == "partial" and r.rating == ReviewRating.HARD


@pytest.mark.asyncio
async def test_review_advances_fsrs_and_status(db: Database):
    """F3a 推进：GOOD 评级 → fsrs_state 推进 + review_count+1 + 排出 due 队列。"""
    repo = SqliteWordRepository(db)
    scheduler = FsrsScheduler()
    entry = VocabEntry(
        word="ephemeral", lemma="ephemeral", context_sentences=["A fad is ephemeral."]
    )
    await repo.add(entry)

    # 模拟 review 路由的核心推进逻辑（与 app.api.review.submit 一致）。
    before = entry.fsrs_state.review_count
    entry.fsrs_state = scheduler.review(entry.fsrs_state, ReviewRating.GOOD)
    entry.status = VocabStatus.LEARNING
    await repo.update(entry)

    got = await repo.get(entry.id)
    assert got.fsrs_state.review_count == before + 1
    assert got.fsrs_state.due is not None  # 已排程
    assert got.status == VocabStatus.LEARNING


# ── 回归：review 团队评审指出的边界 ─────────────────────────────────
@pytest.mark.asyncio
async def test_judge_passes_all_contexts_to_llm():
    """多义并呈：判断时把全部来源句交给 LLM，而非只第一句（ADR-010）。"""
    llm = FakeLLM(json.dumps({"verdict": "correct"}))
    agent = MemoryWordAgent(llm)
    await agent.judge(
        word="bank",
        context_sentences=["He sat by the river bank.", "I went to the bank."],
        understanding="河岸",
    )
    sent = llm.calls[0][1].content  # user 消息
    assert "river bank" in sent and "I went to the bank." in sent


def test_consecutive_good_resets_on_bad_answer():
    """连续答好计数：GOOD 累加，AGAIN 清零（供毕业判断用连续而非累计）。"""
    scheduler = FsrsScheduler()
    state = VocabEntry(word="w", lemma="w").fsrs_state
    state = scheduler.review(state, ReviewRating.GOOD)
    assert state.consecutive_good == 1
    state = scheduler.review(state, ReviewRating.AGAIN)
    assert state.consecutive_good == 0  # 答差清零
    assert state.review_count == 2  # 累计仍 +1
    state = scheduler.review(state, ReviewRating.GOOD)
    assert state.consecutive_good == 1


def test_graduation_needs_consecutive_not_cumulative_good():
    """again,again,good 不该毕业；good,good,good 才毕业（用连续计数）。"""
    from app.api.review import _advance_status

    scheduler = FsrsScheduler()
    entry = VocabEntry(word="w", lemma="w", status=VocabStatus.LEARNING)
    # again, again, good：累计 3 次，但连续答好只有 1 → 不毕业。
    for rating in (ReviewRating.AGAIN, ReviewRating.AGAIN, ReviewRating.GOOD):
        entry.fsrs_state = scheduler.review(entry.fsrs_state, rating)
        entry.status = _advance_status(entry, rating)
    assert entry.status == VocabStatus.LEARNING

    # 再连续两次 good → 连续 3 次 → 毕业。
    for _ in range(2):
        entry.fsrs_state = scheduler.review(entry.fsrs_state, ReviewRating.GOOD)
        entry.status = _advance_status(entry, ReviewRating.GOOD)
    assert entry.status == VocabStatus.KNOWN


@pytest.mark.asyncio
async def test_collect_requeues_known_lemma_with_new_context(db: Database):
    """已毕业（known）的词又被标不认识并带新来源句 → 拉回 learning，重新进 due 队列。"""
    repo = SqliteWordRepository(db)
    agent = TokenizerAgent(None, repo)
    # 先入一条并人为标 known。
    entry = VocabEntry(
        word="bank", lemma="bank", context_sentences=["I went to the bank."],
        status=VocabStatus.KNOWN,
    )
    await repo.add(entry)

    # 用户在新文章里遇到不同义项、再次标「不认识」。
    out = await agent.collect(
        [CollectItem(word="bank", lemma="bank", context_sentences=["He sat by the river bank."])]
    )
    assert out[0].status == VocabStatus.LEARNING  # 已拉回
    assert len(out[0].context_sentences) == 2  # 新义项已合并
    # 重新进入到期队列（known 会被过滤，learning 不会）。
    assert "bank" in {e.lemma for e in await repo.list_due()}


def test_resolve_task_llm_missing_provider_is_config_error():
    """Settings 指定的 provider 不在 AppConfig（拼错/未配/大小写不符）→ 配置错误而非 KeyError。"""
    settings = Settings()
    settings.model_config_.scoring = ModelAssignment(provider="Claude", model="opus")
    config = AppConfig(llm_providers={})  # 没有任何 provider
    with pytest.raises(LLMNotConfiguredError):
        resolve_task_llm("scoring", settings=settings, config=config, default_llm=None)
