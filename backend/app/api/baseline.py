"""水平基线分级路由（L3 第 1 步）。

GET  /api/baseline/prompt   取首次分级写作题
POST /api/baseline/assess   据写作样本估算 CEFR，写入 Settings.level_baseline
GET  /api/baseline          读当前已存基线

基线先于 F1/F2（07 红线）：F1 切词 cutoff、F2 打分都参照 Settings.level_baseline。
评级用 scoring 档模型；结果标 estimated=True（07 可信度风险），前端须明示「AI 估算」。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.agents.leveling import BaselineResult, LevelingAgent
from app.api import deps
from app.container import Container

router = APIRouter(prefix="/api/baseline", tags=["baseline"])

# 容器依赖（DI）。用 Annotated 而非默认实参里调 Depends（避免 B008，FastAPI 推荐写法）。
ContainerDep = Annotated[Container, Depends(deps.container)]


class AssessRequest(BaseModel):
    sample: str  # 学习者写作样本
    prompt: str | None = None  # 写作题目（可选，便于评估切题度）


class CurrentBaseline(BaseModel):
    baseline: str | None  # 当前 Settings.level_baseline（未分级则 None）


@router.get("/prompt")
def get_prompt() -> dict:
    """首次分级写作题（L5 配置向导复用）。"""
    return {"prompt": LevelingAgent.default_prompt()}


@router.get("")
async def current(c: ContainerDep) -> CurrentBaseline:
    """读当前已存基线。"""
    settings = await deps.load_settings(c)
    return CurrentBaseline(baseline=settings.level_baseline)


@router.post("/assess")
async def assess(req: AssessRequest, c: ContainerDep) -> BaselineResult:
    """估算 CEFR 基线并持久化到 Settings.level_baseline。

    评级是 scoring 任务（要准要稳）。写库经 SettingsRepository UPSERT，单行 per user。
    """
    settings = await deps.load_settings(c)
    llm = deps.require_task_llm(c, "scoring", settings=settings)
    result = await LevelingAgent(llm).assess(req.sample, prompt=req.prompt)

    # 只写回基线，其余配置（含目标分）保持不变——目标分是用户的期望值，不该被当前估算覆盖。
    # 无 settings 存储则仅返回结果不持久化。
    if c.settings is not None:
        settings.level_baseline = result.baseline
        await c.settings.save(settings)
    return result
