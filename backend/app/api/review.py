"""理解式背词路由（消费 F1 生词 + L2 FSRS 队列）。

F3a 逐词理解背（L3）：
  GET  /api/review/next     取下一张到期复习卡（词 + 来源句，不含任何释义，ADR-004）
  POST /api/review/submit   提交「用自己的话说的理解」→ LLM 判断 → 映射 FSRS 评级 → 推进调度

F3b 语境造句背（L4）：
  POST /api/review/passage  用一批到期生词造一段短文供翻译（不含释义，ADR-004）
  POST /api/review/passage/check  提交翻译 → 逐词检验理解 → 各自映射 FSRS 评级 → 推进调度

判断用 reasoning 档模型。模糊判断→离散评级的映射见 ADR-011（在 MemoryWordAgent）。
推进后写回 fsrs_state、追加 user_understanding 历史、按状态流转 status。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.agents.memory_word import MemoryWordAgent
from app.api import deps
from app.container import Container
from app.models import PublicUser, VocabEntry, VocabStatus
from app.models.entities import UserUnderstanding
from app.scheduling import ReviewRating

router = APIRouter(prefix="/api/review", tags=["review"])

ContainerDep = Annotated[Container, Depends(deps.container)]
UserDep = Annotated[PublicUser, Depends(deps.optional_current_user)]


class ReviewCard(BaseModel):
    """一张复习卡。只给词 + 来源句，意思由用户当场重新理解出来（ADR-004）。"""

    entry_id: str
    word: str
    lemma: str
    context_sentences: list[str]
    review_count: int


class SubmitRequest(BaseModel):
    entry_id: str
    understanding: str  # 用户用自己的话说的理解
    too_easy: bool = False  # 用户自评「太简单」（秒答）→ 直接 EASY


class SubmitResponse(BaseModel):
    verdict: str  # correct | partial | wrong
    rating: ReviewRating  # 映射出的 FSRS 评级（ADR-011）
    feedback: str  # 简短反馈（非标准答案）
    status: VocabStatus  # 推进后的状态
    next_due: str | None  # 下次到期日（ISO，None 表示未排程）


@router.get("/next")
async def next_card(c: ContainerDep, user: UserDep) -> ReviewCard | None:
    """取下一张到期复习卡。队列空（今日无到期）→ 返回 null。"""
    words = deps.require_words(c)
    due = await words.list_due(user_id=user.id, limit=1)
    if not due:
        return None
    e = due[0]
    return ReviewCard(
        entry_id=e.id,
        word=e.word,
        lemma=e.lemma,
        context_sentences=e.context_sentences,
        review_count=e.fsrs_state.review_count,
    )


@router.post("/submit")
async def submit(req: SubmitRequest, c: ContainerDep, user: UserDep) -> SubmitResponse:
    """提交理解 → 判断 → 推进 FSRS。"""
    words = deps.require_words(c)
    scheduler = deps.require_scheduler(c)
    settings = await deps.load_settings(c)

    entry = await words.get(req.entry_id, user_id=user.id)
    if entry is None:
        raise HTTPException(status_code=404, detail="生词不存在")

    llm = deps.require_task_llm(c, "reasoning", settings=settings)
    agent = MemoryWordAgent(llm)
    # 把卡上展示的全部来源句交给判断（多义并呈，ADR-010）——避免「展示多句、只判第一句」
    # 导致用户解释了后面的句子却被判错。
    judged = await agent.judge(
        word=entry.word,
        context_sentences=entry.context_sentences,
        understanding=req.understanding,
        too_easy=req.too_easy,
    )

    # 推进 FSRS 状态 + 追加理解历史 + 流转 status。
    entry.fsrs_state = scheduler.review(entry.fsrs_state, judged.rating)
    if req.understanding.strip():
        entry.user_understanding.append(UserUnderstanding(text=req.understanding.strip()))
    entry.status = _advance_status(entry, judged.rating)
    await words.update(entry)

    return SubmitResponse(
        verdict=judged.verdict,
        rating=judged.rating,
        feedback=judged.feedback,
        status=entry.status,
        next_due=entry.fsrs_state.due.isoformat() if entry.fsrs_state.due else None,
    )


# ── F3b 语境造句背 ──────────────────────────────────────────────
class PassageRequest(BaseModel):
    """造短文：默认取到期队列里的一批生词；可指定 entry_ids 精确选词。"""

    entry_ids: list[str] | None = None  # 指定生词条目；None 则取到期队列
    limit: int = 5  # 取到期队列时的词数（默认 5，造文不宜过多）
    topic: str | None = None  # 话题联动（贴近功能2 话题，docs/01 跨功能能力5）


class PassageWord(BaseModel):
    """短文涉及的一个目标词（entry_id 供后续检验对齐回库）。"""

    entry_id: str
    word: str
    lemma: str


class PassageResponse(BaseModel):
    """造出的短文 + 目标词（不含任何释义，ADR-004：理解由翻译时重建）。"""

    text: str
    words: list[PassageWord]  # 短文实际用到的目标词


class PassageCheckRequest(BaseModel):
    """提交翻译检验。entries 为造文时返回的 (entry_id, lemma) 对，回传以对齐推进。"""

    passage: str
    lemmas: list[str]  # 造文返回的 words_used（lemma）
    translation: str


class WordCheckResult(BaseModel):
    verdict: str
    rating: ReviewRating
    feedback: str
    lemma: str
    status: VocabStatus
    next_due: str | None


class PassageCheckResponse(BaseModel):
    checks: list[WordCheckResult]


@router.post("/passage")
async def make_passage(req: PassageRequest, c: ContainerDep, user: UserDep) -> PassageResponse:
    """用一批到期生词造短文供翻译（F3b）。不含释义（ADR-004）。"""
    words = deps.require_words(c)
    settings = await deps.load_settings(c)

    # 选词：指定 entry_ids 则按 id 取；否则取到期队列前 limit 个。
    if req.entry_ids:
        picked: list[VocabEntry] = []
        for eid in req.entry_ids:
            e = await words.get(eid, user_id=user.id)
            if e is not None:
                picked.append(e)
    else:
        picked = await words.list_due(user_id=user.id, limit=req.limit)
    if not picked:
        return PassageResponse(text="", words=[])

    # lemma → 条目映射（造文按 lemma 选词，检验时按 lemma 对齐回条目）。
    by_lemma = {e.lemma: e for e in picked}
    llm = deps.require_task_llm(c, "reasoning", settings=settings)
    passage = await MemoryWordAgent(llm).make_passage(
        list(by_lemma), topic=req.topic, baseline=settings.level_baseline
    )
    used = [
        PassageWord(entry_id=by_lemma[lm].id, word=by_lemma[lm].word, lemma=lm)
        for lm in passage.words_used
        if lm in by_lemma
    ]
    return PassageResponse(text=passage.text, words=used)


@router.post("/passage/check")
async def check_passage(
    req: PassageCheckRequest, c: ContainerDep, user: UserDep
) -> PassageCheckResponse:
    """提交翻译 → 逐词检验语境理解 → 各自映射 FSRS 评级 → 推进调度（F3b）。"""
    words = deps.require_words(c)
    scheduler = deps.require_scheduler(c)
    settings = await deps.load_settings(c)

    llm = deps.require_task_llm(c, "reasoning", settings=settings)
    checks = await MemoryWordAgent(llm).check_translation(
        passage=req.passage, words=req.lemmas, translation=req.translation
    )

    results: list[WordCheckResult] = []
    for chk in checks:
        entry = await words.get_by_lemma(chk.word, user_id=user.id)
        if entry is None:
            # 词不在库（已删/lemma 对不上）→ 仍回结果但不推进调度。
            results.append(
                WordCheckResult(
                    verdict=chk.verdict,
                    rating=chk.rating,
                    feedback=chk.feedback,
                    lemma=chk.word,
                    status=VocabStatus.NEW,
                    next_due=None,
                )
            )
            continue
        entry.fsrs_state = scheduler.review(entry.fsrs_state, chk.rating)
        entry.status = _advance_status(entry, chk.rating)
        await words.update(entry)
        results.append(
            WordCheckResult(
                verdict=chk.verdict,
                rating=chk.rating,
                feedback=chk.feedback,
                lemma=chk.word,
                status=entry.status,
                next_due=entry.fsrs_state.due.isoformat() if entry.fsrs_state.due else None,
            )
        )
    return PassageCheckResponse(checks=results)


GRADUATION_STREAK = 3  # 连续答好达此次数才「毕业」为 known


def _advance_status(entry: VocabEntry, rating: ReviewRating) -> VocabStatus:
    """生词状态流转（new → learning → known）。

    入参 entry.fsrs_state 须为**已被 scheduler.review 推进后**的状态（consecutive_good 已更新）。
    - 任意一次复习即脱离 new，进入 learning（开始被调度）。
    - **连续**答好（GOOD/EASY）达 GRADUATION_STREAK 次 → known（不再进 due 队列）。
      用连续计数而非累计复习次数：避免 again,again,good 这类「近期才答对」误毕业。
    - AGAIN/HARD 不降级回 new，但保持 learning（连续计数已清零，FSRS 自会缩短间隔重排）。
    """
    good = rating in (ReviewRating.GOOD, ReviewRating.EASY)
    if good and entry.fsrs_state.consecutive_good >= GRADUATION_STREAK:
        return VocabStatus.KNOWN
    # 答好但未达连续门槛，或答差 → 一律保持 learning（含已毕业又答错被拉回巩固的情形）。
    return VocabStatus.LEARNING
