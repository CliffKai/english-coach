"""句子精读路由。

POST /api/sentence/analyze  输入一个英文句子 → 翻译 + 语法/词汇/表达讲解。

第一版只做即时分析，不落库；用户若主动加入生词本，前端复用 F1 的 /api/vocab/manual，
只存词和当前句子作为来源句，不存本接口生成的释义/讲解（ADR-004/017）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.agents.sentence_analysis import SentenceAnalysis, SentenceAnalysisAgent
from app.api import deps
from app.container import Container

router = APIRouter(prefix="/api/sentence", tags=["sentence"])

ContainerDep = Annotated[Container, Depends(deps.container)]


class SentenceAnalyzeRequest(BaseModel):
    """句子精读请求。"""

    sentence: str


@router.post("/analyze")
async def analyze_sentence(
    req: SentenceAnalyzeRequest, c: ContainerDep
) -> SentenceAnalysis:
    """翻译并讲解一个英文句子。讲解走 reasoning 档模型（ADR-006/017）。"""
    sentence = req.sentence.strip()
    if not sentence:
        raise HTTPException(status_code=422, detail="sentence 不能为空")
    settings = await deps.load_settings(c)
    llm = deps.require_task_llm(c, "reasoning", settings=settings)
    return await SentenceAnalysisAgent(llm).analyze(
        sentence,
        baseline=settings.level_baseline,
        native_lang=settings.native_lang,
    )
