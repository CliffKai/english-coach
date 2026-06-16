"""领域实体模型（mirror docs/03-data-model.md）。

四个实体对应四张表，全部带 user_id（默认 local-user，ADR-007）。
这些是纯数据模型，不含持久化逻辑——持久化由 app.adapters 的 Repository 接口负责。
"""

from app.models.entities import (
    DEFAULT_USER_ID,
    ErrorEntry,
    FsrsState,
    PracticeSession,
    Settings,
    VocabEntry,
)
from app.models.enums import (
    ErrorType,
    LLMAdapterKind,
    PracticeMode,
    PronunciationProviderKind,
    ScoringStandard,
    STTAdapterKind,
    StorageBackend,
    TTSAdapterKind,
    VocabStatus,
)

__all__ = [
    "DEFAULT_USER_ID",
    "VocabEntry",
    "ErrorEntry",
    "PracticeSession",
    "Settings",
    "FsrsState",
    "VocabStatus",
    "ErrorType",
    "PracticeMode",
    "ScoringStandard",
    "StorageBackend",
    "PronunciationProviderKind",
    "LLMAdapterKind",
    "STTAdapterKind",
    "TTSAdapterKind",
]
