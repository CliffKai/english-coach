"""F1 生词收集路由（L3 第 2 步，吃基线产物，产 VocabEntry 喂 F3）。

POST /api/vocab/extract   文本 → 候选生词（切词+过滤，按 Settings.level_baseline）
POST /api/vocab/collect   把「不认识」的词连同来源句入库（按 lemma 查重合并）
GET  /api/vocab           列出生词本
GET  /api/vocab/due       FSRS 到期复习队列（F3a 消费）

切词/过滤是确定性的（L2 spaCy+wordfreq），不调 LLM（ADR-008）。逐词「认识/跳过/
不认识」的问询是前端交互，后端只在 collect 收「不认识」的结果。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

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
