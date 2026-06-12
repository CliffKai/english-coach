"""PronunciationProvider 实现（L1 唯一实现：NoneAdapter，ADR-003）。

第一版默认不做声学发音评估。NoneAdapter 返回 estimated=True 的占位结果，
前端据此把口语「发音/流利度」维度标注「基于文本估算，仅供参考」。
填入 Azure key 后由 AzureAdapter（L4+）替换为音素级真实评分。
"""

from __future__ import annotations

from app.adapters.speech import PronunciationProvider, PronunciationResult


class NonePronunciationAdapter(PronunciationProvider):
    async def assess(self, audio: bytes, *, reference_text: str) -> PronunciationResult:
        # 不做真实评估：分值留空，estimated=True 表明由文本估算/占位。
        return PronunciationResult(estimated=True)
