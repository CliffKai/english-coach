"""Agent 编排层（docs/02）。

Agent 是「功能逻辑」的归属地：编排 L1 适配器（LLM/存储）+ L2 服务（切词/调度），
把确定性预处理与 LLM 判断粘合成一个功能。业务路由（app.api）只调用 Agent，不直接
碰适配器细节。

L3 落地五个（按 07 严格顺序）：
- LevelingAgent       水平基线分级（scoring 任务，写 Settings.level_baseline）—— 先于 F1/F2
- TokenizerAgent      F1 生词收集（复用 L2 SpacyTokenizer，确定性切词+过滤+查重入库）
- MemoryWordAgent     F3a 理解式背词（reasoning 任务，判断复述理解 → 映射 FSRS 评级，ADR-011）
- ExaminerAgent       F2c/F2d 考试模式打分（scoring 任务，延迟纠错 + 多维度打分；2d 对话）
- ErrorAnalysisAgent  F2 收尾（reasoning 任务，buffer → 错题本 + 模式识别复盘）—— 紧跟 Examiner
- TutorAgent          F2a/2b 引导写/说（reasoning 任务，练习模式即时纠错 + 脚手架）—— L4
- TopicSuggestionAgent F2 练习前可选话题生成（conversation 任务，不落库）
- SentenceAnalysisAgent 句子精读（reasoning 任务，翻译 + 语法/用法讲解，不落库）
"""

from app.agents.base import (
    LLMNotConfiguredError,
    parse_json_object,
    resolve_task_llm,
)
from app.agents.error_analysis import AnalysisReport, ErrorAnalysisAgent
from app.agents.examiner import (
    ConverseResult,
    DetectedError,
    DimensionScore,
    ExaminerAgent,
    ExamResult,
)
from app.agents.leveling import BaselineResult, LevelingAgent
from app.agents.memory_word import (
    JudgeResult,
    MemoryWordAgent,
    Passage,
    WordCheck,
)
from app.agents.sentence_analysis import (
    LearningPoint,
    LexicalNote,
    RewriteOption,
    SentenceAnalysis,
    SentenceAnalysisAgent,
)
from app.agents.tokenizer_agent import CollectItem, TokenizerAgent
from app.agents.topic_suggestion import SuggestedTopic, TopicSuggestionAgent
from app.agents.tutor import Correction, TutorAgent, TutorTurn

__all__ = [
    "LLMNotConfiguredError",
    "parse_json_object",
    "resolve_task_llm",
    "LevelingAgent",
    "BaselineResult",
    "TokenizerAgent",
    "CollectItem",
    "MemoryWordAgent",
    "JudgeResult",
    "Passage",
    "WordCheck",
    "ExaminerAgent",
    "ExamResult",
    "ConverseResult",
    "DimensionScore",
    "DetectedError",
    "ErrorAnalysisAgent",
    "AnalysisReport",
    "TutorAgent",
    "TutorTurn",
    "Correction",
    "TopicSuggestionAgent",
    "SuggestedTopic",
    "SentenceAnalysisAgent",
    "SentenceAnalysis",
    "LearningPoint",
    "LexicalNote",
    "RewriteOption",
]
