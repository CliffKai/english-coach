"""L4 验证（docs/07，ADR-012）：STT/TTS 适配器构造 + 工厂按 kind 选择 + 转写规整。

全程离线：不发真实网络/不加载本地模型，只验证「装配正确」——工厂按 kind 选对适配器、
OpenAI 兼容 STT 的响应规整（含时间戳）、默认 provider 挑选规则。真实转写/合成属手动集成测试。
faster-whisper / piper 适配器只验证构造与懒加载边界（不触发 import），不跑模型。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.adapters.speech_factory import (
    build_default_stt,
    build_default_tts,
    build_stt_adapter,
    build_tts_adapter,
)
from app.adapters.stt_faster_whisper import FasterWhisperSTTAdapter
from app.adapters.stt_openai_compat import OpenAICompatSTTAdapter, _to_transcript
from app.adapters.tts_openai_compat import OpenAICompatTTSAdapter
from app.adapters.tts_piper import PiperTTSAdapter
from app.config import AppConfig, STTProviderConnection, TTSProviderConnection
from app.models.enums import STTAdapterKind, TTSAdapterKind


# ── 工厂：按 kind 选适配器 ──────────────────────────────────────────
def test_build_stt_adapter_routes_by_kind():
    compat = build_stt_adapter(
        STTProviderConnection(
            kind="openai_compat", base_url="http://x/v1", api_key="k", model="whisper-1"
        )
    )
    local = build_stt_adapter(STTProviderConnection(kind="faster_whisper", model="base"))
    assert isinstance(compat, OpenAICompatSTTAdapter)
    assert isinstance(local, FasterWhisperSTTAdapter)


def test_build_tts_adapter_routes_by_kind():
    compat = build_tts_adapter(
        TTSProviderConnection(kind="openai_compat", model="tts-1", voice="alloy")
    )
    piper = build_tts_adapter(TTSProviderConnection(kind="piper", model="/tmp/v.onnx"))
    assert isinstance(compat, OpenAICompatTTSAdapter)
    assert isinstance(piper, PiperTTSAdapter)


def test_piper_requires_model():
    # piper 是离线适配器，无 model（.onnx 路径）无从合成 → 构建期即报错。
    with pytest.raises(ValueError):
        build_tts_adapter(TTSProviderConnection(kind="piper", model=None))


def test_unknown_kind_rejected_at_config_load():
    # 拼错/大小写不符的 kind 在配置模型校验期即报错（同 LLM，不静默落到某适配器）。
    for bad in ("Whisper", "openai", "fasterwhisper"):
        with pytest.raises(ValidationError):
            STTProviderConnection(kind=bad)
    for bad in ("Piper", "openai_tts"):
        with pytest.raises(ValidationError):
            TTSProviderConnection(kind=bad)
    assert STTProviderConnection().kind == STTAdapterKind.OPENAI_COMPAT  # 默认
    assert TTSProviderConnection().kind == TTSAdapterKind.OPENAI_COMPAT


# ── 默认 provider 挑选 ──────────────────────────────────────────────
def test_build_default_stt_tts_empty_is_none():
    cfg = AppConfig()
    assert build_default_stt(cfg) is None
    assert build_default_tts(cfg) is None


def test_build_default_picks_single_then_named():
    # 单一 provider → 直接选它。
    cfg = AppConfig(stt_providers={"openai": STTProviderConnection(model="whisper-1")})
    assert isinstance(build_default_stt(cfg), OpenAICompatSTTAdapter)

    # 多 provider + 指定 default → 选指定的（这里指定本地）。
    cfg2 = AppConfig(
        stt_providers={
            "openai": STTProviderConnection(model="whisper-1"),
            "local": STTProviderConnection(kind="faster_whisper", model="base"),
        },
        default_stt_provider="local",
    )
    assert isinstance(build_default_stt(cfg2), FasterWhisperSTTAdapter)


# ── OpenAI 兼容 STT：响应规整（含时间戳）──────────────────────────
def test_to_transcript_with_segments():
    class _Seg:
        def __init__(self, start, end, text):
            self.start, self.end, self.text = start, end, text

    class _Resp:
        text = "  Hello there.  "
        language = "en"
        segments = [_Seg(0.0, 1.2, "Hello"), _Seg(1.2, 2.0, "there.")]

    t = _to_transcript(_Resp(), fallback_language=None)
    assert t.text == "Hello there."
    assert t.language == "en"
    # 时间戳保留（流利度信号，ADR-005/013）。
    assert t.segments == [(0.0, 1.2, "Hello"), (1.2, 2.0, "there.")]


def test_to_transcript_handles_dict_segments_and_missing():
    class _Resp:
        text = "hi"
        language = None
        segments = [{"start": 0.0, "end": 0.5, "text": "hi"}, {"text": "no-times"}]

    t = _to_transcript(_Resp(), fallback_language="en")
    assert t.text == "hi"
    assert t.language == "en"  # 回落到 fallback
    # 缺时间戳的段被跳过，不污染 segments。
    assert t.segments == [(0.0, 0.5, "hi")]


def test_openai_compat_stt_no_key_placeholder():
    adapter = OpenAICompatSTTAdapter(model="whisper-1", base_url="http://localhost:9000/v1")
    assert adapter._client.api_key == "not-needed"
