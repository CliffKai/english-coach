"""适配器接口骨架（ADR-002：一切外部依赖皆适配器）。

L0 只定义接口与数据类型，不写任何实现。业务代码只依赖这些接口；
具体实现（OpenAICompatAdapter / ClaudeAdapter / LocalAdapter / WhisperLocalAdapter …）
在 L1+ 逐步落地，通过依赖注入替换。

接口清单（docs/07 L0）：
- LLMProvider            app.adapters.llm
- WordRepository         app.adapters.repository
- ErrorRepository        app.adapters.repository
- SessionRepository      app.adapters.repository
- SettingsRepository     app.adapters.repository
- STTProvider            app.adapters.speech
- TTSProvider            app.adapters.speech
- PronunciationProvider  app.adapters.speech

L1 实现：
- OpenAICompatAdapter / ClaudeAdapter        app.adapters.{openai_compat,claude}
- Sqlite{Word,Error,Session,Settings}Repository  app.adapters.local
- NonePronunciationAdapter                   app.adapters.pronunciation
"""

from app.adapters.claude import ClaudeAdapter
from app.adapters.llm import ChatMessage, LLMProvider, LLMResponse, Role
from app.adapters.local import (
    SqliteErrorRepository,
    SqliteSessionRepository,
    SqliteSettingsRepository,
    SqliteWordRepository,
)
from app.adapters.openai_compat import OpenAICompatAdapter
from app.adapters.pronunciation import NonePronunciationAdapter
from app.adapters.repository import (
    ErrorRepository,
    SessionRepository,
    SettingsRepository,
    WordRepository,
)
from app.adapters.speech import (
    PronunciationProvider,
    PronunciationResult,
    STTProvider,
    Transcript,
    TTSProvider,
)

__all__ = [
    # 接口
    "LLMProvider",
    "ChatMessage",
    "LLMResponse",
    "Role",
    "WordRepository",
    "ErrorRepository",
    "SessionRepository",
    "SettingsRepository",
    "STTProvider",
    "TTSProvider",
    "PronunciationProvider",
    "Transcript",
    "PronunciationResult",
    # L1 实现
    "OpenAICompatAdapter",
    "ClaudeAdapter",
    "SqliteWordRepository",
    "SqliteErrorRepository",
    "SqliteSessionRepository",
    "SqliteSettingsRepository",
    "NonePronunciationAdapter",
]
