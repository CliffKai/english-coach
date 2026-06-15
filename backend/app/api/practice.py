"""话题练习路由 —— L3 落地 F2c 自由写作打分（考试模式，延迟纠错 + 多维度打分）。

POST /api/practice/score   提交自由写作 → 打分 + 错误检测 → 复盘 + 回填错题本 → 落库会话
GET  /api/practice         列出历史练习会话
GET  /api/errors           错题本（错误清单；首页/复盘用，resolved 过滤）

延迟纠错机制（docs/02，ADR-005）：考试模式不当场纠错；点「完成/提前交卷」后一次性
出分 + 错误清单 + 复盘。F2c（free_write）是单轮提交，故「整篇即 buffer」——ExaminerAgent
标注错误进 ExamResult.errors（隐藏 buffer），紧跟交 ErrorAnalysisAgent 转 ErrorEntry 落库
（07 红线：buffer 临时，产出即消费）。2d 对话（多轮累积 buffer）复用此链路，L4 接。

模型分配（ADR-006）：打分走 scoring 档（要准要稳），复盘走 reasoning 档。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.agents.error_analysis import AnalysisReport, ErrorAnalysisAgent
from app.agents.examiner import DimensionScore, ExaminerAgent
from app.api import deps
from app.container import Container
from app.models import ErrorEntry, PracticeMode, PracticeSession, ScoringStandard

router = APIRouter(tags=["practice"])

ContainerDep = Annotated[Container, Depends(deps.container)]


class ScoreRequest(BaseModel):
    """提交一次自由写作打分。"""

    text: str
    topic: str | None = None
    # 仅考试模式（free_write / dialogue）；L3 落地 free_write，默认即它。
    mode: PracticeMode = PracticeMode.FREE_WRITE
    # 提前交卷（ADR-005）：按已有内容打分，不是救场；落进会话 ended_early。
    ended_early: bool = False


class ScoreResponse(BaseModel):
    """打分 + 错误清单 + 复盘。一次性返回（延迟纠错的「结算」时刻）。"""

    session_id: str
    standard: ScoringStandard
    dimensions: list[DimensionScore]
    overall: float | None
    estimated: bool  # 恒 True：AI 估算，UI 须明示（07 可信度风险）
    errors: list[ErrorEntry]  # 已落库的错题（含 id，供前端跳错题本）
    report: AnalysisReport  # 复盘（模式识别 + 中文总结）


@router.post("/api/practice/score")
async def score(req: ScoreRequest, c: ContainerDep) -> ScoreResponse:
    """考试模式结算：打分 → 错误检测 → 复盘 → 回填错题本 → 落库会话。

    顺序即 07 的 F2c → ErrorAnalysis 红线：ExaminerAgent 的隐藏 buffer 当场交给
    ErrorAnalysisAgent，转 ErrorEntry 落库 + 产复盘，buffer 不持久化。
    """
    if req.mode is not PracticeMode.FREE_WRITE:
        # L3 仅落地自由写作（2c）。对话打分（2d）强依赖 STT/TTS，属 L4（07 红线）：
        # 此处用写作 rubric 给口语打分、且可能落库 pronunciation 错误（无语音证据），故拒绝。
        # 练习模式（guided_*）是即时纠错，归 TutorAgent（L4），同样不走本结算链路。
        raise HTTPException(
            status_code=400, detail="该接口当前仅支持自由写作打分（free_write）；对话打分 2d 待 L4"
        )

    sessions = deps.require_sessions(c)
    errors_repo = deps.require_errors(c)
    settings = await deps.load_settings(c)

    # 先把两档模型都解析出来（ADR-006：打分 scoring、复盘 reasoning）——任一未配置即 409，
    # 在任何持久化之前失败，避免「打分成功但复盘模型未配」时留下半截会话/错题（部分写入）。
    scoring_llm = deps.require_task_llm(c, "scoring", settings=settings)
    analysis_agent = ErrorAnalysisAgent(deps.require_task_llm(c, "reasoning", settings=settings))

    exam = await ExaminerAgent(scoring_llm).score(
        req.text,
        mode=req.mode,
        topic=req.topic,
        standard=settings.scoring_standard,
        target_band=settings.target_band,
        baseline=settings.level_baseline,
    )

    # 在此构造会话对象（id 此刻即生成，default_factory），但**先不落库**——错题要挂这个 id。
    session = PracticeSession(
        user_id=settings.user_id,
        mode=req.mode,
        topic=req.topic,
        transcript=req.text,
        scores=_scores_json(exam.standard, exam.dimensions, exam.overall),
        ended_early=req.ended_early,
    )
    entries = analysis_agent.to_entries(
        exam.errors, session_id=session.id, topic=req.topic, user_id=settings.user_id
    )

    # 复盘要在写入本次错误**之前**取历史，否则本次错误会被当成「既往反复出现的模式」
    # （首犯被误判为复发）。history 仅含此前未解决错题。
    history = await errors_repo.list(user_id=settings.user_id, resolved=False)
    report = await analysis_agent.analyze(exam.errors, history=history, topic=req.topic)

    # 所有可能失败的 LLM/解析工作已完成，到此才落库，把部分写入窗口压到最小。
    # 顺序：先会话后错题——error_entries.session_id 有外键引用 practice_sessions，
    # 反过来插错题会违反 FK（schema.sql，PRAGMA foreign_keys=ON）。
    session.error_ids = [e.id for e in entries]
    session.summary = report.summary
    await sessions.add(session)
    if entries:
        await errors_repo.add_many(entries)

    return ScoreResponse(
        session_id=session.id,
        standard=exam.standard,
        dimensions=exam.dimensions,
        overall=exam.overall,
        estimated=exam.estimated,
        errors=entries,
        report=report,
    )


@router.get("/api/practice")
async def list_sessions(c: ContainerDep) -> list[PracticeSession]:
    """历史练习会话（最近在前；首页/进度用）。"""
    sessions = deps.require_sessions(c)
    return await sessions.list()


@router.get("/api/errors")
async def list_errors(
    c: ContainerDep,
    resolved: bool | None = Query(default=None),
) -> list[ErrorEntry]:
    """错题本。resolved=None 全部；False 仅待巩固（首页错题区用）。"""
    errors_repo = deps.require_errors(c)
    return await errors_repo.list(resolved=resolved)


def _scores_json(
    standard: ScoringStandard, dimensions: list[DimensionScore], overall: float | None
) -> dict:
    """PracticeSession.scores 的存储形态（各维度 + 综合分 + 标准）。"""
    return {
        "standard": standard.value,
        "overall": overall,
        "dimensions": [d.model_dump() for d in dimensions],
    }
