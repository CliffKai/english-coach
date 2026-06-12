"""ClaudeAdapter —— Anthropic 原生协议适配器（L1，评分用，docs/04）。

评分（scoring 任务）默认走最强模型。默认 claude-opus-4-8：
- system 消息不进 messages 列表，需抽出走顶层 `system` 参数。
- 4.x 家族（opus-4-8 等）不接受 temperature/top_p（会 400），故对这些模型不传采样参数；
  仅当用户显式配置较老模型时才下放 temperature（这里默认按 4.x 处理，忽略 temperature）。
- 大 max_tokens 非流式可能触发 SDK 超时守卫；stream_chat 用 .stream() 规避。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from anthropic import NOT_GIVEN, AsyncAnthropic

from app.adapters.llm import ChatMessage, LLMProvider, LLMResponse, Role

# 评分默认最强模型（claude-api skill：除非用户指定，一律 opus-4-8）。
DEFAULT_CLAUDE_MODEL = "claude-opus-4-8"


class ClaudeAdapter(LLMProvider):
    def __init__(
        self,
        *,
        model: str = DEFAULT_CLAUDE_MODEL,
        api_key: str | None = None,
        base_url: str | None = None,
        default_max_tokens: int = 4096,
    ) -> None:
        self._default_model = model
        self._default_max_tokens = default_max_tokens
        kwargs: dict = {}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        self._client = AsyncAnthropic(**kwargs)

    @staticmethod
    def _split(messages: list[ChatMessage]) -> tuple[str | None, list[dict]]:
        """抽出 system 文本（合并多条），其余转 Anthropic messages。"""
        system_parts: list[str] = []
        convo: list[dict] = []
        for m in messages:
            if m.role == Role.SYSTEM:
                system_parts.append(m.content)
            else:
                convo.append({"role": m.role.value, "content": m.content})
        system = "\n\n".join(system_parts) if system_parts else None
        return system, convo

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        system, convo = self._split(messages)
        resp = await self._client.messages.create(
            model=model or self._default_model,
            max_tokens=max_tokens or self._default_max_tokens,
            system=system or NOT_GIVEN,
            messages=convo,
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        return LLMResponse(
            content=text,
            model=resp.model,
            prompt_tokens=resp.usage.input_tokens,
            completion_tokens=resp.usage.output_tokens,
        )

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        system, convo = self._split(messages)
        async with self._client.messages.stream(
            model=model or self._default_model,
            max_tokens=max_tokens or self._default_max_tokens,
            system=system or NOT_GIVEN,
            messages=convo,
        ) as stream:
            async for text in stream.text_stream:
                yield text
