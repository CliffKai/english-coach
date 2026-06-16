"""PiperTTSAdapter —— 纯本地离线 TTS（L4，ADR-012，可选）。

piper-tts 完全离线、隐私优先（与本地优先取向一致）。重依赖 + 需下载语音模型 .onnx，
故放 [voice] 可选依赖组并在此**懒加载**（沿用 SpacyTokenizer/FsrsScheduler 风格）。

piper 是同步库，合成在线程池跑。piper 一次产出整段 WAV；流式分支按固定块大小切片
yield（满足 stream_synthesize 接口，给 WebSocket 低延迟开播）。
"""

from __future__ import annotations

import asyncio
import io
import wave
from collections.abc import AsyncIterator
from functools import lru_cache

from app.adapters.speech import TTSProvider

_CHUNK_SIZE = 4096


@lru_cache(maxsize=2)
def _load_voice(model_path: str):
    from piper import PiperVoice

    return PiperVoice.load(model_path)


class PiperTTSAdapter(TTSProvider):
    # piper 产出 WAV（见 _synthesize_sync 用 wave 写入）。
    content_type = "audio/wav"

    def __init__(self, *, model: str) -> None:
        # model：piper 语音模型 .onnx 路径（需用户预先下载，无在线回退——这是离线适配器）。
        if not model:
            raise ValueError("PiperTTSAdapter 需要 model（语音模型 .onnx 路径）")
        self._model_path = model

    async def synthesize(self, text: str, *, voice: str | None = None) -> bytes:
        # voice 形参对 piper 无意义（音色由 .onnx 模型本身决定），保留以符合接口。
        return await asyncio.to_thread(self._synthesize_sync, text)

    def _synthesize_sync(self, text: str) -> bytes:
        voice_model = _load_voice(self._model_path)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            voice_model.synthesize(text, wav)
        return buf.getvalue()

    async def stream_synthesize(
        self, text: str, *, voice: str | None = None
    ) -> AsyncIterator[bytes]:
        # piper 一次产出整段 WAV；切片 yield 以满足流式接口（非真增量合成，但播放低延迟）。
        audio = await self.synthesize(text, voice=voice)
        for i in range(0, len(audio), _CHUNK_SIZE):
            yield audio[i : i + _CHUNK_SIZE]
