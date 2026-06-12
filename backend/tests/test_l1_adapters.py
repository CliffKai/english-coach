"""L1 验证（docs/07）：LLM 适配器构造 + 消息映射 + 工厂 + 发音占位。

全程离线：不发真实网络请求，只验证「装配正确」——system 抽取、payload 形状、
工厂按 kind 选对适配器、NoneAdapter 返回 estimated。真实 chat 连通性属手动/集成测试。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.adapters.claude import DEFAULT_CLAUDE_MODEL, ClaudeAdapter
from app.adapters.llm import ChatMessage, Role
from app.adapters.llm_factory import build_adapter, build_default_llm, build_for_provider
from app.adapters.openai_compat import OpenAICompatAdapter
from app.adapters.pronunciation import NonePronunciationAdapter
from app.config import AppConfig, LLMProviderConnection
from app.models.enums import LLMAdapterKind


# ── ClaudeAdapter：system 抽取 ──────────────────────────────────────
def test_claude_split_extracts_system_and_keeps_order():
    msgs = [
        ChatMessage(role=Role.SYSTEM, content="You are a strict IELTS examiner."),
        ChatMessage(role=Role.USER, content="Score my essay."),
        ChatMessage(role=Role.ASSISTANT, content="Sure."),
        ChatMessage(role=Role.SYSTEM, content="Use band 0-9."),
    ]
    system, convo = ClaudeAdapter._split(msgs)
    # 多条 system 合并；messages 不含 system。
    assert "strict IELTS examiner" in system and "band 0-9" in system
    assert [m["role"] for m in convo] == ["user", "assistant"]
    assert convo[0]["content"] == "Score my essay."


def test_claude_split_no_system_returns_none():
    system, convo = ClaudeAdapter._split([ChatMessage(role=Role.USER, content="hi")])
    assert system is None
    assert convo == [{"role": "user", "content": "hi"}]


def test_claude_default_model_is_opus():
    adapter = ClaudeAdapter(api_key="sk-ant-test")
    assert adapter._default_model == DEFAULT_CLAUDE_MODEL == "claude-opus-4-8"


# ── OpenAICompatAdapter：payload 映射 + 无 key 兜底 ─────────────────
def test_openai_compat_payload_maps_roles():
    adapter = OpenAICompatAdapter(model="deepseek-chat", base_url="http://x/v1")
    payload = adapter._payload(
        [
            ChatMessage(role=Role.SYSTEM, content="sys"),
            ChatMessage(role=Role.USER, content="u"),
        ]
    )
    assert payload == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "u"},
    ]


def test_openai_compat_local_no_key_uses_placeholder():
    # 本地 Ollama 无 key：SDK 不接受空 key，适配器须兜底，不应抛错。
    adapter = OpenAICompatAdapter(model="qwen2.5", base_url="http://localhost:11434/v1")
    assert adapter._client.api_key == "not-needed"


# ── 工厂：按 kind 选适配器 ──────────────────────────────────────────
def test_build_adapter_routes_by_kind():
    claude = build_adapter(LLMProviderConnection(kind="claude", api_key="sk-ant-x"), "opus")
    compat = build_adapter(
        LLMProviderConnection(kind="openai_compat", base_url="http://x/v1", api_key="k"),
        "deepseek-chat",
    )
    assert isinstance(claude, ClaudeAdapter)
    assert isinstance(compat, OpenAICompatAdapter)


def test_unknown_kind_rejected_at_config_load_not_silently_openai():
    # 拼错 / 大小写不符的 kind 必须在配置模型校验期就报错，
    # 不能被静默当成 OpenAI 兼容（否则 Claude 凭证会塞进 OpenAI 客户端）。
    for bad in ("Claude", "anthropic", "claud", "openai"):
        with pytest.raises(ValidationError):
            LLMProviderConnection(kind=bad, api_key="x")
    # 合法值仍正常（字符串自动转枚举）。
    assert LLMProviderConnection(kind="claude").kind == LLMAdapterKind.CLAUDE
    assert LLMProviderConnection().kind == LLMAdapterKind.OPENAI_COMPAT  # 默认


def test_build_for_provider_looks_up_connection():
    config = AppConfig(
        llm_providers={
            "deepseek": LLMProviderConnection(base_url="http://x/v1", api_key="k"),
        }
    )
    adapter = build_for_provider(config, "deepseek", "deepseek-chat")
    assert isinstance(adapter, OpenAICompatAdapter)
    with pytest.raises(KeyError):
        build_for_provider(config, "missing", "m")


def test_build_default_llm_prefers_claude_else_none():
    # 无配置 → None（容器 llm 留空，功能层用到时报缺配置）。
    assert build_default_llm(AppConfig(llm_providers={})) is None

    # 有 Claude（按 kind 识别，而非 provider 名）→ 默认绑 claude。
    # 故意用非 "claude" 的键名，证明选择依据是 kind。
    cfg = AppConfig(
        llm_providers={"my-scorer": LLMProviderConnection(kind="claude", api_key="x")}
    )
    assert isinstance(build_default_llm(cfg), ClaudeAdapter)

    # 只有 OpenAI 兼容（无从知 model）→ None（须显式 build_for_provider 指定 model）。
    cfg2 = AppConfig(
        llm_providers={"ollama": LLMProviderConnection(base_url="http://localhost:11434/v1")}
    )
    assert build_default_llm(cfg2) is None


# ── 发音占位（ADR-003）──────────────────────────────────────────────
@pytest.mark.asyncio
async def test_none_pronunciation_returns_estimated():
    result = await NonePronunciationAdapter().assess(b"", reference_text="hello world")
    assert result.estimated is True
    assert result.accuracy is None and result.fluency is None
