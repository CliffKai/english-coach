"""路由依赖：从容器取适配器/服务，缺失则转成清晰的 HTTP 错误。

容器字段是 `X | None`（L0 默认未绑定）；功能层用到却没绑定时，应回 503 让前端
知道「这功能还没配好」，而非让 None 在深处炸成 500。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException

from app import auth as auth_utils
from app.adapters.repository import (
    ErrorRepository,
    SessionRepository,
    SettingsRepository,
    UserRepository,
    WordRepository,
)
from app.adapters.speech import PronunciationProvider, STTProvider, TTSProvider
from app.agents.base import LLMNotConfiguredError, TaskKind, resolve_task_llm
from app.config import get_config
from app.container import Container, get_container
from app.models import DEFAULT_USER_ID, PublicUser, Settings
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


def require_users(c: Container) -> UserRepository:
    if c.users is None:
        raise HTTPException(status_code=503, detail="账号存储未就绪")
    return c.users


def require_sessions(c: Container) -> SessionRepository:
    if c.sessions is None:
        raise HTTPException(status_code=503, detail="练习会话存储未就绪")
    return c.sessions


def require_errors(c: Container) -> ErrorRepository:
    if c.errors is None:
        raise HTTPException(status_code=503, detail="错题本存储未就绪")
    return c.errors


def require_tokenizer(c: Container) -> Tokenizer:
    if c.tokenizer is None:
        raise HTTPException(status_code=503, detail="切词服务未就绪")
    return c.tokenizer


def require_scheduler(c: Container) -> Scheduler:
    if c.scheduler is None:
        raise HTTPException(status_code=503, detail="调度服务未就绪")
    return c.scheduler


def require_stt(c: Container) -> STTProvider:
    if c.stt is None:
        raise HTTPException(status_code=503, detail="语音转写未配置（请配置 STT provider）")
    return c.stt


def require_tts(c: Container) -> TTSProvider:
    if c.tts is None:
        raise HTTPException(status_code=503, detail="语音合成未配置（请配置 TTS provider）")
    return c.tts


def require_pronunciation(c: Container) -> PronunciationProvider:
    """发音评估。默认 NonePronunciationAdapter 总会绑定（ADR-003/013）；
    None 仅在测试未注入时出现，回 503。"""
    if c.pronunciation is None:
        raise HTTPException(status_code=503, detail="发音评估未就绪")
    return c.pronunciation


async def load_settings(c: Container, *, user_id: str = DEFAULT_USER_ID) -> Settings:
    """读用户配置；无配置（未初始化）→ 返回默认 Settings，不报错。"""
    if c.settings is None:
        return Settings(user_id=user_id)
    existing = await c.settings.get(user_id=user_id)
    return existing or Settings(user_id=user_id)


async def optional_current_user(
    c: Annotated[Container, Depends(container)],
    authorization: Annotated[str | None, Header()] = None,
) -> PublicUser:
    """当前学习数据所属用户。

    无 Authorization 时回落到历史单用户 local-user，便于本地脚本/旧测试继续工作。
    前端登录后会始终带 Bearer token，此时按真实账号隔离数据。
    """
    if not authorization:
        return PublicUser(id=DEFAULT_USER_ID, username=DEFAULT_USER_ID)
    return await _user_from_authorization(c, authorization)


async def current_user(
    c: Annotated[Container, Depends(container)],
    authorization: Annotated[str | None, Header()] = None,
) -> PublicUser:
    """要求已登录；/api/auth/me 等账号接口使用。"""
    if not authorization:
        raise HTTPException(status_code=401, detail="请先登录")
    return await _user_from_authorization(c, authorization)


async def _user_from_authorization(c: Container, authorization: str) -> PublicUser:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="无效的登录凭证")
    try:
        payload = auth_utils.decode_access_token(token, secret=get_config().auth_secret)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录") from exc
    users = require_users(c)
    user = await users.get(payload["sub"])
    if user is None:
        raise HTTPException(status_code=401, detail="账号不存在，请重新登录")
    return PublicUser(id=user.id, username=user.username)


async def user_from_token(c: Container, token: str | None) -> PublicUser:
    """WebSocket 使用：从 query token 解析用户；缺省时沿用 local-user 回退。"""
    if not token:
        return PublicUser(id=DEFAULT_USER_ID, username=DEFAULT_USER_ID)
    return await _user_from_authorization(c, f"Bearer {token}")


def require_task_llm(c: Container, task: TaskKind, *, settings: Settings):
    """为某任务解析 LLM（ADR-006）。未配置模型 → 409，提示去配置向导配模型。"""
    try:
        return resolve_task_llm(
            task, settings=settings, config=get_config(), default_llm=c.llm
        )
    except LLMNotConfiguredError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def resolve_llm_or_raise(c: Container, task: TaskKind, *, settings: Settings):
    """同 require_task_llm 但抛 LLMNotConfiguredError 而非 HTTPException。

    WebSocket 路径用：WS 无 HTTP 状态码，由调用方捕获后以错误帧告知客户端。
    """
    return resolve_task_llm(
        task, settings=settings, config=get_config(), default_llm=c.llm
    )
