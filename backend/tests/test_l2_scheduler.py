"""L2 验证（docs/07）：FSRS 调度器。

✅ 标准：一批词 → 到期复习队列。本文件覆盖单词调度语义（推进/到期/留存率/往返），
批量「到期队列」的过滤排序在 WordRepository.list_due（见 test_l1_local_repos）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models import FsrsState
from app.scheduling import FsrsScheduler, ReviewRating

pytest.importorskip("fsrs")


@pytest.fixture
def scheduler() -> FsrsScheduler:
    # 关掉 fuzzing，到期日可确定性断言。
    return FsrsScheduler(enable_fuzzing=False)


def test_fresh_state_is_due(scheduler: FsrsScheduler):
    # 刚收集（due=None）→ 立即到期可学。
    assert scheduler.is_due(FsrsState()) is True


def test_review_advances_state_and_sets_due(scheduler: FsrsScheduler):
    now = datetime(2026, 6, 15, tzinfo=UTC)
    new = scheduler.review(FsrsState(), ReviewRating.GOOD, now=now)
    # 复习后：填充 stability/difficulty、推进 last_review、计数 +1、有了新 due。
    assert new.stability is not None and new.stability > 0
    assert new.difficulty is not None
    assert new.last_review == now
    assert new.review_count == 1
    assert new.due is not None


def test_again_schedules_sooner_than_easy(scheduler: FsrsScheduler):
    now = datetime(2026, 6, 15, tzinfo=UTC)
    # 先到稳定复习态，再比较 Again vs Easy 的下次间隔。
    base = scheduler.review(FsrsState(), ReviewRating.GOOD, now=now)
    base = scheduler.review(base, ReviewRating.GOOD, now=now + timedelta(minutes=10))
    later = now + timedelta(days=1)
    again = scheduler.review(base, ReviewRating.AGAIN, now=later)
    easy = scheduler.review(base, ReviewRating.EASY, now=later)
    # 答不上来 → 更快重来；轻松 → 间隔更长。
    assert again.due < easy.due


def test_retrievability_decays_over_time(scheduler: FsrsScheduler):
    now = datetime(2026, 6, 15, tzinfo=UTC)
    state = scheduler.review(FsrsState(), ReviewRating.GOOD, now=now)
    # 未复习过的状态留存率记 0。
    assert scheduler.retrievability(FsrsState()) == 0.0
    # 复习后随时间衰减。
    r_soon = scheduler.retrievability(state, now=now)
    r_later = scheduler.retrievability(state, now=now + timedelta(days=30))
    assert r_soon > r_later


def test_state_roundtrips_through_json(scheduler: FsrsScheduler):
    # FsrsState 镜像 fsrs.Card，序列化往返不丢字段（L1 LocalAdapter 即以 JSON 存它）。
    now = datetime(2026, 6, 15, tzinfo=UTC)
    state = scheduler.review(FsrsState(), ReviewRating.HARD, now=now)
    restored = FsrsState.model_validate_json(state.model_dump_json())
    assert restored == state
    # 还原后仍可继续调度。
    nxt = scheduler.review(restored, ReviewRating.GOOD, now=now + timedelta(days=1))
    assert nxt.review_count == 2


def test_legacy_zero_valued_state_is_handled(scheduler: FsrsScheduler):
    # 旧库/旧 FsrsState 默认把「未复习」存成 stability=0.0 / difficulty=0.0 / last_review=None。
    # 这种 legacy 行不能让 0.0 流进 fsrs（会 ZeroDivisionError 0.0 的负幂）。
    now = datetime(2026, 6, 15, tzinfo=UTC)
    legacy = FsrsState(
        state=1, step=0, stability=0.0, difficulty=0.0, due=None, last_review=None
    )
    # 留存率：未复习 → 0，不报错。
    assert scheduler.retrievability(legacy, now=now) == 0.0
    # is_due：due=None → 立即可学。
    assert scheduler.is_due(legacy, now=now) is True
    # review：能正常推进，零值被当作未复习处理，而非崩溃。
    advanced = scheduler.review(legacy, ReviewRating.GOOD, now=now)
    assert advanced.stability is not None and advanced.stability > 0
    assert advanced.review_count == 1


def test_due_state_not_due_in_future(scheduler: FsrsScheduler):
    now = datetime(2026, 6, 15, tzinfo=UTC)
    state = scheduler.review(FsrsState(), ReviewRating.EASY, now=now)
    # 刚复习完，立刻不到期；到了 due 之后到期。
    assert scheduler.is_due(state, now=now) is False
    assert scheduler.is_due(state, now=state.due + timedelta(seconds=1)) is True
