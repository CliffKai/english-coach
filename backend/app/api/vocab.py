"""F1 生词收集路由（L3 第 2 步，吃基线产物，产 VocabEntry 喂 F3）。

POST /api/vocab/extract   文本 → 候选生词（切词+过滤，按 Settings.level_baseline）
POST /api/vocab/collect   把「不认识」的词连同来源句入库（按 lemma 查重合并）
GET  /api/vocab           列出生词本
GET  /api/vocab/due       FSRS 到期复习队列（F3a 消费）
DELETE /api/vocab/{id}    从生词本永久删除一个词条

切词/过滤是确定性的（L2 spaCy+wordfreq），不调 LLM（ADR-008）。逐词「认识/跳过/
不认识」的问询是前端交互，后端只在 collect 收「不认识」的结果。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel

from app.agents.base import LLMNotConfiguredError
from app.agents.tokenizer_agent import CollectItem, TokenizerAgent
from app.api import deps
from app.container import Container
from app.models import VocabEntry
from app.nlp.tokenizer import VocabCandidate

router = APIRouter(prefix="/api/vocab", tags=["vocab"])

ContainerDep = Annotated[Container, Depends(deps.container)]


class ExtractRequest(BaseModel):
    text: str
    # 可覆盖基线（默认用 Settings.level_baseline）；min_zipf 滤语料外噪音。
    baseline: str | None = None
    min_zipf: float = 1.0


class ExtractResponse(BaseModel):
    baseline: str | None  # 实际生效的基线（来自请求或 Settings）
    candidates: list[VocabCandidate]


class CollectRequest(BaseModel):
    items: list[CollectItem]  # 仅「不认识」的词（认识/跳过不传）


@router.post("/extract")
async def extract(req: ExtractRequest, c: ContainerDep) -> ExtractResponse:
    """文本 → 候选生词。baseline 缺省取 Settings.level_baseline（07 红线）。"""
    tokenizer = deps.require_tokenizer(c)
    words = deps.require_words(c)
    settings = await deps.load_settings(c)
    baseline = req.baseline or settings.level_baseline
    agent = TokenizerAgent(tokenizer, words)
    candidates = agent.extract(req.text, baseline=baseline, min_zipf=req.min_zipf)
    return ExtractResponse(baseline=baseline, candidates=candidates)


@router.post("/collect")
async def collect(req: CollectRequest, c: ContainerDep) -> list[VocabEntry]:
    """把「不认识」的词入库（连同来源句，按 lemma 查重合并，ADR-004/010）。"""
    words = deps.require_words(c)
    tokenizer = deps.require_tokenizer(c)
    agent = TokenizerAgent(tokenizer, words)
    return await agent.collect(req.items)


class ManualRequest(BaseModel):
    """用户补录一个生词（ADR-015）。

    word     必填，要补的词。
    text     可选，「从本文补词」：后端从该文本定位 word 取来源句（零 LLM）。
    sentence 可选，用户自填例句（最高优先级，零 LLM）。
    都没给且词不在 text 中 → LLM（conversation 档）造一个例句作来源句。
    """

    word: str
    text: str | None = None
    sentence: str | None = None


@router.post("/manual")
async def manual(req: ManualRequest, c: ContainerDep) -> VocabEntry:
    """用户主动补录生词（ADR-015）：取/造来源句 → 复用 collect 入库（按 lemma 合并）。

    来源句优先级：自填 sentence > text 中定位 > LLM 造句 > 无来源句兜底。
    仅「需造句且无自填/无文本命中」时才调 LLM；未配模型则降级为无来源句，不报 409。
    """
    if not req.word.strip():
        raise HTTPException(status_code=422, detail="word 不能为空")
    words = deps.require_words(c)
    tokenizer = deps.require_tokenizer(c)
    agent = TokenizerAgent(tokenizer, words)

    # 仅在确实需要造句的路径才解析 LLM（有自填例句/文中能定位则不需要）。
    llm = None
    needs_generation = not (req.sentence and req.sentence.strip())
    if needs_generation and req.text and req.text.strip():
        needs_generation = tokenizer.locate_in_text(req.word, req.text) is None
    if needs_generation:
        settings = await deps.load_settings(c)
        try:
            llm = deps.resolve_llm_or_raise(c, "conversation", settings=settings)
        except LLMNotConfiguredError:
            llm = None  # 降级：无模型则入库无来源句的纯词，不阻断补录

    candidate = await agent.manual_candidate(
        req.word, text=req.text, sentence=req.sentence, llm=llm
    )
    item = CollectItem(
        word=candidate.word,
        lemma=candidate.lemma,
        context_sentences=candidate.context_sentences,
    )
    entries = await agent.collect([item])
    return entries[0]


@router.get("")
async def list_vocab(c: ContainerDep) -> list[VocabEntry]:
    """生词本全量。"""
    words = deps.require_words(c)
    return await words.list()


@router.get("/due")
async def due(
    c: ContainerDep,
    limit: int | None = Query(default=None, ge=1),
) -> list[VocabEntry]:
    """FSRS 到期复习队列（F3a 消费）。排序/过滤在 WordRepository.list_due（L1/L2）。"""
    words = deps.require_words(c)
    return await words.list_due(limit=limit)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vocab(entry_id: str, c: ContainerDep) -> Response:
    """从生词本永久删除一个词条。"""
    words = deps.require_words(c)
    entry = await words.get(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="生词不存在")
    await words.delete(entry_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
