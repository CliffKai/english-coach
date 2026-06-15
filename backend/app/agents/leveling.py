"""LevelingAgent —— 水平基线分级（L3 第 1 步，07 红线：基线先于 F1/F2）。

首次使用让用户写一小段英文，用 scoring 档模型估算 CEFR 等级（并给估算雅思分），
写入 Settings.level_baseline。此后 F1 过滤（切词 cutoff）与 F2 打分都参照它。

可信度（07 已知风险）：LLM 评级方差大，故
- 用固定 rubric（CEFR 六级描述）锚定判断，降低发挥空间；
- 结果一律标 estimated=True，UI 须明示「AI 估算，仅供参考」，可被用户手动覆盖。
"""

from __future__ import annotations

from pydantic import BaseModel

from app.adapters.llm import ChatMessage, LLMProvider, Role
from app.agents.base import parse_json_object

# CEFR 六级，存进 Settings.level_baseline 的合法值（与 tokenizer._CEFR_CUTOFF 对齐）。
CEFR_LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")

# 固定 rubric：锚定 LLM 判断，减少同一文本两次评级飘动（07 可信度风险的对策之一）。
_RUBRIC = """CEFR 六级写作水平锚点：
- A1 入门：仅能写孤立短句，词汇极有限，基础语法频繁出错。
- A2 初级：能写简单连句描述熟悉话题，常见时态有错，词汇基础。
- B1 中级：能就熟悉话题写连贯短文，结构简单，错误不妨碍理解。
- B2 中高：能写清晰详细的文章，论证较完整，用词较准，偶有错误。
- C1 高级：能写结构良好的复杂文章，灵活准确，错误少且细微。
- C2 精通：接近母语者，表达精准地道，几乎无误。"""

_SYSTEM = (
    "你是严格、稳定的英语水平评估专家。依据给定 CEFR rubric 评估学习者的英文写作样本，"
    "只输出 JSON，不要任何解释性前后缀。母语中文的学习者，rationale 用中文。\n\n" + _RUBRIC
)

# 估算雅思分（用于 Settings 展示/目标对照）。粗映射，与 tokenizer 的反向折算保持同一刻度。
_CEFR_TO_BAND: dict[str, float] = {
    "A1": 3.0,
    "A2": 3.5,
    "B1": 4.5,
    "B2": 6.0,
    "C1": 7.0,
    "C2": 8.5,
}

# 默认写作提示题（首次分级用）。话题中性、便于自由发挥，约 80–120 词。
DEFAULT_PROMPT = (
    "Describe a place you enjoy spending time in, and explain why it appeals to you. "
    "Write about 80–120 words in English."
)


class BaselineResult(BaseModel):
    """分级结果。baseline 为 CEFR 码（写入 Settings.level_baseline）。"""

    baseline: str  # CEFR：A1..C2
    estimated_band: float | None = None  # 估算雅思分（展示用）
    rationale: str = ""  # 评级理由（中文，给用户看）
    estimated: bool = True  # 恒 True：AI 估算，仅供参考（07 可信度风险）


class LevelingAgent:
    """水平基线分级。LLM 由功能层按 scoring 任务解析后注入（ADR-006）。"""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    @staticmethod
    def default_prompt() -> str:
        """首次分级的写作题。L5 配置向导直接复用。"""
        return DEFAULT_PROMPT

    async def assess(self, sample: str, *, prompt: str | None = None) -> BaselineResult:
        """据写作样本估算 CEFR 基线。空样本回落 B1（默认档），不烧 token。"""
        if not sample or not sample.strip():
            return BaselineResult(
                baseline="B1",
                estimated_band=_CEFR_TO_BAND["B1"],
                rationale="未提供样本，回落默认中级（B1）。建议补做分级或在设置中手动调整。",
            )

        user = (
            (f"写作题目：{prompt}\n\n" if prompt else "")
            + f"学习者写作样本：\n{sample.strip()}\n\n"
            "请评估其 CEFR 等级，输出 JSON：\n"
            '{"baseline": "<A1|A2|B1|B2|C1|C2>", "rationale": "<中文简评，1-2 句>"}'
        )
        resp = await self._llm.chat(
            [
                ChatMessage(role=Role.SYSTEM, content=_SYSTEM),
                ChatMessage(role=Role.USER, content=user),
            ],
            temperature=0.0,  # 评级要稳：固定 rubric + 零温度，降低两次评级飘动
        )
        return self._parse(resp.content)

    @staticmethod
    def _parse(content: str) -> BaselineResult:
        """解析 LLM 输出；非法等级回落 B1，保证总能给出可用基线。"""
        try:
            obj = parse_json_object(content)
        except ValueError:
            obj = {}
        level = str(obj.get("baseline", "")).strip().upper()
        if level not in CEFR_LEVELS:
            level = "B1"
        return BaselineResult(
            baseline=level,
            estimated_band=_CEFR_TO_BAND[level],
            rationale=str(obj.get("rationale", "")).strip(),
        )
