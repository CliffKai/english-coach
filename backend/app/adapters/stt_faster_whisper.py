"""FasterWhisperSTTAdapter —— 纯本地离线 STT（L4，ADR-012，可选）。

完全离线、隐私优先（与本地优先取向一致）。faster-whisper 是重依赖（ctranslate2），
故放 [voice] 可选依赖组，并在此**懒加载**（沿用 SpacyTokenizer/FsrsScheduler 的
import-inside 风格）：模块导入仍轻，未装 [voice] 也不影响其余功能与测试。

转写在线程池跑（faster-whisper 是同步、CPU/GPU 密集），避免阻塞事件循环。
segments 直接来自模型的分段（含时间戳，流利度信号 ADR-005/013）。
"""

from __future__ import annotations

import asyncio
import io
from functools import lru_cache

from app.adapters.speech import STTProvider, Transcript


# 模型加载开销大，按 (model, device, compute_type) 缓存单例（进程内复用，同 _load_nlp）。
@lru_cache(maxsize=2)
def _load_model(model: str, device: str, compute_type: str):
    from faster_whisper import WhisperModel

    return WhisperModel(model, device=device, compute_type=compute_type)


class FasterWhisperSTTAdapter(STTProvider):
    def __init__(
        self,
        *,
        model: str = "base",
        device: str = "auto",
        compute_type: str = "default",
    ) -> None:
        self._model = model
        self._device = device
        self._compute_type = compute_type

    async def transcribe(self, audio: bytes, *, language: str | None = None) -> Transcript:
        return await asyncio.to_thread(self._transcribe_sync, audio, language)

    def _transcribe_sync(self, audio: bytes, language: str | None) -> Transcript:
        model = _load_model(self._model, self._device, self._compute_type)
        # faster-whisper 接受 file-like（用 ffmpeg/pyav 解码任意容器：webm/wav/mp3）。
        segments_iter, info = model.transcribe(io.BytesIO(audio), language=language)
        segments: list[tuple[float, float, str]] = []
        parts: list[str] = []
        for seg in segments_iter:  # 惰性迭代器，遍历即触发实际转写
            seg_text = seg.text.strip()
            if seg_text:
                segments.append((float(seg.start), float(seg.end), seg_text))
                parts.append(seg_text)
        return Transcript(
            text=" ".join(parts).strip(),
            language=getattr(info, "language", None) or language,
            segments=segments,
        )
