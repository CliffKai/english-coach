"""调度层（L2，docs/07）：FSRS 间隔重复调度器。

给定 `fsrs_state` 算「到期日」并在一次复习后推进状态。**按词调度（per-lemma）**：
一个 VocabEntry 一个 fsrs_state（ADR-010）。功能3（理解式背词）的引擎。

业务只依赖 `Scheduler` 接口；默认实现 `FsrsScheduler` 包装官方 fsrs 库。
ReviewRating 是本项目对外的离散评级（again/hard/good/easy），L3 的 MemoryWordAgent
负责把「用户复述理解」的模糊判断映射到它（那层映射见 07 已知风险，属 L3）。
"""

from app.scheduling.fsrs_scheduler import (
    FsrsScheduler,
    ReviewRating,
    Scheduler,
)

__all__ = ["Scheduler", "FsrsScheduler", "ReviewRating"]
