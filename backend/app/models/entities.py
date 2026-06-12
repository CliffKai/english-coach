"""四个核心领域实体（docs/03-data-model.md）。

设计不变量（不经新 ADR 不得违反）：
- VocabEntry 不存释义，只存 word + lemma + context_sentences[]（ADR-004）。
- 所有实体带 user_id，默认 local-user（ADR-007）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from app.models.enums import (
    ErrorType,
    PracticeMode,
    ScoringStandard,
    StorageBackend,
    VocabStatus,
)

# 单用户本地优先（ADR-007）：字段保留，值默认 local-user。
DEFAULT_USER_ID = "local-user"


def _new_id() -> str:
    return uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class FsrsState(BaseModel):
    """FSRS 间隔重复状态（docs/03 VocabEntry.fsrs_state）。

    L0 只定义形状；真正的调度逻辑在 L2 接入 FSRS 库时实现。
    多义词调度单位（按词 vs 按义项）是 L2 必须先定的红线（见 07 已知风险），
    L0 先按「一个 VocabEntry 一个 fsrs_state」建模。
    """

    difficulty: float = 0.0
    stability: float = 0.0
    due: datetime | None = None
    review_count: int = 0
    last_review: datetime | None = None


class UserUnderstanding(BaseModel):
    """用户复习时说出的理解（历史记录，非标准答案，ADR-004）。"""

    text: str
    created_at: datetime = Field(default_factory=_now)


class VocabEntry(BaseModel):
    """生词条目 —— 功能1产出，功能3消费。

    关键：context_sentences 是来源句列表，同词不同义存多条（ADR-004）。
    """

    id: str = Field(default_factory=_new_id)
    user_id: str = DEFAULT_USER_ID
    word: str
    lemma: str
    context_sentences: list[str] = Field(default_factory=list)
    status: VocabStatus = VocabStatus.NEW
    fsrs_state: FsrsState = Field(default_factory=FsrsState)
    user_understanding: list[UserUnderstanding] = Field(default_factory=list)
    source_text_id: str | None = None
    created_at: datetime = Field(default_factory=_now)


class ErrorEntry(BaseModel):
    """错题条目 —— 功能2（考试模式）产出，汇入错题本。"""

    id: str = Field(default_factory=_new_id)
    user_id: str = DEFAULT_USER_ID
    type: ErrorType
    original: str
    correction: str
    explanation: str
    session_id: str | None = None
    topic: str | None = None
    severity: int = 1
    # 连续 N 次未再犯则标记 resolved，复盘不再唠叨（阶段2 的「错题毕业」机制）。
    resolved: bool = False
    created_at: datetime = Field(default_factory=_now)


class PracticeSession(BaseModel):
    """练习会话 —— 功能2。scores 为各维度分数 JSON，error_ids 引用本次错误。"""

    id: str = Field(default_factory=_new_id)
    user_id: str = DEFAULT_USER_ID
    mode: PracticeMode
    topic: str | None = None
    transcript: str = ""
    scores: dict | None = None
    error_ids: list[str] = Field(default_factory=list)
    summary: str | None = None
    # 提前交卷标记（ADR-005）：按已有内容打分，不是救场。
    ended_early: bool = False
    created_at: datetime = Field(default_factory=_now)


class ModelAssignment(BaseModel):
    """单个任务的模型分配（docs/04 models: 按任务分配）。

    provider 指向 Settings 中配置的某个 LLM provider（如 claude / deepseek / ollama），
    base_url / api_key 由该 provider 的连接配置提供，这里只选 provider + model。
    """

    provider: str
    model: str


class ModelConfig(BaseModel):
    """per-task 模型分配（ADR-006）。任务键固定，值可由用户改。"""

    scoring: ModelAssignment | None = None  # 评分：最强
    reasoning: ModelAssignment | None = None  # 引导/复盘：中档
    tokenize: ModelAssignment | None = None  # 切词判断：本地/轻量
    conversation: ModelAssignment | None = None  # 高频对话：性价比


class Settings(BaseModel):
    """用户配置（docs/03 Settings）。

    注意与 app.config.AppConfig 区分：
    - 这个 Settings 是「用户在应用内可改的偏好」，持久化进 settings 表。
    - AppConfig 是「进程级环境配置」（端口、数据库路径、密钥来源），来自 .env。
    """

    user_id: str = DEFAULT_USER_ID
    storage_backend: StorageBackend = StorageBackend.LOCAL
    scoring_standard: ScoringStandard = ScoringStandard.IELTS
    target_band: float | None = None
    native_lang: str = "zh"
    # 水平基线（CEFR / 估算雅思分）。首次分级写入；F1 过滤与 F2 打分都参照它。
    level_baseline: str | None = None
    voice_enabled: bool = False
    model_config_: ModelConfig = Field(default_factory=ModelConfig, alias="model_config")
    pronunciation_provider: str = "none"

    # 允许用别名 model_config 读写（pydantic 把 model_config 作保留名，故内部用 model_config_）。
    model_config = {"populate_by_name": True}
