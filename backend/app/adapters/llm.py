"""LLMProvider 接口（docs/04）。

落地重点（L1）：OpenAICompatAdapter（base_url/api_key/model_name 覆盖 ~80% 模型：
DeepSeek/Qwen/Kimi/vLLM/Ollama/LM Studio…）+ ClaudeAdapter（原生协议，评分用）。
L0 只定接口与消息类型。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from enum import Enum

from pydantic import BaseModel


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(BaseModel):
    role: Role
    content: str


class LLMResponse(BaseModel):
    content: str
    model: str
    # 用量信息（如可得），用于成本核算；适配器尽力填充。
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMProvider(ABC):
    """聊天补全接口。所有 Agent 经此调用模型，按任务分配不同 provider（ADR-006）。"""

    @abstractmethod
    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """一次非流式补全。model 为空时用适配器默认模型。"""

    @abstractmethod
    def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """流式补全，逐段 yield 文本增量（语音/对话用，docs/02）。"""
