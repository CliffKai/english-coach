"""OpenAICompatAdapter —— 覆盖 ~80% 模型的 LLM 适配器（L1，docs/04 关键洞察）。

填 base_url + api_key + model 即可对接 DeepSeek / Qwen / Kimi / 智谱 / vLLM /
Ollama / LM Studio 等任何兼容 OpenAI /v1/chat/completions 协议的服务。
本地模型（Ollama 等）无需 key，api_key 留空时填占位串（SDK 要求非空）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from app.adapters.llm import ChatMessage, LLMProvider, LLMResponse


class OpenAICompatAdapter(LLMProvider):
    def __init__(
        self,
        *,
        model: str,
        base_url: str | None = None,
        api_key: str | None = None,
        default_max_tokens: int = 4096,
    ) -> None:
        self._default_model = model
        self._default_max_tokens = default_max_tokens
        # 本地服务常无鉴权；SDK 不接受空 key，给个占位。
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key or "not-needed")

    def _payload(self, messages: list[ChatMessage]) -> list[dict]:
        return [{"role": m.role.value, "content": m.content} for m in messages]

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        resp = await self._client.chat.completions.create(
            model=model or self._default_model,
            messages=self._payload(messages),
            temperature=temperature,
            max_tokens=max_tokens or self._default_max_tokens,
        )
        choice = resp.choices[0]
        usage = resp.usage
        return LLMResponse(
            content=choice.message.content or "",
            model=resp.model,
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
        )

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        stream = await self._client.chat.completions.create(
            model=model or self._default_model,
            messages=self._payload(messages),
            temperature=temperature,
            max_tokens=max_tokens or self._default_max_tokens,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta
