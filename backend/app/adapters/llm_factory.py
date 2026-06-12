"""按配置构建 LLMProvider 适配器（L1）。

Settings.model_config 按任务（scoring/reasoning/tokenize/conversation）选一个 provider 名
+ model；provider 的连接信息（base_url/api_key/kind）在 AppConfig.llm_providers 里按名查得。
本工厂据此构建对应适配器。任务→适配器的「路由」是 L3 Agent 层的事；L1 只负责
「给定 provider 名 + model 造出能跑的适配器」，并能挑一个默认 provider 绑进容器验证连通。
"""

from __future__ import annotations

from app.adapters.claude import ClaudeAdapter
from app.adapters.llm import LLMProvider
from app.adapters.openai_compat import OpenAICompatAdapter
from app.config import AppConfig, LLMProviderConnection
from app.models.enums import LLMAdapterKind


def build_adapter(conn: LLMProviderConnection, model: str) -> LLMProvider:
    """据连接信息的 kind 造适配器。kind 已由 config 模型约束为合法枚举值。"""
    if conn.kind == LLMAdapterKind.CLAUDE:
        return ClaudeAdapter(model=model, api_key=conn.api_key, base_url=conn.base_url)
    if conn.kind == LLMAdapterKind.OPENAI_COMPAT:
        return OpenAICompatAdapter(model=model, base_url=conn.base_url, api_key=conn.api_key)
    # 枚举已穷尽；新增 kind 未在此分支处理时显式报错，而非静默落到某个适配器。
    raise ValueError(f"未支持的 LLM 适配器 kind: {conn.kind}")


def build_for_provider(config: AppConfig, provider: str, model: str) -> LLMProvider:
    """按 provider 名查连接信息并构建适配器。未配置则抛 KeyError。"""
    conn = config.llm_providers[provider]
    return build_adapter(conn, model)


def build_default_llm(config: AppConfig) -> LLMProvider | None:
    """挑一个默认 LLM 绑进容器（L1 验证「跑通一次 chat」用）。

    优先 Claude（评分主力，且自带默认 model），否则返回 None：OpenAI 兼容必须指定
    model，无从得知用哪个，故默认 LLM 仅在配了 Claude provider 时可用；其余走
    build_for_provider 显式指定。都没配则返回 None（容器 llm 未绑定，用到时再报缺配置）。
    """
    for conn in config.llm_providers.values():
        if conn.kind == LLMAdapterKind.CLAUDE:
            return ClaudeAdapter(api_key=conn.api_key, base_url=conn.base_url)
    return None
