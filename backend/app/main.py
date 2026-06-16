"""FastAPI 入口。

L1：启动时把 LocalAdapter(SQLite) 四个 Repo + NonePronunciationAdapter（+ 已配置的
默认 LLM）绑进容器。
L3：挂载核心闭环路由 —— baseline（水平基线）/ vocab（F1 生词）/ review（F3a 背词）/
practice（F2c 自由写作打分 + 错题本）。
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
from app.adapters.speech_factory import build_default_stt, build_default_tts
from app.api import (
    baseline_router,
    practice_router,
    review_router,
    vocab_router,
    voice_router,
)
from app.config import get_config
from app.container import Container, set_container
from app.db.connection import Database
from app.nlp import SpacyTokenizer
from app.scheduling import FsrsScheduler

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
            # L2 服务：spaCy 切词（模型懒加载，首次 tokenize 才载入）+ FSRS 调度。
            tokenizer=SpacyTokenizer(),
            scheduler=FsrsScheduler(),
            # L4 语音（ADR-012）：默认走 OpenAI 兼容协议，按配置挑默认 provider；
            # 未配置语音 provider 则为 None（用到时回 503，提示去配语音）。
            stt=build_default_stt(config),
            tts=build_default_tts(config),
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

# L3 核心闭环路由：baseline → vocab(F1) → review(F3a/F3b) → practice(F2c/F2d/F2a/2b + 错题本)。
# L4 语音：voice（F2d 语音对话 WebSocket）。
app.include_router(baseline_router)
app.include_router(vocab_router)
app.include_router(review_router)
app.include_router(practice_router)
app.include_router(voice_router)


@app.get("/api/health")
async def health() -> dict:
    """健康检查（前端脚手架据此确认后端连通）。"""
    return {"status": "ok", "version": __version__}


@app.get("/api/meta")
async def meta() -> dict:
    """暴露关键运行时元信息（不含密钥），便于前端/向导探测。"""
    from app.container import get_container

    c = get_container()
    # 语音可用 = STT 与 TTS 都已绑定（ADR-012：默认走 API，未配则 None）。
    voice_enabled = c.stt is not None and c.tts is not None
    return {
        "version": __version__,
        "storage_backend": "local",  # L1 起从 Settings 读
        "voice_enabled": voice_enabled,
        # 语音子能力细分（前端按需禁用录音/播放）。
        "voice": {"stt": c.stt is not None, "tts": c.tts is not None},
        "features": {
            # 随层级推进置 true。
            "vocab_collection": True,  # F1，L3 已接（切词+逐词问询+入库）
            "topic_practice": True,  # F2，L3 接 2c；L4 接 2a/2b（引导）+ 2d（对话打分）
            "comprehension_review": True,  # F3，L3 接 3a；L4 接 3b（语境造句背）
        },
    }
