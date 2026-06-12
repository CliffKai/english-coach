"""进程级配置加载（来自环境变量 / .env）。

区分两类「配置」：
- AppConfig（本文件）：进程级 —— 端口、CORS、数据库路径、各 LLM provider 的连接信息。
  来自环境变量，启动时读一次。密钥只从这里来，绝不入库（见 .gitignore）。
- models.Settings：用户偏好 —— 水平基线、打分标准、per-task 模型分配等，持久化进 DB，
  运行时可改。配置向导（L5）写它。

provider 连接信息以 ENGLISH_COACH_LLM__<NAME>__BASE_URL 形式的嵌套环境变量提供，
此处 L0 用一个简单的前缀解析占位；L1 接入真实适配器时再细化 secret 来源。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ 目录（本文件位于 backend/app/config.py）。
BACKEND_DIR = Path(__file__).resolve().parent.parent


class AppConfig(BaseSettings):
    """从环境变量读取的进程级配置。前缀 ENGLISH_COACH_。"""

    model_config = SettingsConfigDict(
        env_prefix="ENGLISH_COACH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 服务
    host: str = "127.0.0.1"
    port: int = 8000
    debug: bool = False

    # CORS：前端 dev server 源。
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # 存储：LocalAdapter(SQLite) 的数据库文件路径（相对 backend/ 或绝对）。
    database_url: str = "sqlite:///./data/english_coach.db"

    @property
    def sqlite_path(self) -> Path:
        """从 sqlite:///… 解出实际文件路径（供 L1 LocalAdapter 用）。"""
        prefix = "sqlite:///"
        raw = self.database_url
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
        p = Path(raw)
        return p if p.is_absolute() else (BACKEND_DIR / p)


@lru_cache
def get_config() -> AppConfig:
    """单例配置。测试可用 get_config.cache_clear() 重置。"""
    return AppConfig()
