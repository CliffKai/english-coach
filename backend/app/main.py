"""FastAPI 入口。

L0 脚手架：服务能启动 + 健康检查 + CORS。功能路由（F1/F2/F3）在 L3+ 挂载。
运行：uvicorn app.main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.config import get_config

config = get_config()

app = FastAPI(
    title="English Coach Agent API",
    version=__version__,
    debug=config.debug,
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
