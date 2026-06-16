"""OpenAICompatTTSAdapter —— 默认 TTS 适配器（L4，ADR-012）。

打 OpenAI 音频协议 `/v1/audio/speech`，填 base_url + api_key + model 即可对接云端
（OpenAI 等）或暴露同协议的本地服务。流式合成用 SDK 的 streaming response，逐块
yield 给 WebSocket 播放（docs/02 语音流式）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal

from openai import AsyncOpenAI

from app.adapters.speech import TTSProvider

# OpenAI 音频格式（SDK 以 Literal 约束）。
AudioFormat = Literal["mp3", "opus", "aac", "flac", "wav", "pcm"]
# 各格式 → MIME 类型（供前端按正确解码器播放）。
_FORMAT_MIME: dict[str, str] = {
    "mp3": "audio/mpeg",
    "opus": "audio/ogg",
    "aac": "audio/aac",
    "flac": "audio/flac",
    "wav": "audio/wav",
    "pcm": "audio/L16",
}
# OpenAI 默认音色；可被调用方/配置覆盖。
_DEFAULT_VOICE = "alloy"
# 流式分块大小（字节）。够小以低延迟开播，又不至于过碎。
_CHUNK_SIZE = 4096


class OpenAICompatTTSAdapter(TTSProvider):
    def __init__(
        self,
        *,
        model: str = "tts-1",
        base_url: str | None = None,
        api_key: str | None = None,
        voice: str | None = None,
        response_format: AudioFormat = "mp3",
    ) -> None:
        self._model = model
        self._voice = voice or _DEFAULT_VOICE
        self._format: AudioFormat = response_format
        # content_type 随配置的格式而定（默认 mp3→audio/mpeg）。
        self.content_type = _FORMAT_MIME.get(response_format, "audio/mpeg")
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key or "not-needed")

    async def synthesize(self, text: str, *, voice: str | None = None) -> bytes:
        resp = await self._client.audio.speech.create(
            model=self._model,
            voice=voice or self._voice,
            input=text,
            response_format=self._format,
        )
        return resp.content

    async def stream_synthesize(
        self, text: str, *, voice: str | None = None
    ) -> AsyncIterator[bytes]:
        async with self._client.audio.speech.with_streaming_response.create(
            model=self._model,
            voice=voice or self._voice,
            input=text,
            response_format=self._format,
        ) as resp:
            async for chunk in resp.iter_bytes(_CHUNK_SIZE):
                if chunk:
                    yield chunk
