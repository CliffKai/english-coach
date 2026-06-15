"""Agent 编排层（docs/02 五个 Agent）。

Agent 是「功能逻辑」的归属地：编排 L1 适配器（LLM/存储）+ L2 服务（切词/调度），
把确定性预处理与 LLM 判断粘合成一个功能。业务路由（app.api）只调用 Agent，不直接
碰适配器细节。

L3 落地三个（按 07 严格顺序）：
- LevelingAgent      水平基线分级（scoring 任务，写 Settings.level_baseline）—— 先于 F1/F2
- TokenizerAgent     F1 生词收集（复用 L2 SpacyTokenizer，确定性切词+过滤+查重入库）
- MemoryWordAgent    F3a 理解式背词（reasoning 任务，判断复述理解 → 映射 FSRS 评级，ADR-011）

TutorAgent / ExaminerAgent / ErrorAnalysisAgent 属 F2/L4，后续层落地。
"""

from app.agents.base import (
    LLMNotConfiguredError,
    parse_json_object,
    resolve_task_llm,
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
]
