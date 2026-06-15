"""FSRS 调度器（L2，docs/07）。

职责（只做调度，不碰存储）：
1. `review(state, rating, now)`：吃当前 `FsrsState` + 一次评级 → 推进出新 `FsrsState`
   （含新到期日 due）。复习次数 review_count 在此 +1。
2. `is_due(state, now)` / `retrievability(state, now)`：到期判断与记忆留存率（首页排序用）。

与 fsrs 库的边界：本模块在 `FsrsState`（我们的持久化模型）与 `fsrs.Card`（库的运行时
对象）之间互转。`FsrsState` 字段刻意镜像 `Card` 的可序列化字段，做到无损往返
（见 app/models/entities.py FsrsState）。**按词调度**：一个 fsrs_state 对一个 lemma（ADR-010）。

到期队列的「过滤+排序」由 WordRepository.list_due 负责（L1 已实现按 due 升序、空 due 优先）；
本模块只回答单个词的 due/留存率，不重复实现批量查询。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from enum import IntEnum

from app.models import FsrsState


class ReviewRating(IntEnum):
    """复习评级。整数值对齐 fsrs.Rating（Again=1 Hard=2 Good=3 Easy=4），可直接互转。

    L3 的 MemoryWordAgent 把开放式「用户复述理解」的判断映射到这四档（07 已知风险），
    本层只接收已离散化的评级，不参与那层模糊判断。
    """

    AGAIN = 1  # 没答上来 / 理解错 → 重新学
    HARD = 2  # 勉强，吃力
    GOOD = 3  # 正常答对
    EASY = 4  # 轻松，太简单


class Scheduler(ABC):
    """间隔重复调度接口。默认实现 FsrsScheduler。"""

    @abstractmethod
    def review(
        self, state: FsrsState, rating: ReviewRating, *, now: datetime | None = None
    ) -> FsrsState:
        """应用一次复习评级，返回推进后的新状态（含新 due，review_count+1）。"""

    @abstractmethod
    def is_due(self, state: FsrsState, *, now: datetime | None = None) -> bool:
        """该词此刻是否到期（due 为空视为「立即可学」，到期）。"""

    @abstractmethod
    def retrievability(self, state: FsrsState, *, now: datetime | None = None) -> float:
        """当前预测记忆留存率 [0,1]。未复习过（无 stability）记 0。"""


def _now(now: datetime | None) -> datetime:
    return now if now is not None else datetime.now(UTC)


class FsrsScheduler(Scheduler):
    """官方 fsrs 库（py-fsrs 6.x）的封装。

    desired_retention 默认 0.9（fsrs 默认值，约定「九成记得住才算到期复习」）。
    enable_fuzzing 默认开启：给到期日加少量随机抖动，避免同批词永远同一天到期堆积。
    单用户单机，参数全用库默认值；个性化参数（optimizer）属阶段2。
    """

    def __init__(
        self, *, desired_retention: float = 0.9, enable_fuzzing: bool = True
    ) -> None:
        from fsrs import Scheduler as _FsrsLib

        self._lib = _FsrsLib(
            desired_retention=desired_retention, enable_fuzzing=enable_fuzzing
        )

    # ── FsrsState <-> fsrs.Card ──────────────────────────────────────
    def _to_card(self, state: FsrsState):
        from fsrs import Card, State

        # legacy 归一化：本模块早期版本（及 L0 的 FsrsState 默认值）把「未复习」序列化成
        # stability=0.0 / difficulty=0.0，而 fsrs 6.x 用 None 表示未复习。把这种旧行的
        # 零值当作 None 喂给库，否则 review() 会 ZeroDivisionError（0.0 的负幂）。
        # 判据用 fsrs 原生信号 last_review is None（未复习过 → 无稳定性可言）。
        unreviewed = state.last_review is None
        stability = None if unreviewed else (state.stability or None)
        difficulty = None if unreviewed else state.difficulty
        return Card(
            state=State(state.state),
            step=state.step,
            stability=stability,
            difficulty=difficulty,
            due=state.due,
            last_review=state.last_review,
        )

    def _is_unreviewed(self, state: FsrsState) -> bool:
        """未复习过（含 legacy 0.0 零值）→ 无留存率/无需库计算。"""
        return state.last_review is None or not state.stability

    def _from_card(self, card, *, review_count: int, consecutive_good: int) -> FsrsState:
        return FsrsState(
            state=int(card.state),
            step=card.step,
            stability=card.stability,
            difficulty=card.difficulty,
            due=card.due,
            last_review=card.last_review,
            review_count=review_count,
            consecutive_good=consecutive_good,
        )

    def review(
        self, state: FsrsState, rating: ReviewRating, *, now: datetime | None = None
    ) -> FsrsState:
        from fsrs import Rating

        card = self._to_card(state)
        new_card, _log = self._lib.review_card(
            card, Rating(int(rating)), review_datetime=_now(now)
        )
        # 连续答好计数：GOOD/EASY 累加，AGAIN/HARD 清零（供 F3a「连续 N 次才毕业」判断）。
        good = rating in (ReviewRating.GOOD, ReviewRating.EASY)
        consecutive_good = state.consecutive_good + 1 if good else 0
        return self._from_card(
            new_card,
            review_count=state.review_count + 1,
            consecutive_good=consecutive_good,
        )

    def is_due(self, state: FsrsState, *, now: datetime | None = None) -> bool:
        if state.due is None:
            return True  # 刚收集、未排程 → 立即可学
        return state.due <= _now(now)

    def retrievability(self, state: FsrsState, *, now: datetime | None = None) -> float:
        if self._is_unreviewed(state):
            return 0.0  # 从未复习（含 legacy 0.0），无留存率可言
        return self._lib.get_card_retrievability(
            self._to_card(state), current_datetime=_now(now)
        )
