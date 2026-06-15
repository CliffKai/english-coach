"""Agent 编排层（docs/02 五个 Agent）。

Agent 是「功能逻辑」的归属地：编排 L1 适配器（LLM/存储）+ L2 服务（切词/调度），
把确定性预处理与 LLM 判断粘合成一个功能。业务路由（app.api）只调用 Agent，不直接
碰适配器细节。

L3 落地五个（按 07 严格顺序）：
- LevelingAgent       水平基线分级（scoring 任务，写 Settings.level_baseline）—— 先于 F1/F2
- TokenizerAgent      F1 生词收集（复用 L2 SpacyTokenizer，确定性切词+过滤+查重入库）
- MemoryWordAgent     F3a 理解式背词（reasoning 任务，判断复述理解 → 映射 FSRS 评级，ADR-011）
- ExaminerAgent       F2c 自由写作打分（scoring 任务，考试模式延迟纠错 + 多维度打分）
- ErrorAnalysisAgent  F2 收尾（reasoning 任务，buffer → 错题本 + 模式识别复盘）—— 紧跟 Examiner

TutorAgent 属 F2a/2b（练习模式即时纠错），L4 落地。
"""

from app.agents.base import (
    LLMNotConfiguredError,
    parse_json_object,
    resolve_task_llm,
)
from app.agents.error_analysis import AnalysisReport, ErrorAnalysisAgent
from app.agents.examiner import (
    DetectedError,
    DimensionScore,
    ExaminerAgent,
    ExamResult,
)
from app.agents.leveling import BaselineResult, LevelingAgent
from app.agents.memory_word import JudgeResult, MemoryWordAgent
from app.agents.tokenizer_agent import CollectItem, TokenizerAgent

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
    "ExaminerAgent",
    "ExamResult",
    "DimensionScore",
    "DetectedError",
    "ErrorAnalysisAgent",
    "AnalysisReport",
]
