"""路由依赖：从容器取适配器/服务，缺失则转成清晰的 HTTP 错误。

容器字段是 `X | None`（L0 默认未绑定）；功能层用到却没绑定时，应回 503 让前端
知道「这功能还没配好」，而非让 None 在深处炸成 500。
"""

from __future__ import annotations

from fastapi import HTTPException

from app.adapters.repository import SettingsRepository, WordRepository
from app.agents.base import LLMNotConfiguredError, TaskKind, resolve_task_llm
from app.config import get_config
from app.container import Container, get_container
from app.models import DEFAULT_USER_ID, Settings
from app.nlp.tokenizer import Tokenizer
from app.scheduling import Scheduler


def container() -> Container:
    """FastAPI 依赖：当前进程容器。测试可 set_container 整体替换。"""
    return get_container()


def require_words(c: Container) -> WordRepository:
    if c.words is None:
        raise HTTPException(status_code=503, detail="生词存储未就绪")
    return c.words


def require_settings_repo(c: Container) -> SettingsRepository:
    if c.settings is None:
        raise HTTPException(status_code=503, detail="配置存储未就绪")
    return c.settings


def require_tokenizer(c: Container) -> Tokenizer:
    if c.tokenizer is None:
        raise HTTPException(status_code=503, detail="切词服务未就绪")
    return c.tokenizer


def require_scheduler(c: Container) -> Scheduler:
    if c.scheduler is None:
        raise HTTPException(status_code=503, detail="调度服务未就绪")
    return c.scheduler


async def load_settings(c: Container, *, user_id: str = DEFAULT_USER_ID) -> Settings:
    """读用户配置；无配置（未初始化）→ 返回默认 Settings，不报错。"""
    if c.settings is None:
        return Settings(user_id=user_id)
    existing = await c.settings.get(user_id=user_id)
    return existing or Settings(user_id=user_id)


def require_task_llm(c: Container, task: TaskKind, *, settings: Settings):
    """为某任务解析 LLM（ADR-006）。未配置模型 → 409，提示去配置向导配模型。"""
    try:
        return resolve_task_llm(
            task, settings=settings, config=get_config(), default_llm=c.llm
        )
    except LLMNotConfiguredError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
