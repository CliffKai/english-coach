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

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.models.enums import LLMAdapterKind, STTAdapterKind, TTSAdapterKind

# backend/ 目录（本文件位于 backend/app/config.py）。
BACKEND_DIR = Path(__file__).resolve().parent.parent


class LLMProviderConnection(BaseModel):
    """单个 LLM provider 的连接信息（密钥来源，来自环境变量，绝不入库）。

    业务里 Settings.model_config 只选 provider 名 + model；真正的 base_url/api_key
    在这里按 provider 名查得。`kind` 决定用哪个适配器：
    - openai_compat → OpenAICompatAdapter（DeepSeek/Qwen/Kimi/vLLM/Ollama/LM Studio…）
    - claude        → ClaudeAdapter（Anthropic 原生协议，评分用）
    本地模型（Ollama 等）只填 base_url，api_key 可空。

    kind 为枚举：拼错或大小写不符（如 "Claude"）在配置加载期即 ValidationError，
    不会被静默当成 OpenAI 兼容而把 Claude 凭证塞进 OpenAI 客户端。
    """

    kind: LLMAdapterKind = LLMAdapterKind.OPENAI_COMPAT
    base_url: str | None = None
    api_key: str | None = None


class STTProviderConnection(BaseModel):
    """单个 STT provider 的连接信息（ADR-012，密钥来自环境变量，绝不入库）。

    kind 决定适配器：
    - openai_compat → OpenAICompatSTTAdapter（/v1/audio/transcriptions；云端 OpenAI/Groq
      或本地服务如 faster-whisper-server。本地无鉴权时 api_key 可空）。
    - faster_whisper → FasterWhisperSTTAdapter（纯本地离线，base_url/api_key 无意义；
      model 即 whisper 模型尺寸如 "base"/"small"，device/compute 走默认）。
    """

    kind: STTAdapterKind = STTAdapterKind.OPENAI_COMPAT
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None


class TTSProviderConnection(BaseModel):
    """单个 TTS provider 的连接信息（ADR-012）。

    kind 决定适配器：
    - openai_compat → OpenAICompatTTSAdapter（/v1/audio/speech）。
    - piper → PiperTTSAdapter（纯本地离线；model 为 piper 语音模型 .onnx 路径）。
    voice 为默认音色（OpenAI 兼容如 "alloy"；可被调用方覆盖）。
    """

    kind: TTSAdapterKind = TTSAdapterKind.OPENAI_COMPAT
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    voice: str | None = None


class AppConfig(BaseSettings):
    """从环境变量读取的进程级配置。前缀 ENGLISH_COACH_。"""

    model_config = SettingsConfigDict(
        env_prefix="ENGLISH_COACH_",
        # Always read backend/.env regardless of the process working directory.
        # Local dev sometimes starts uvicorn from the repository root; a relative
        # ".env" would then miss backend/.env and make configured providers
        # disappear at runtime.
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
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

    # 本地登录 token 签名密钥。自部署建议在 backend/.env 显式设置；
    # 未设置时使用开发默认值，重启后 token 仍可用但不适合公网暴露。
    auth_secret: str = "english-coach-local-dev-secret"
    auth_token_ttl_seconds: int = 60 * 60 * 24 * 14

    # LLM provider 连接表：provider 名 → 连接信息。
    # 嵌套环境变量写法（分隔符 __），如：
    #   ENGLISH_COACH_LLM_PROVIDERS__CLAUDE__KIND=claude
    #   ENGLISH_COACH_LLM_PROVIDERS__CLAUDE__API_KEY=sk-ant-...
    #   ENGLISH_COACH_LLM_PROVIDERS__DEEPSEEK__BASE_URL=https://api.deepseek.com/v1
    #   ENGLISH_COACH_LLM_PROVIDERS__DEEPSEEK__API_KEY=sk-...
    #   ENGLISH_COACH_LLM_PROVIDERS__OLLAMA__BASE_URL=http://localhost:11434/v1
    llm_providers: dict[str, LLMProviderConnection] = Field(default_factory=dict)

    # 语音 provider 连接表（ADR-012），镜像 llm_providers 的嵌套环境变量写法：
    #   ENGLISH_COACH_STT_PROVIDERS__OPENAI__BASE_URL=https://api.openai.com/v1
    #   ENGLISH_COACH_STT_PROVIDERS__OPENAI__API_KEY=sk-...
    #   ENGLISH_COACH_STT_PROVIDERS__OPENAI__MODEL=whisper-1
    #   ENGLISH_COACH_TTS_PROVIDERS__OPENAI__MODEL=tts-1
    stt_providers: dict[str, STTProviderConnection] = Field(default_factory=dict)
    tts_providers: dict[str, TTSProviderConnection] = Field(default_factory=dict)
    # 默认绑进容器的语音 provider 名（缺省取各表里的唯一项 / 第一项；见 build_default_*）。
    default_stt_provider: str | None = None
    default_tts_provider: str | None = None

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
