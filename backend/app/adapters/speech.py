"""语音适配器接口：STTProvider / TTSProvider / PronunciationProvider。

L0 只定接口。实现推迟到 L4（STT/TTS）；PronunciationProvider 的 NoneAdapter
是 L1 唯一实现（ADR-003：第一版默认 none，发音/流利度维度标注「基于文本估算」）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from pydantic import BaseModel


class Transcript(BaseModel):
    """STT 结果。segments 预留时间戳（卡顿/停顿是流利度信号，ADR-005 不可抹平）。"""

    text: str
    language: str | None = None
    # 每段 (start_sec, end_sec, text)，用于流利度分析；适配器尽力填充。
    segments: list[tuple[float, float, str]] = []


class STTProvider(ABC):
    """语音转文字（docs/04，L4 接 faster-whisper 本地）。"""

    @abstractmethod
    async def transcribe(self, audio: bytes, *, language: str | None = None) -> Transcript:
        """整段音频转写。"""


class TTSProvider(ABC):
    """文字转语音（docs/04，L4）。"""

    # 合成音频的 MIME 类型（供前端按正确解码器播放：mp3→audio/mpeg、wav→audio/wav…）。
    # 默认 mp3；产出其他格式的适配器（如本地 Piper 出 WAV）须覆盖，否则浏览器会用错
    # 解码器导致播放失败。
    content_type: str = "audio/mpeg"

    @abstractmethod
    async def synthesize(self, text: str, *, voice: str | None = None) -> bytes:
        """合成整段音频，返回字节（如 wav/mp3）。"""

    @abstractmethod
    def stream_synthesize(
        self, text: str, *, voice: str | None = None
    ) -> AsyncIterator[bytes]:
        """流式合成，逐块 yield 音频（WebSocket 播放用）。"""


class PronunciationResult(BaseModel):
    """发音评估结果（ADR-003）。

    estimated=True 表示由 NoneAdapter 基于文本估算，前端须标注「仅供参考」。
    填入 Azure key 后 estimated=False，含音素级真实评分。
    """

    accuracy: float | None = None
    fluency: float | None = None
    completeness: float | None = None
    # 音素/单词级明细（Azure 提供；NoneAdapter 留空）。
    details: dict | None = None
    estimated: bool = True


class PronunciationProvider(ABC):
    """发音评估（ADR-003，默认 NoneAdapter）。"""

    @abstractmethod
    async def assess(
        self, audio: bytes, *, reference_text: str
    ) -> PronunciationResult:
        """对照参考文本评估发音。NoneAdapter 返回 estimated=True 的占位结果。"""
