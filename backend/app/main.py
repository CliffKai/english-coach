"""FastAPI 入口。

L1：启动时把 LocalAdapter(SQLite) 四个 Repo + NonePronunciationAdapter（+ 已配置的
默认 LLM）绑进容器；功能路由（F1/F2/F3）在 L3+ 挂载。
运行：uvicorn app.main:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.adapters import (
    NonePronunciationAdapter,
    SqliteErrorRepository,
    SqliteSessionRepository,
    SqliteSettingsRepository,
    SqliteWordRepository,
)
from app.adapters.llm_factory import build_default_llm
from app.config import get_config
from app.container import Container, set_container
from app.db.connection import Database

config = get_config()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """绑定真实适配器（L1）。SQLite 连接随进程生命周期，关停时收尾。"""
    db = Database(config.sqlite_path)
    set_container(
        Container(
            llm=build_default_llm(config),
            words=SqliteWordRepository(db),
            errors=SqliteErrorRepository(db),
            sessions=SqliteSessionRepository(db),
            settings=SqliteSettingsRepository(db),
            pronunciation=NonePronunciationAdapter(),
            # stt / tts 仍未绑定（L4 接入 faster-whisper / TTS）。
        )
    )
    try:
        yield
    finally:
        db.close()


app = FastAPI(
    title="English Coach Agent API",
    version=__version__,
    debug=config.debug,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict:
    """健康检查（前端脚手架据此确认后端连通）。"""
    return {"status": "ok", "version": __version__}


@app.get("/api/meta")
async def meta() -> dict:
    """暴露关键运行时元信息（不含密钥），便于前端/向导探测。"""
    return {
        "version": __version__,
        "storage_backend": "local",  # L1 起从 Settings 读
        "voice_enabled": False,
        "features": {
            # L0 全部未实现，前端据此显示「即将到来」。随层级推进置 true。
            "vocab_collection": False,  # F1, L3
            "topic_practice": False,  # F2, L3/L4
            "comprehension_review": False,  # F3, L3/L4
        },
    }
