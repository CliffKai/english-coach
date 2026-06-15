"""ExaminerAgent —— F2c 自由写作打分（L3 第 4 步，考试模式，产出 ErrorEntry 喂错题本）。

流程（docs/01 功能2 / docs/02 延迟纠错机制，ADR-005）：
  考试模式下，用户自由写作（零脚手架、不救场、不打断）→ 点「完成/提前交卷」后，
  本 Agent **一次性**对全文做两件事：
    ① 多维度打分（雅思/托福各维度，按 Settings.scoring_standard）
    ② 把检测到的错误标注进一个**结构化 buffer**（隐藏，不当场逐条纠正）
  buffer 随后交给 ErrorAnalysisAgent 产复盘 + 回填错题本（紧跟本步，07 红线：
  buffer 是临时的，产出即消费，本 Agent 不持久化 buffer）。

为什么打分与错误检测合在一次 LLM 调用：两者都要通读全文，分开调是双倍成本与
双倍方差。dimensions 的「分数」由 LLM 给，但**综合分（overall）在 Python 里按规则
确定性地从各维度算出**，不让 LLM 算聚合——降低同篇两次打分飘动（07 可信度风险）。

可信度（07 已知风险）：LLM 评分方差大，对策：
- 固定 rubric（雅思 band / 托福 0–5 锚点描述）锚定判断；
- 零温度（temperature=0）求稳；
- 结果一律标 estimated=True，UI 须明示「AI 估算，仅供参考」；
- overall 确定性计算，不交给 LLM。
口语模式（2d，L4）的发音/流利度维度无 Azure 时标 estimated=True（ADR-003）；
写作（2c）无此两维，estimated 仅承载整体「AI 估算」语义。
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel

from app.adapters.llm import ChatMessage, LLMProvider, Role
from app.agents.base import parse_json_object
from app.models import ErrorType, PracticeMode, ScoringStandard

# 各标准的写作维度（key 稳定，供前端/复盘对齐；label 给用户看）。
# 雅思写作 Task 2 四维，0–9 band；托福独立写作 rubric 三维，0–5。
_IELTS_DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("task_response", "任务回应 Task Response"),
    ("coherence_cohesion", "连贯与衔接 Coherence & Cohesion"),
    ("lexical_resource", "词汇丰富度 Lexical Resource"),
    ("grammatical_range_accuracy", "语法多样性与准确性 Grammatical Range & Accuracy"),
)
_TOEFL_DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("development", "论述充分性 Development"),
    ("organization", "组织结构 Organization"),
    ("language_use", "语言运用 Language Use"),
)

# 各标准的分制（min, max, 取整步长）。overall 据此确定性计算。
_SCALE: dict[ScoringStandard, tuple[float, float, float]] = {
    ScoringStandard.IELTS: (0.0, 9.0, 0.5),  # band，四舍五入到 0.5
    # 独立写作 rubric 0–5（官方再缩放到 0–30，属展示层/阶段2）。
    ScoringStandard.TOEFL: (0.0, 5.0, 0.5),
}

# 固定 rubric：锚定 LLM 判断，减少同篇两次评分飘动（07 可信度风险对策）。
_IELTS_RUBRIC = """雅思写作评分锚点（0–9 band，每 0.5 一档）：
- 任务回应：是否切题、立场清晰、论证充分、有具体例证。
- 连贯与衔接：段落与逻辑是否清楚，衔接手段是否自然准确。
- 词汇丰富度：用词是否多样准确地道，搭配是否得体，拼写是否规范。
- 语法多样性与准确性：句式是否多样，时态/主谓/冠词等是否准确。
band 参照：5≈能表达但错误多影响理解；6≈基本清楚偶有错误；7≈清楚准确错误少；8≈娴熟少误。"""

_TOEFL_RUBRIC = """托福独立写作评分锚点（0–5）：
- 论述充分性：观点是否展开、例证是否具体相关。
- 组织结构：是否结构连贯、过渡自然、逻辑递进。
- 语言运用：句式与词汇是否多样准确，语法/用词错误是否影响表达。
分档参照：3≈表达清楚但有明显错误或展开不足；4≈展开较好用词较准偶有错误；5≈展开充分语言娴熟。"""

# 写作模式（2c）允许的错误类型：排除 pronunciation（属口语 2d，写作出现即幻觉，丢弃）。
# 口语模式（2d，L4 复用本 Agent）允许全部类型。按 mode 决定，见 _allowed_error_types。
_WRITING_ERROR_TYPES = {t.value for t in ErrorType if t is not ErrorType.PRONUNCIATION}
_ALL_ERROR_TYPES = {t.value for t in ErrorType}


def _allowed_error_types(mode: PracticeMode) -> set[str]:
    """该模式下合法的错误类型集合。写作排除 pronunciation；口语（dialogue）放行全部。"""
    return _ALL_ERROR_TYPES if mode is PracticeMode.DIALOGUE else _WRITING_ERROR_TYPES


class DimensionScore(BaseModel):
    """单维度评分。estimated 仅用于口语无 Azure 时的发音/流利度维度（ADR-003），写作恒 False。"""

    key: str
    label: str
    score: float
    comment: str = ""  # 中文简评，1 句
    estimated: bool = False


class DetectedError(BaseModel):
    """检测到的一条错误（隐藏 buffer 的元素，交给 ErrorAnalysisAgent 回填错题本）。

    字段对齐 ErrorEntry 的可由 LLM 判定部分；session_id/topic 由功能层补齐后落库。
    """

    type: ErrorType
    original: str  # 用户原句/片段
    correction: str  # 修正后
    explanation: str = ""  # 中文解释
    severity: int = 1  # 1–3，越大越严重


class ExamResult(BaseModel):
    """ExaminerAgent 的产出：维度分 + 综合分 + 隐藏错误 buffer。

    overall 在 Python 里确定性算出（不交给 LLM）；estimated 恒 True（AI 估算，07 风险）。
    errors 即「延迟纠错 buffer」，本 Agent 不持久化，随后交 ErrorAnalysisAgent 消费。
    """

    standard: ScoringStandard
    dimensions: list[DimensionScore]
    overall: float | None  # 综合分（雅思 band / 托福 0–5）；无维度分时 None
    errors: list[DetectedError]
    estimated: bool = True


class ExaminerAgent:
    """F2c 考试模式打分 + 错误检测。LLM 由功能层按 scoring 任务解析后注入（ADR-006）。"""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def score(
        self,
        text: str,
        *,
        mode: PracticeMode = PracticeMode.FREE_WRITE,
        topic: str | None = None,
        standard: ScoringStandard = ScoringStandard.IELTS,
        target_band: float | None = None,
        baseline: str | None = None,
    ) -> ExamResult:
        """对全文打分 + 检测错误（一次 LLM 调用）。空文本不烧 token，回零分空 buffer。

        mode：当前仅 free_write（2c）落地；dialogue（2d）在 L4 复用本 Agent。
        topic/target_band/baseline：作为评分上下文（切题度参照、目标分对照、水平基线）。
        """
        dims_spec = _dimensions_for(standard)
        if not text or not text.strip():
            # 提前交卷且无内容（ADR-005 允许提前交卷，但空内容只能给最低分）。
            empty = [
                DimensionScore(key=k, label=lbl, score=_SCALE[standard][0], comment="未作答。")
                for k, lbl in dims_spec
            ]
            return ExamResult(
                standard=standard, dimensions=empty, overall=_SCALE[standard][0], errors=[]
            )

        resp = await self._llm.chat(
            [
                ChatMessage(role=Role.SYSTEM, content=_system_prompt(standard)),
                ChatMessage(
                    role=Role.USER,
                    content=_user_prompt(
                        text.strip(),
                        dims_spec,
                        mode=mode,
                        topic=topic,
                        target_band=target_band,
                        baseline=baseline,
                    ),
                ),
            ],
            temperature=0.0,  # 评分要稳：固定 rubric + 零温度
        )
        return self._parse(
            resp.content, standard=standard, dims_spec=dims_spec, mode=mode
        )

    @staticmethod
    def _parse(
        content: str,
        *,
        standard: ScoringStandard,
        dims_spec: tuple[tuple[str, str], ...],
        mode: PracticeMode,
    ) -> ExamResult:
        """解析 LLM 输出。缺维度/越界分一律夹取或回落；overall 在此确定性计算。"""
        try:
            obj = parse_json_object(content)
        except ValueError:
            obj = {}

        lo, hi, step = _SCALE[standard]
        raw_dims = obj.get("dimensions")
        by_key = (
            {str(d.get("key", "")): d for d in raw_dims if isinstance(d, dict)}
            if isinstance(raw_dims, list)
            else {}
        )
        dimensions: list[DimensionScore] = []
        for key, label in dims_spec:
            d = by_key.get(key, {})
            dimensions.append(
                DimensionScore(
                    key=key,
                    label=label,
                    score=_clamp_round(d.get("score"), lo, hi, step),
                    comment=str(d.get("comment", "")).strip(),
                )
            )

        errors = _parse_errors(obj.get("errors"), allowed=_allowed_error_types(mode))
        overall = _overall(dimensions, standard) if dimensions else None
        return ExamResult(
            standard=standard, dimensions=dimensions, overall=overall, errors=errors
        )


# ── 提示词与解析辅助 ────────────────────────────────────────────────
def _dimensions_for(standard: ScoringStandard) -> tuple[tuple[str, str], ...]:
    return _IELTS_DIMENSIONS if standard is ScoringStandard.IELTS else _TOEFL_DIMENSIONS


def _system_prompt(standard: ScoringStandard) -> str:
    rubric = _IELTS_RUBRIC if standard is ScoringStandard.IELTS else _TOEFL_RUBRIC
    return (
        "你是严格、稳定、可校准的英语写作考官。依据给定 rubric 为学习者的英文写作"
        "逐维度打分，并把全部语言错误结构化标注出来（延迟纠错：此处只标注、不在分数外"
        "额外说教）。母语中文的学习者，所有 comment/explanation 用中文。"
        "只输出 JSON，不要任何前后缀说明。\n\n" + rubric
    )


def _user_prompt(
    text: str,
    dims_spec: tuple[tuple[str, str], ...],
    *,
    mode: PracticeMode,
    topic: str | None,
    target_band: float | None,
    baseline: str | None,
) -> str:
    dim_lines = "\n".join(f'  - "{k}"：{lbl}' for k, lbl in dims_spec)
    ctx = ""
    if topic:
        ctx += f"话题：{topic}\n"
    if baseline:
        ctx += f"学习者水平基线（CEFR）：{baseline}\n"
    if target_band is not None:
        ctx += f"学习者目标分：{target_band}\n"
    allowed = _allowed_error_types(mode)
    types = " | ".join(sorted(allowed))
    pron_hint = (
        "" if ErrorType.PRONUNCIATION.value in allowed else "（不要用 pronunciation，那属口语）"
    )
    return (
        f"{ctx}"
        f"学习者写作：\n{text}\n\n"
        "请输出 JSON：\n"
        "{\n"
        '  "dimensions": [\n'
        '    {"key": "<维度key>", "score": <数字>, "comment": "<中文简评1句>"}\n'
        "  ],\n"
        '  "errors": [\n'
        '    {"type": "<类型>", "original": "<原句片段>", "correction": "<修正>", '
        '"explanation": "<中文解释>", "severity": <1-3>}\n'
        "  ]\n"
        "}\n"
        "维度 key 必须且仅为以下各项（逐一给分）：\n"
        f"{dim_lines}\n"
        f"错误 type 取值：{types}{pron_hint}。\n"
        "不要给综合分（系统会按维度分自动计算）。错误尽量找全，找不到则 errors 为空数组。"
    )


def _parse_errors(raw, *, allowed: set[str]) -> list[DetectedError]:
    """解析错误 buffer；非法/缺字段的条目跳过，类型不在 allowed 内跳过（不污染错题本）。"""
    if not isinstance(raw, list):
        return []
    out: list[DetectedError] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        etype = str(item.get("type", "")).strip().lower()
        original = str(item.get("original", "")).strip()
        correction = str(item.get("correction", "")).strip()
        # type 不在该模式允许集合，或缺核心内容（原句/修正）→ 跳过，宁缺毋滥。
        if etype not in allowed or not original or not correction:
            continue
        out.append(
            DetectedError(
                type=ErrorType(etype),
                original=original,
                correction=correction,
                explanation=str(item.get("explanation", "")).strip(),
                severity=_clamp_severity(item.get("severity")),
            )
        )
    return out


def _clamp_round(value, lo: float, hi: float, step: float) -> float:
    """把 LLM 给的分夹到 [lo,hi] 并按 step 取整；非数字回落 lo。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return lo
    v = max(lo, min(hi, v))
    return _round_to_step(v, step)


def _clamp_severity(value) -> int:
    try:
        return max(1, min(3, int(value)))
    except (TypeError, ValueError):
        return 1


def _overall(dimensions: list[DimensionScore], standard: ScoringStandard) -> float:
    """综合分 = 各维度均值，按该标准的步长取整（确定性，不交给 LLM）。"""
    lo, hi, step = _SCALE[standard]
    mean = sum(d.score for d in dimensions) / len(dimensions)
    return _round_to_step(mean, step)


def _round_to_step(value: float, step: float) -> float:
    """把 value 四舍五入到最近的 step 倍数，**逢半向上**（half-up）。

    不能用内置 round()：它是「银行家舍入」（round-half-to-even），会把 6.25→6.0、
    雅思半档 x.x5 该进的不进，与 rubric/雅思 band「逢半进位」不符。用 Decimal 显式
    ROUND_HALF_UP，并以字符串构造 Decimal 规避二进制浮点误差（如 0.1 的不精确表示）。
    """
    quotient = Decimal(str(value)) / Decimal(str(step))
    rounded = quotient.to_integral_value(rounding=ROUND_HALF_UP)
    return float(rounded * Decimal(str(step)))
