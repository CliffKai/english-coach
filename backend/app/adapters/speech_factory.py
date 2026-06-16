"""按配置构建 STTProvider / TTSProvider 适配器（L4，ADR-012）。

镜像 llm_factory：Settings/调用方按 provider 名选连接，连接信息（kind/base_url/api_key/
model）在 AppConfig.stt_providers / tts_providers 里按名查得。默认走 OpenAI 兼容协议，
faster-whisper / piper 作纯本地可选。

启动时挑一个默认 provider 绑进容器（default_stt_provider / default_tts_provider，
缺省取表里唯一项 / 第一项），用到时再由功能层按需解析。
"""

from __future__ import annotations

from app.adapters.speech import STTProvider, TTSProvider
from app.adapters.stt_faster_whisper import FasterWhisperSTTAdapter
from app.adapters.stt_openai_compat import OpenAICompatSTTAdapter
from app.adapters.tts_openai_compat import OpenAICompatTTSAdapter
from app.adapters.tts_piper import PiperTTSAdapter
from app.config import AppConfig, STTProviderConnection, TTSProviderConnection
from app.models.enums import STTAdapterKind, TTSAdapterKind


def build_stt_adapter(conn: STTProviderConnection) -> STTProvider:
    """据连接 kind 造 STT 适配器。kind 已由 config 模型约束为合法枚举值。"""
    if conn.kind == STTAdapterKind.FASTER_WHISPER:
        # 本地：model 即 whisper 尺寸（base/small/...），缺省 base。
        return FasterWhisperSTTAdapter(model=conn.model or "base")
    if conn.kind == STTAdapterKind.OPENAI_COMPAT:
        return OpenAICompatSTTAdapter(
            model=conn.model or "whisper-1", base_url=conn.base_url, api_key=conn.api_key
        )
    raise ValueError(f"未支持的 STT 适配器 kind: {conn.kind}")


def build_tts_adapter(conn: TTSProviderConnection) -> TTSProvider:
    """据连接 kind 造 TTS 适配器。"""
    if conn.kind == TTSAdapterKind.PIPER:
        if not conn.model:
            raise ValueError("piper TTS 需配置 model（语音模型 .onnx 路径）")
        return PiperTTSAdapter(model=conn.model)
    if conn.kind == TTSAdapterKind.OPENAI_COMPAT:
        return OpenAICompatTTSAdapter(
            model=conn.model or "tts-1",
            base_url=conn.base_url,
            api_key=conn.api_key,
            voice=conn.voice,
        )
    raise ValueError(f"未支持的 TTS 适配器 kind: {conn.kind}")


def _pick(table: dict, preferred: str | None) -> str | None:
    """挑默认 provider 名：显式指定优先，否则表里唯一项 / 第一项；空表 None。"""
    if preferred and preferred in table:
        return preferred
    if len(table) >= 1:
        return next(iter(table))
    return None


def build_default_stt(config: AppConfig) -> STTProvider | None:
    """挑一个默认 STT 绑进容器（L4 启动）。未配置任何 STT provider → None。"""
    name = _pick(config.stt_providers, config.default_stt_provider)
    return build_stt_adapter(config.stt_providers[name]) if name else None


def build_default_tts(config: AppConfig) -> TTSProvider | None:
    """挑一个默认 TTS 绑进容器（L4 启动）。未配置任何 TTS provider → None。"""
    name = _pick(config.tts_providers, config.default_tts_provider)
    return build_tts_adapter(config.tts_providers[name]) if name else None
