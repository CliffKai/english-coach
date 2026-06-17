"""ADR-015 验证：用户主动补录生词 —— 来源句三种来源（自填 / 文中提取 / LLM 造句）。

全程离线：mock LLM（造句不发网络）+ 内存 SQLite + 真实 SpacyTokenizer。
覆盖 manual_candidate 的优先级分支与查重合并；缺 en_core_web_sm 时切词分支跳过。
"""

from __future__ import annotations

import pytest

from app.adapters.llm import LLMResponse
from app.adapters.local import SqliteWordRepository
from app.agents.tokenizer_agent import TokenizerAgent
from app.db.connection import Database
from app.nlp.tokenizer import SpacyTokenizer

spacy = pytest.importorskip("spacy")
_HAS_MODEL = spacy.util.is_package("en_core_web_sm")
_needs_model = pytest.mark.skipif(not _HAS_MODEL, reason="en_core_web_sm 未安装")


class FakeLLM:
    """造句假 LLM：回固定例句，记录是否被调用（验证零 LLM 路径不触发）。"""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list = []

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


# ── 1. 用户自填例句：直接采用，不调 LLM ──────────────────────────────
@pytest.mark.asyncio
async def test_manual_self_filled_sentence_no_llm(db: Database):
    repo = SqliteWordRepository(db)
    llm = FakeLLM("should-not-be-called")
    agent = TokenizerAgent(SpacyTokenizer() if _HAS_MODEL else None, repo)
    cand = await agent.manual_candidate(
        "benefit", sentence="This change will benefit everyone.", llm=llm
    )
    assert cand.context_sentences == ["This change will benefit everyone."]
    assert llm.calls == []  # 自填例句零 LLM


# ── 2. 从本文提取：取原句，不调 LLM ─────────────────────────────────
@_needs_model
@pytest.mark.asyncio
async def test_manual_from_text_extracts_source_sentence(db: Database):
    repo = SqliteWordRepository(db)
    llm = FakeLLM("should-not-be-called")
    agent = TokenizerAgent(SpacyTokenizer(), repo)
    text = "I love hiking. The benefit of exercise is huge."
    cand = await agent.manual_candidate("benefit", text=text, llm=llm)
    assert cand.lemma == "benefit"
    assert cand.context_sentences == ["The benefit of exercise is huge."]
    assert llm.calls == []  # 文中定位零 LLM


@_needs_model
@pytest.mark.asyncio
async def test_manual_from_text_matches_inflected_form(db: Database):
    """用户填 "running"，文本里是 "running" → 命中并还原 lemma "run"。"""
    repo = SqliteWordRepository(db)
    agent = TokenizerAgent(SpacyTokenizer(), repo)
    text = "She was running in the park yesterday."
    cand = await agent.manual_candidate("running", text=text)
    assert cand.lemma == "run"
    assert "running" in cand.context_sentences[0]


# ── 3. LLM 造句：词不在文本且无自填例句 ─────────────────────────────
@_needs_model
@pytest.mark.asyncio
async def test_manual_generates_sentence_when_not_in_text(db: Database):
    repo = SqliteWordRepository(db)
    llm = FakeLLM("Serendipity brought them together.")
    agent = TokenizerAgent(SpacyTokenizer(), repo)
    # text 里没有 serendipity → 触发造句。
    cand = await agent.manual_candidate(
        "serendipity", text="I like apples.", llm=llm
    )
    assert cand.context_sentences == ["Serendipity brought them together."]
    assert llm.calls, "词不在文本中应触发 LLM 造句"


@pytest.mark.asyncio
async def test_manual_no_llm_falls_back_to_no_context(db: Database):
    """无自填、无文本、无 LLM（未配模型）→ 入库无来源句的纯词，不报错。"""
    repo = SqliteWordRepository(db)
    agent = TokenizerAgent(SpacyTokenizer() if _HAS_MODEL else None, repo)
    cand = await agent.manual_candidate("serendipity", llm=None)
    assert cand.lemma == "serendipity"
    assert cand.context_sentences == []


@pytest.mark.asyncio
async def test_manual_llm_failure_degrades_gracefully(db: Database):
    """造句调用抛错 → 降级为无来源句，不冒泡。"""

    class BoomLLM(FakeLLM):
        async def chat(self, messages, *, model=None, temperature=0.7, max_tokens=None):
            raise RuntimeError("network down")

    repo = SqliteWordRepository(db)
    agent = TokenizerAgent(SpacyTokenizer() if _HAS_MODEL else None, repo)
    cand = await agent.manual_candidate("serendipity", llm=BoomLLM("x"))
    assert cand.context_sentences == []


# ── 入库链复用：补录走 collect，按 lemma 与既有条目合并 ──────────────
@pytest.mark.asyncio
async def test_manual_merges_into_existing_entry_by_lemma(db: Database):
    repo = SqliteWordRepository(db)
    agent = TokenizerAgent(SpacyTokenizer() if _HAS_MODEL else None, repo)
    cand = await agent.manual_candidate(
        "ephemeral", sentence="Fame is ephemeral."
    )
    from app.agents.tokenizer_agent import CollectItem

    await agent.collect([CollectItem(**cand.model_dump(exclude={"zipf"}))])
    # 再补一条不同来源句 → 合并到同一 entry。
    cand2 = await agent.manual_candidate(
        "ephemeral", sentence="The trend was ephemeral."
    )
    await agent.collect([CollectItem(**cand2.model_dump(exclude={"zipf"}))])

    stored = await repo.list()
    assert len(stored) == 1
    assert len(stored[0].context_sentences) == 2
