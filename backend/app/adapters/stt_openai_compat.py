"""OpenAICompatSTTAdapter —— 默认 STT 适配器（L4，ADR-012）。

打 OpenAI 音频协议 `/v1/audio/transcriptions`，填 base_url + api_key + model 即可对接
云端（OpenAI / Groq …）或任何暴露同协议的本地服务（faster-whisper-server 等）。
复刻 OpenAICompatAdapter（LLM）的「一个兼容适配器打天下」思路。

时间戳：请求 verbose_json + segment 粒度，把每段 (start, end, text) 填进 Transcript.segments
（流利度信号，ADR-005/013 不可抹平）。服务不支持时优雅降级为只有整段 text。
"""

from __future__ import annotations

import io

from openai import AsyncOpenAI, omit

from app.adapters.speech import STTProvider, Transcript


class OpenAICompatSTTAdapter(STTProvider):
    def __init__(
        self,
        *,
        model: str = "whisper-1",
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._model = model
        # 本地服务常无鉴权；SDK 不接受空 key，给个占位（同 OpenAICompatAdapter）。
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key or "not-needed")

    async def transcribe(self, audio: bytes, *, language: str | None = None) -> Transcript:
        # SDK 要求一个带名字的 file-like；扩展名让服务端推断容器格式（webm/wav/mp3 皆可）。
        buf = io.BytesIO(audio)
        buf.name = "audio.webm"
        lang = language or omit
        try:
            verbose = await self._client.audio.transcriptions.create(
                model=self._model,
                file=buf,
                language=lang,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )
            return _to_transcript(verbose, fallback_language=language)
        except Exception:
            # 服务不支持 verbose_json/时间戳（部分本地实现）→ 退回最简纯文本转写。
            buf.seek(0)
            plain = await self._client.audio.transcriptions.create(
                model=self._model, file=buf, language=lang
            )
            return _to_transcript(plain, fallback_language=language)


def _to_transcript(resp, *, fallback_language: str | None) -> Transcript:
    """把 SDK 返回（verbose_json 对象或纯文本对象）规整成 Transcript。"""
    text = (getattr(resp, "text", "") or "").strip()
    language = getattr(resp, "language", None) or fallback_language
    segments: list[tuple[float, float, str]] = []
    for seg in getattr(resp, "segments", None) or []:
        # SDK 6.x segment 是对象；老版本/本地服务可能给 dict。两者都兜住。
        start = _get(seg, "start")
        end = _get(seg, "end")
        seg_text = (_get(seg, "text") or "").strip()
        if start is not None and end is not None and seg_text:
            segments.append((float(start), float(end), seg_text))
    return Transcript(text=text, language=language, segments=segments)


def _get(obj, key: str):
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
