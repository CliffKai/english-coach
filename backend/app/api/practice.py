"""话题练习路由 —— 考试模式（延迟纠错 + 打分）：F2c 自由写作 + F2d 对话打分。

POST /api/practice/topic          练习开始前生成一个可选话题（不落库，可编辑/可留空）
POST /api/practice/dialogue/turn  F2d 对话单轮：用户话语 + 历史 → 自然回话（不纠错/不打分）
POST /api/practice/score          提交 → 打分 + 错误检测 → 复盘 + 回填错题本 → 落库会话
GET  /api/practice                列出历史练习会话
GET  /api/errors                  错题本（错误清单；首页/复盘用，resolved 过滤）

延迟纠错机制（docs/02，ADR-005）：考试模式不当场纠错；点「完成/提前交卷」后一次性
出分 + 错误清单 + 复盘。
- F2c（free_write）单轮提交，「整篇即 buffer」。
- F2d（dialogue）多轮对话：每轮 converse() 只自然回话（零脚手架，绝不纠错/提示），
  前端持有整段对话（无服务端会话态，沿用本项目无状态风格）；用户「提交」时把累积的
  **用户话语**作为 text 走 score()，复用同一条结算链（ExaminerAgent→ErrorAnalysisAgent）。
ExaminerAgent 标注错误进 ExamResult.errors（隐藏 buffer），紧跟交 ErrorAnalysisAgent 转
ErrorEntry 落库（07 红线：buffer 临时，产出即消费）。

口语发音/流利度（ADR-013）：本 HTTP 文本路径无音频证据，发音评估为 None →
ExaminerAgent 让发音/流利度维度**空缺并标注**，不假评（真音频评估走 L4 WS 路径）。

模型分配（ADR-006）：打分走 scoring 档（要准要稳），复盘/引导走 reasoning 档，
话题生成/对话单轮回话走 conversation 档（量大、性价比）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.adapters.llm import ChatMessage, Role
from app.agents.error_analysis import AnalysisReport, ErrorAnalysisAgent
from app.agents.examiner import DimensionScore, ExaminerAgent
from app.agents.topic_suggestion import TopicSuggestionAgent
from app.agents.tutor import Correction, TutorAgent
from app.api import deps
from app.container import Container
from app.models import ErrorEntry, PracticeMode, PracticeSession, PublicUser, ScoringStandard

router = APIRouter(tags=["practice"])

ContainerDep = Annotated[Container, Depends(deps.container)]
UserDep = Annotated[PublicUser, Depends(deps.optional_current_user)]

# 本接口受理的考试模式（延迟纠错）。练习模式 guided_* 即时纠错，归 TutorAgent（/tutor）。
_EXAM_MODES = (PracticeMode.FREE_WRITE, PracticeMode.DIALOGUE)
# 练习模式（即时纠错 + 脚手架，TutorAgent）。
_PRACTICE_MODES = (PracticeMode.GUIDED_WRITE, PracticeMode.GUIDED_SPEAK)


class ScoreRequest(BaseModel):
    """提交一次考试模式打分（自由写作整篇 / 对话累积的用户话语）。"""

    text: str
    topic: str | None = None
    # 考试模式：free_write（2c）/ dialogue（2d）。默认自由写作。
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


class TopicSuggestionRequest(BaseModel):
    """练习开始前生成一个可选话题。"""

    mode: PracticeMode = PracticeMode.FREE_WRITE


class TopicSuggestionResponse(BaseModel):
    """前端填入 topic 输入框的建议话题；用户仍可编辑/删除/留空。"""

    topic: str


@router.post("/api/practice/topic")
async def suggest_topic(
    req: TopicSuggestionRequest, c: ContainerDep
) -> TopicSuggestionResponse:
    """可选随机话题生成。只发生在练习开始前，不改变考试模式零脚手架规则。"""
    settings = await deps.load_settings(c)
    llm = deps.require_task_llm(c, "conversation", settings=settings)
    result = await TopicSuggestionAgent(llm).suggest(
        mode=req.mode, baseline=settings.level_baseline
    )
    return TopicSuggestionResponse(topic=result.topic)


class DialogueTurn(BaseModel):
    """对话历史的一轮（前端持有整段对话，逐轮回传）。"""

    role: Role  # user | assistant
    content: str


class DialogueTurnRequest(BaseModel):
    """F2d 对话单轮：用户本轮话语 + 既往历史。"""

    message: str
    history: list[DialogueTurn] = []
    topic: str | None = None


class DialogueTurnResponse(BaseModel):
    """考官的自然回话（驱动前端 TTS 播放）。零纠错/零打分（ADR-005）。"""

    reply: str


@router.post("/api/practice/dialogue/turn")
async def dialogue_turn(req: DialogueTurnRequest, c: ContainerDep) -> DialogueTurnResponse:
    """F2d 对话单轮：自然推进对话，绝不纠错/提示/打分（考试模式零脚手架，ADR-005）。

    无服务端会话态：前端持有整段对话历史逐轮回传（沿用本项目无状态风格）。错误检测与
    打分一律延迟到 /score（对累积用户话语整体进行）。回话走 conversation 档（量大省钱）。
    """
    settings = await deps.load_settings(c)
    llm = deps.require_task_llm(c, "conversation", settings=settings)
    history = [ChatMessage(role=t.role, content=t.content) for t in req.history]
    result = await ExaminerAgent(llm).converse(
        req.message, history=history, topic=req.topic, baseline=settings.level_baseline
    )
    return DialogueTurnResponse(reply=result.reply)


class TutorRequest(BaseModel):
    """F2a/2b 引导练习单轮：用户本轮输出 + 历史（前端持有，逐轮回传）。"""

    text: str
    # 练习模式：guided_write（2a）/ guided_speak（2b）。默认引导写作。
    mode: PracticeMode = PracticeMode.GUIDED_WRITE
    topic: str | None = None
    history: list[DialogueTurn] = []


class TutorResponse(BaseModel):
    """即时纠错 + 鼓励 + 脚手架 + 引导回话（练习模式，当场返回，不打分/不落错题本）。"""

    corrections: list[Correction]
    encouragement: str
    scaffold: str
    follow_up: str


@router.post("/api/practice/tutor")
async def tutor(req: TutorRequest, c: ContainerDep) -> TutorResponse:
    """F2a/2b 练习模式：即时纠错 + 脚手架引导（与考试模式相反，ADR-005）。

    不打分、不落错题本（错题本是考试模式 F2c/F2d 的产物）；当场把纠错与引导返回。
    无状态：前端持有整段历史逐轮回传。引导走 reasoning 档（ADR-006）。
    """
    if req.mode not in _PRACTICE_MODES:
        raise HTTPException(
            status_code=400,
            detail="该接口仅支持练习模式（guided_write / guided_speak）；考试打分走 /score",
        )
    settings = await deps.load_settings(c)
    llm = deps.require_task_llm(c, "reasoning", settings=settings)
    history = [ChatMessage(role=t.role, content=t.content) for t in req.history]
    result = await TutorAgent(llm).tutor(
        req.text,
        mode=req.mode,
        topic=req.topic,
        baseline=settings.level_baseline,
        history=history,
    )
    return TutorResponse(
        corrections=result.corrections,
        encouragement=result.encouragement,
        scaffold=result.scaffold,
        follow_up=result.follow_up,
    )


@router.post("/api/practice/score")
async def score(req: ScoreRequest, c: ContainerDep, user: UserDep) -> ScoreResponse:
    """考试模式结算：打分 → 错误检测 → 复盘 → 回填错题本 → 落库会话。

    顺序即 07 的 F2c → ErrorAnalysis 红线：ExaminerAgent 的隐藏 buffer 当场交给
    ErrorAnalysisAgent，转 ErrorEntry 落库 + 产复盘，buffer 不持久化。
    """
    if req.mode not in _EXAM_MODES:
        # 练习模式（guided_*）是即时纠错，归 TutorAgent（/api/practice/tutor），不走本结算链路。
        raise HTTPException(
            status_code=400,
            detail="该接口仅支持考试模式（free_write / dialogue）；引导练习走 /tutor",
        )
    # 口语（dialogue）发音/流利度：本 HTTP 文本路径无音频，pronunciation=None →
    # ExaminerAgent 让这些维度空缺并标注（不假评，ADR-013）。真音频评估走 L4 WS 路径。
    return await settle_exam(
        c,
        user_id=user.id,
        text=req.text,
        mode=req.mode,
        topic=req.topic,
        ended_early=req.ended_early,
        pronunciation=None,
    )


async def settle_exam(
    c: Container,
    *,
    user_id: str,
    text: str,
    mode: PracticeMode,
    topic: str | None,
    ended_early: bool,
    pronunciation=None,
) -> ScoreResponse:
    """考试模式结算链（F2c/F2d 共用）：打分 → 错误检测 → 复盘 → 回填错题本 → 落库会话。

    HTTP /score（文本，pronunciation=None）与 WS 语音对话（带音频发音评估）都调本函数，
    避免「打分 + 隐藏 buffer → ErrorAnalysis」这条 07 红线链路两处实现走样。
    """
    sessions = deps.require_sessions(c)
    errors_repo = deps.require_errors(c)
    settings = await deps.load_settings(c)

    # 先把两档模型都解析出来（ADR-006：打分 scoring、复盘 reasoning）——任一未配置即 409，
    # 在任何持久化之前失败，避免「打分成功但复盘模型未配」时留下半截会话/错题（部分写入）。
    scoring_llm = deps.require_task_llm(c, "scoring", settings=settings)
    analysis_agent = ErrorAnalysisAgent(deps.require_task_llm(c, "reasoning", settings=settings))

    exam = await ExaminerAgent(scoring_llm).score(
        text,
        mode=mode,
        topic=topic,
        standard=settings.scoring_standard,
        target_band=settings.target_band,
        baseline=settings.level_baseline,
        pronunciation=pronunciation,
    )

    # 在此构造会话对象（id 此刻即生成，default_factory），但**先不落库**——错题要挂这个 id。
    session = PracticeSession(
        user_id=user_id,
        mode=mode,
        topic=topic,
        transcript=text,
        scores=_scores_json(exam.standard, exam.dimensions, exam.overall),
        ended_early=ended_early,
    )
    entries = analysis_agent.to_entries(
        exam.errors, session_id=session.id, topic=topic, user_id=user_id
    )

    # 复盘要在写入本次错误**之前**取历史，否则本次错误会被当成「既往反复出现的模式」
    # （首犯被误判为复发）。history 仅含此前未解决错题。
    history = await errors_repo.list(user_id=user_id, resolved=False)
    report = await analysis_agent.analyze(exam.errors, history=history, topic=topic)

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
async def list_sessions(c: ContainerDep, user: UserDep) -> list[PracticeSession]:
    """历史练习会话（最近在前；首页/进度用）。"""
    sessions = deps.require_sessions(c)
    return await sessions.list(user_id=user.id)


@router.get("/api/errors")
async def list_errors(
    c: ContainerDep,
    user: UserDep,
    resolved: bool | None = Query(default=None),
) -> list[ErrorEntry]:
    """错题本。resolved=None 全部；False 仅待巩固（首页错题区用）。"""
    errors_repo = deps.require_errors(c)
    return await errors_repo.list(user_id=user.id, resolved=resolved)


def _scores_json(
    standard: ScoringStandard, dimensions: list[DimensionScore], overall: float | None
) -> dict:
    """PracticeSession.scores 的存储形态（各维度 + 综合分 + 标准）。"""
    return {
        "standard": standard.value,
        "overall": overall,
        "dimensions": [d.model_dump() for d in dimensions],
    }
