"""受约束字段的枚举。集中定义，供模型、DB、接口共用。"""

from enum import Enum


class VocabStatus(str, Enum):
    """生词学习状态（docs/03 VocabEntry.status）。"""

    NEW = "new"
    LEARNING = "learning"
    KNOWN = "known"


class ErrorType(str, Enum):
    """错误类型（docs/03 ErrorEntry.type）。"""

    GRAMMAR = "grammar"
    COLLOCATION = "collocation"
    SPELLING = "spelling"
    LOGIC = "logic"
    VOCABULARY = "vocabulary"
    PRONUNCIATION = "pronunciation"


class PracticeMode(str, Enum):
    """话题练习四模式（docs/01 功能2）。

    练习模式（即时纠错，TutorAgent）：guided_write / guided_speak
    考试模式（延迟纠错，ExaminerAgent）：free_write / dialogue
    """

    GUIDED_WRITE = "guided_write"
    GUIDED_SPEAK = "guided_speak"
    FREE_WRITE = "free_write"
    DIALOGUE = "dialogue"

    @property
    def is_exam_mode(self) -> bool:
        """考试模式 = 延迟纠错 + 打分（ADR-005）。"""
        return self in (PracticeMode.FREE_WRITE, PracticeMode.DIALOGUE)


class ScoringStandard(str, Enum):
    """打分标准（docs/03 Settings.scoring_standard）。"""

    IELTS = "IELTS"
    TOEFL = "TOEFL"


class StorageBackend(str, Enum):
    """存储后端（docs/03 Settings.storage_backend）。L0/L1 仅 local。"""

    LOCAL = "local"
    CLOUD = "cloud"


class PronunciationProviderKind(str, Enum):
    """发音评估 provider（ADR-003，默认 none）。"""

    NONE = "none"
    AZURE = "azure"


class LLMAdapterKind(str, Enum):
    """LLM 适配器协议种类（docs/04）。决定 provider 连接走哪个适配器。

    用枚举而非裸字符串：拼错/大小写不符的 kind 在配置加载期即报错，
    不会被静默当成 OpenAI 兼容（否则 Claude 凭证可能被塞进 OpenAI 客户端）。
    """

    OPENAI_COMPAT = "openai_compat"
    CLAUDE = "claude"


class STTAdapterKind(str, Enum):
    """语音转文字适配器种类（ADR-012）。默认走 OpenAI 兼容音频协议。

    - openai_compat → OpenAICompatSTTAdapter（/v1/audio/transcriptions，云/本地服务皆可）
    - faster_whisper → FasterWhisperSTTAdapter（纯本地离线，可选）
    """

    OPENAI_COMPAT = "openai_compat"
    FASTER_WHISPER = "faster_whisper"


class TTSAdapterKind(str, Enum):
    """文字转语音适配器种类（ADR-012）。默认走 OpenAI 兼容音频协议。

    - openai_compat → OpenAICompatTTSAdapter（/v1/audio/speech，云/本地服务皆可）
    - piper → PiperTTSAdapter（纯本地离线，可选）
    """

    OPENAI_COMPAT = "openai_compat"
    PIPER = "piper"
