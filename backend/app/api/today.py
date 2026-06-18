"""「今日学习」聚合首页路由（L5，ADR-009）。

GET /api/today  把日常复习/练习任务聚合成一页「今天该干什么」：
  - 待复习生词数（FSRS 到期队列，功能3 消费）+ 几个示例词
  - 待巩固错题数（错题本 resolved=False，功能2 产出）+ 几条示例
  - 推荐一个话题（功能2 练习入口）

聚合是只读、确定性的（不调 LLM）：把上游已有数据拼起来即可，保证首页加载快、可离线测。
**必须等 F1/F3/F2 都有数据产出后才有意义**（07：上游空则页面空）——上游为空时各区返回 0 / 空列表，
前端据此显示「今天没有待办」而非报错。

话题推荐（确定性，不调 LLM）：优先取未解决错题里出现最多的 topic（哪儿弱补哪儿）；
都没有则从一组内置雅思/托福风格话题里按「当天」轮换挑一个（无随机，便于测试）。
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api import deps
from app.container import Container
from app.models import VocabEntry

router = APIRouter(prefix="/api/today", tags=["today"])

ContainerDep = Annotated[Container, Depends(deps.container)]

# 首页各区展示的示例条数（只为「让用户看一眼」，完整列表点进各功能页看）。
_DUE_PREVIEW = 5
_ERROR_PREVIEW = 5

# 内置话题池（雅思/托福常见话题），无未解决错题可参照时按「当天」轮换推荐。
# 顺序固定 + 按 day-of-year 取模 → 同一天推荐稳定、跨天轮换，且不引入随机（测试可断言）。
_FALLBACK_TOPICS = [
    "Describe a skill you would like to learn and why.",
    "Do the advantages of remote work outweigh the disadvantages?",
    "Should governments invest more in public transport than roads?",
    "Talk about a book or film that changed your perspective.",
    "Is social media doing more harm than good to society?",
    "Describe a place you find relaxing.",
    "Should higher education be free for everyone?",
    "Discuss the impact of artificial intelligence on jobs.",
]


class DueWordPreview(BaseModel):
    entry_id: str
    word: str
    lemma: str


class ErrorPreview(BaseModel):
    id: str
    type: str
    original: str
    correction: str


class TopicRecommendation(BaseModel):
    """推荐话题 + 来源说明（前端可标「针对你常错的 X 话题」）。"""

    topic: str
    # weak_area：来自未解决错题里最多的 topic（哪儿弱补哪儿）；rotating：内置池轮换。
    reason: str  # weak_area | rotating


class TodayResponse(BaseModel):
    """「今日学习」聚合。各计数为 0 / 列表为空时前端显示「今天无待办」。"""

    due_count: int
    due_preview: list[DueWordPreview]
    unresolved_error_count: int
    error_preview: list[ErrorPreview]
    recommended_topic: TopicRecommendation


def _recommend_topic(error_topics: list[str | None], *, now: datetime) -> TopicRecommendation:
    """确定性推荐：未解决错题里最多的 topic 优先；否则内置池按当天轮换。"""
    named = [t for t in error_topics if t]
    if named:
        # 取出现最多的话题（并列时 Counter.most_common 保留首次出现序，稳定可测）。
        top = Counter(named).most_common(1)[0][0]
        return TopicRecommendation(topic=top, reason="weak_area")
    # 无可参照的弱项 → 按 day-of-year 轮换内置池（同一天稳定、跨天换）。
    idx = now.timetuple().tm_yday % len(_FALLBACK_TOPICS)
    return TopicRecommendation(topic=_FALLBACK_TOPICS[idx], reason="rotating")


@router.get("")
async def today(c: ContainerDep) -> TodayResponse:
    """聚合首页数据。只读、确定性、不调 LLM；上游空则各区为 0/空。"""
    words = deps.require_words(c)
    errors_repo = deps.require_errors(c)
    settings = await deps.load_settings(c)

    # 待复习生词：FSRS 到期队列（list_due 已按 due 升序、空 due 优先，L1/L2）。
    # 显式标注：Repository 有名为 `list` 的方法遮蔽内建 list，mypy 会错判 list_due 返回值
    # 不可索引（同 review.py），标注本地变量即恢复正确类型。
    due: list[VocabEntry] = await words.list_due(user_id=settings.user_id)
    due_preview = [
        DueWordPreview(entry_id=e.id, word=e.word, lemma=e.lemma) for e in due[:_DUE_PREVIEW]
    ]

    # 待巩固错题：resolved=False（首页只督促还没解决的，ADR：错题毕业后不再唠叨）。
    unresolved = await errors_repo.list(user_id=settings.user_id, resolved=False)
    error_preview = [
        ErrorPreview(id=e.id, type=e.type.value, original=e.original, correction=e.correction)
        for e in unresolved[:_ERROR_PREVIEW]
    ]

    recommended = _recommend_topic(
        [e.topic for e in unresolved], now=datetime.now(UTC)
    )

    return TodayResponse(
        due_count=len(due),
        due_preview=due_preview,
        unresolved_error_count=len(unresolved),
        error_preview=error_preview,
        recommended_topic=recommended,
    )
