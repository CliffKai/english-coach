"""L1 验证（docs/07）：LocalAdapter(SQLite) 能存取四类实体。

用内存 SQLite，全程离线、无网络。覆盖：往返一致、JSON 嵌套结构、lemma 查重、
错题批量回填、settings UPSERT、list_due 语义。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.adapters.local import (
    SqliteErrorRepository,
    SqliteSessionRepository,
    SqliteSettingsRepository,
    SqliteWordRepository,
)
from app.db.connection import Database
from app.models import (
    ErrorEntry,
    ErrorType,
    FsrsState,
    PracticeMode,
    PracticeSession,
    Settings,
    VocabEntry,
    VocabStatus,
)
from app.models.entities import ModelAssignment, UserUnderstanding


@pytest.fixture
def db() -> Database:
    database = Database(":memory:")
    yield database
    database.close()


# ── VocabEntry ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_vocab_roundtrip_preserves_nested_json(db: Database):
    repo = SqliteWordRepository(db)
    entry = VocabEntry(
        word="bank",
        lemma="bank",
        context_sentences=["He sat by the river bank.", "I went to the bank."],
        user_understanding=[UserUnderstanding(text="河岸 / 银行，看语境")],
    )
    await repo.add(entry)

    got = await repo.get(entry.id)
    assert got is not None
    assert got.word == "bank"
    # 多义词存多条来源句（ADR-004）。
    assert got.context_sentences == entry.context_sentences
    assert got.user_understanding[0].text == "河岸 / 银行，看语境"
    assert isinstance(got.fsrs_state, FsrsState)


@pytest.mark.asyncio
async def test_vocab_get_by_lemma_for_dedup(db: Database):
    repo = SqliteWordRepository(db)
    await repo.add(VocabEntry(word="running", lemma="run", context_sentences=["I am running."]))
    got = await repo.get_by_lemma("run")
    assert got is not None and got.word == "running"
    assert await repo.get_by_lemma("walk") is None


@pytest.mark.asyncio
async def test_vocab_update_and_delete(db: Database):
    repo = SqliteWordRepository(db)
    entry = VocabEntry(word="ephemeral", lemma="ephemeral")
    await repo.add(entry)

    entry.status = VocabStatus.LEARNING
    entry.context_sentences.append("A fad is ephemeral.")
    await repo.update(entry)
    got = await repo.get(entry.id)
    assert got.status == VocabStatus.LEARNING
    assert "A fad is ephemeral." in got.context_sentences

    await repo.delete(entry.id)
    assert await repo.get(entry.id) is None


@pytest.mark.asyncio
async def test_vocab_list_due_orders_null_due_first_and_skips_known(db: Database):
    repo = SqliteWordRepository(db)
    now = datetime.now(UTC)

    fresh = VocabEntry(word="new1", lemma="new1")  # due=None → 立即可学
    overdue = VocabEntry(
        word="old", lemma="old", fsrs_state=FsrsState(due=now - timedelta(days=1))
    )
    future = VocabEntry(
        word="later", lemma="later", fsrs_state=FsrsState(due=now + timedelta(days=3))
    )
    known = VocabEntry(word="mastered", lemma="mastered", status=VocabStatus.KNOWN)
    for e in (fresh, overdue, future, known):
        await repo.add(e)

    due = await repo.list_due()
    lemmas = [e.lemma for e in due]
    assert "later" not in lemmas  # 未到期
    assert "mastered" not in lemmas  # known 不复习
    assert lemmas[0] == "new1"  # 空 due 优先
    assert "old" in lemmas

    assert len(await repo.list_due(limit=1)) == 1


# ── ErrorEntry ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_error_add_many_and_filter_by_resolved(db: Database):
    repo = SqliteErrorRepository(db)
    await repo.add_many(
        [
            ErrorEntry(
                type=ErrorType.GRAMMAR,
                original="He go to school.",
                correction="He goes to school.",
                explanation="第三人称单数",
            ),
            ErrorEntry(
                type=ErrorType.COLLOCATION,
                original="do a mistake",
                correction="make a mistake",
                explanation="搭配",
                resolved=True,
            ),
        ]
    )
    assert len(await repo.list()) == 2
    unresolved = await repo.list(resolved=False)
    assert len(unresolved) == 1 and unresolved[0].type == ErrorType.GRAMMAR


@pytest.mark.asyncio
async def test_error_update_resolved(db: Database):
    repo = SqliteErrorRepository(db)
    e = ErrorEntry(
        type=ErrorType.SPELLING,
        original="recieve",
        correction="receive",
        explanation="i 在 e 前（除非在 c 后）",
    )
    await repo.add(e)
    e.resolved = True
    await repo.update(e)
    assert (await repo.get(e.id)).resolved is True


# ── PracticeSession ─────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_session_roundtrip_scores_json_and_ended_early(db: Database):
    repo = SqliteSessionRepository(db)
    s = PracticeSession(
        mode=PracticeMode.FREE_WRITE,
        topic="环保",
        transcript="My essay...",
        scores={"task_response": 6.5, "coherence": 6.0},
        error_ids=["e1", "e2"],
        ended_early=True,
    )
    await repo.add(s)
    got = await repo.get(s.id)
    assert got.scores["task_response"] == 6.5
    assert got.error_ids == ["e1", "e2"]
    assert got.ended_early is True

    # scores=None（未打分）也要往返正确。
    s2 = PracticeSession(mode=PracticeMode.GUIDED_WRITE)
    await repo.add(s2)
    assert (await repo.get(s2.id)).scores is None


# ── Settings ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_settings_upsert_and_model_config_alias(db: Database):
    repo = SqliteSettingsRepository(db)
    assert await repo.get() is None  # 初始无配置

    s = Settings(level_baseline="B1")
    s.model_config_.scoring = ModelAssignment(provider="claude", model="opus")
    await repo.save(s)

    got = await repo.get()
    assert got.level_baseline == "B1"
    assert got.model_config_.scoring.provider == "claude"

    # 再 save 同 user → UPSERT 覆盖，不报主键冲突，仍是单行。
    s.level_baseline = "B2"
    await repo.save(s)
    assert (await repo.get()).level_baseline == "B2"
