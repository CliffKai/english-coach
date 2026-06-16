"""ExaminerAgent —— 考试模式（延迟纠错）：F2c 自由写作打分 + F2d 对话打分。

流程（docs/01 功能2 / docs/02 延迟纠错机制，ADR-005）：
  考试模式下，用户自由表达（零脚手架、不救场、不打断）。
  - F2c（free_write）：单轮提交整篇 → 一次性打分 + 错误 buffer。
  - F2d（dialogue，L4）：多轮口语对话，每轮 converse() 只回自然对话（不纠错、不提示，
    ADR-005 零脚手架）；用户「完成/提前交卷」后，对累积的用户话语整体 score()。
  两者结算都走同一条链：score() 产「维度分 + 隐藏错误 buffer」→ 紧跟交 ErrorAnalysisAgent
  转 ErrorEntry 回填错题本 + 产复盘（07 红线：buffer 临时，产出即消费，本 Agent 不持久化）。

为什么打分与错误检测合在一次 LLM 调用：两者都要通读全文，分开调是双倍成本与
双倍方差。dimensions 的「分数」由 LLM 给，但**综合分（overall）在 Python 里按规则
确定性地从各维度算出**，不让 LLM 算聚合——降低同篇两次打分飘动（07 可信度风险）。

可信度（07 已知风险）：LLM 评分方差大，对策：
- 固定 rubric（雅思 band / 托福 0–5 锚点描述）锚定判断；
- 零温度（temperature=0）求稳；
- 结果一律标 estimated=True，UI 须明示「AI 估算，仅供参考」；
- overall 确定性计算，不交给 LLM。

口语（F2d）的**发音/流利度维度**：默认无发音评估 API 时**空缺并标注「未接入发音评估」**
（不拿文本假评，ADR-013）；overall 只对有分的维度求均值，不让空缺维度把综合分拖低。
配了发音评估 API（PronunciationProvider 返回 estimated=False）则据其结果填这些维度。
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel

from app.adapters.llm import ChatMessage, LLMProvider, Role
from app.adapters.speech import PronunciationResult
from app.agents.base import parse_json_object
from app.models import ErrorType, PracticeMode, ScoringStandard

# ── 维度集（key 稳定，供前端/复盘对齐；label 给用户看）──────────────
# 写作：雅思 Task 2 四维（0–9 band）；托福独立写作 rubric 三维（0–5）。
_IELTS_WRITING_DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("task_response", "任务回应 Task Response"),
    ("coherence_cohesion", "连贯与衔接 Coherence & Cohesion"),
    ("lexical_resource", "词汇丰富度 Lexical Resource"),
    ("grammatical_range_accuracy", "语法多样性与准确性 Grammatical Range & Accuracy"),
)
_TOEFL_WRITING_DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("development", "论述充分性 Development"),
    ("organization", "组织结构 Organization"),
    ("language_use", "语言运用 Language Use"),
)
# 口语：雅思 Speaking 四维（0–9 band）；托福口语 rubric（沿用本项目 0–5 内部刻度）。
_IELTS_SPEAKING_DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("fluency_coherence", "流利与连贯 Fluency & Coherence"),
    ("lexical_resource", "词汇丰富度 Lexical Resource"),
    ("grammatical_range_accuracy", "语法多样性与准确性 Grammatical Range & Accuracy"),
    ("pronunciation", "发音 Pronunciation"),
)
_TOEFL_SPEAKING_DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("delivery", "表达流畅度 Delivery"),
    ("language_use", "语言运用 Language Use"),
    ("topic_development", "话题展开 Topic Development"),
)

# 声学依赖维度（发音/流利度类）：文本评不了，须靠发音评估 API（ADR-013）。
# 无真实评估时这些维度空缺并标注；不拿文本假评、也不据时间戳编造分数（仅时间戳进复盘）。
_ACOUSTIC_DIM_KEYS = frozenset({"pronunciation", "fluency_coherence", "delivery"})
_NO_PRON_COMMENT = "未接入发音评估，无此项评分（ADR-013）。"

# 各标准的分制（min, max, 取整步长）。overall 据此确定性计算。
_SCALE: dict[ScoringStandard, tuple[float, float, float]] = {
    ScoringStandard.IELTS: (0.0, 9.0, 0.5),  # band，四舍五入到 0.5
    # 独立写作/口语 rubric 0–5（官方再缩放到 0–30/0–4，属展示层/阶段2）。
    ScoringStandard.TOEFL: (0.0, 5.0, 0.5),
}

# 固定 rubric：锚定 LLM 判断，减少同篇两次评分飘动（07 可信度风险对策）。
_IELTS_WRITING_RUBRIC = """雅思写作评分锚点（0–9 band，每 0.5 一档）：
- 任务回应：是否切题、立场清晰、论证充分、有具体例证。
- 连贯与衔接：段落与逻辑是否清楚，衔接手段是否自然准确。
- 词汇丰富度：用词是否多样准确地道，搭配是否得体，拼写是否规范。
- 语法多样性与准确性：句式是否多样，时态/主谓/冠词等是否准确。
band 参照：5≈能表达但错误多影响理解；6≈基本清楚偶有错误；7≈清楚准确错误少；8≈娴熟少误。"""

_TOEFL_WRITING_RUBRIC = """托福独立写作评分锚点（0–5）：
- 论述充分性：观点是否展开、例证是否具体相关。
- 组织结构：是否结构连贯、过渡自然、逻辑递进。
- 语言运用：句式与词汇是否多样准确，语法/用词错误是否影响表达。
分档参照：3≈表达清楚但有明显错误或展开不足；4≈展开较好用词较准偶有错误；5≈展开充分语言娴熟。"""

_IELTS_SPEAKING_RUBRIC = """雅思口语评分锚点（0–9 band，每 0.5 一档）：
- 流利与连贯：语流是否顺畅、有无频繁卡顿、逻辑衔接是否自然（基于转写与停顿信号）。
- 词汇丰富度：口语用词是否多样准确，能否自然转述。
- 语法多样性与准确性：句式是否多样，口语语法是否准确。
- 发音：音准、语调、可懂度（须发音评估，无则空缺）。
band 参照：5≈能交流但卡顿/错误多；6≈基本流畅偶有错误；7≈流畅清楚错误少；8≈自然娴熟。"""

_TOEFL_SPEAKING_RUBRIC = """托福口语评分锚点（0–5）：
- 表达流畅度：语流、节奏、清晰度（须发音评估，无则空缺）。
- 语言运用：语法与词汇是否准确多样。
- 话题展开：回应是否切题、内容是否充分连贯。
分档参照：3≈可理解但有明显问题；4≈较流畅较准确；5≈流畅准确内容充分。"""

# 写作模式（2c）允许的错误类型：排除 pronunciation（属口语 2d，写作出现即幻觉，丢弃）。
# 口语模式（2d，L4）允许全部类型。按 mode 决定，见 _allowed_error_types。
_WRITING_ERROR_TYPES = {t.value for t in ErrorType if t is not ErrorType.PRONUNCIATION}
_ALL_ERROR_TYPES = {t.value for t in ErrorType}


def _is_speaking(mode: PracticeMode) -> bool:
    """口语模式（对话 / 引导口语）→ 用口语维度集与口语 rubric。"""
    return mode in (PracticeMode.DIALOGUE, PracticeMode.GUIDED_SPEAK)


def _allowed_error_types(mode: PracticeMode) -> set[str]:
    """该模式下合法的错误类型集合。写作排除 pronunciation；口语放行全部。"""
    return _ALL_ERROR_TYPES if _is_speaking(mode) else _WRITING_ERROR_TYPES


class DimensionScore(BaseModel):
    """单维度评分。

    score 为 None 表示**该维度空缺**——口语发音/流利度维度在无发音评估 API 时取此
    （不拿文本假评，ADR-013），estimated=True 标注「AI 估算 / 未评」。
    """

    key: str
    label: str
    score: float | None
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

    overall 在 Python 里确定性算出（不交给 LLM），只对**有分的维度**求均值（空缺维度不计）；
    estimated 恒 True（AI 估算，07 风险）。errors 即「延迟纠错 buffer」，本 Agent 不持久化，
    随后交 ErrorAnalysisAgent 消费。
    """

    standard: ScoringStandard
    dimensions: list[DimensionScore]
    overall: float | None  # 综合分（雅思 band / 托福 0–5）；无有效维度分时 None
    errors: list[DetectedError]
    estimated: bool = True


class ConverseResult(BaseModel):
    """F2d 对话单轮产出：仅自然对话回复（驱动 TTS）。

    考试模式零脚手架（ADR-005）：本轮**不纠错、不提示、不打分**，只把对话推进下去。
    错误检测与打分一律延迟到「提交」时对累积话语整体进行（score()）。
    """

    reply: str


class ExaminerAgent:
    """考试模式打分 + 错误检测（F2c/F2d）。LLM 由功能层按任务解析后注入（ADR-006）：
    打分走 scoring 档（要准要稳），对话单轮回话走 conversation 档（量大、性价比）。"""

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
        pronunciation: PronunciationResult | None = None,
    ) -> ExamResult:
        """对全文/全程话语打分 + 检测错误（一次 LLM 调用）。空文本不烧 token，回零分空 buffer。

        mode：free_write（2c 写作）/ dialogue（2d 口语）。口语用口语维度集，且发音/流利度
          维度按 pronunciation 处理（无真实评估则空缺并标注，ADR-013）。
        topic/target_band/baseline：评分上下文（切题度参照、目标分对照、水平基线）。
        pronunciation：发音评估结果。estimated=False（真实评估）时据其填发音/流利度维度；
          None 或 estimated=True（NoneAdapter）则这些维度空缺。
        """
        dims_spec = _dimensions_for(standard, mode)
        if not text or not text.strip():
            # 提前交卷且无内容（ADR-005 允许提前交卷，但空内容只能给最低分/空缺）。
            empty = _empty_dimensions(dims_spec, standard, mode, pronunciation)
            return ExamResult(
                standard=standard,
                dimensions=empty,
                overall=_overall(empty, standard),
                errors=[],
            )

        # 只问 LLM 文本可评的维度（声学维度由 Python 据发音评估填/空缺，不让 LLM 假评）。
        text_dims = [(k, lbl) for k, lbl in dims_spec if k not in _ACOUSTIC_DIM_KEYS]
        resp = await self._llm.chat(
            [
                ChatMessage(role=Role.SYSTEM, content=_system_prompt(standard, mode)),
                ChatMessage(
                    role=Role.USER,
                    content=_user_prompt(
                        text.strip(),
                        text_dims,
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
            resp.content,
            standard=standard,
            dims_spec=dims_spec,
            mode=mode,
            pronunciation=pronunciation,
        )

    async def converse(
        self,
        message: str,
        *,
        history: Iterable[ChatMessage] = (),
        topic: str | None = None,
        baseline: str | None = None,
    ) -> ConverseResult:
        """F2d 对话单轮：据历史 + 用户本轮话语，回一句自然对话（驱动 TTS）。

        零脚手架（ADR-005）：绝不纠错、不提示、不打分——只自然交流、追问以引出更多表达。
        history：既往轮次（user/assistant 已映射好的 ChatMessage 序列）。
        """
        messages = [ChatMessage(role=Role.SYSTEM, content=_converse_system(topic, baseline))]
        messages.extend(history)
        messages.append(ChatMessage(role=Role.USER, content=message))
        resp = await self._llm.chat(messages, temperature=0.7, max_tokens=300)
        return ConverseResult(reply=resp.content.strip())

    @staticmethod
    def _parse(
        content: str,
        *,
        standard: ScoringStandard,
        dims_spec: tuple[tuple[str, str], ...],
        mode: PracticeMode,
        pronunciation: PronunciationResult | None,
    ) -> ExamResult:
        """解析 LLM 输出。缺维度/越界分一律夹取或回落；声学维度据发音评估填/空缺；
        overall 在此确定性计算（只算有分维度）。"""
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
            if key in _ACOUSTIC_DIM_KEYS:
                dimensions.append(_acoustic_dimension(key, label, standard, pronunciation))
                continue
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
        overall = _overall(dimensions, standard)
        return ExamResult(
            standard=standard, dimensions=dimensions, overall=overall, errors=errors
        )


# ── 提示词与解析辅助 ────────────────────────────────────────────────
def _dimensions_for(
    standard: ScoringStandard, mode: PracticeMode
) -> tuple[tuple[str, str], ...]:
    if _is_speaking(mode):
        return (
            _IELTS_SPEAKING_DIMENSIONS
            if standard is ScoringStandard.IELTS
            else _TOEFL_SPEAKING_DIMENSIONS
        )
    return (
        _IELTS_WRITING_DIMENSIONS
        if standard is ScoringStandard.IELTS
        else _TOEFL_WRITING_DIMENSIONS
    )


def _rubric_for(standard: ScoringStandard, mode: PracticeMode) -> str:
    if _is_speaking(mode):
        return (
            _IELTS_SPEAKING_RUBRIC
            if standard is ScoringStandard.IELTS
            else _TOEFL_SPEAKING_RUBRIC
        )
    return (
        _IELTS_WRITING_RUBRIC if standard is ScoringStandard.IELTS else _TOEFL_WRITING_RUBRIC
    )


def _empty_dimensions(
    dims_spec: tuple[tuple[str, str], ...],
    standard: ScoringStandard,
    mode: PracticeMode,
    pronunciation: PronunciationResult | None,
) -> list[DimensionScore]:
    """空作答（提前交卷无内容）：文本维度给最低分，声学维度按发音评估填/空缺。"""
    lo = _SCALE[standard][0]
    out: list[DimensionScore] = []
    for key, label in dims_spec:
        if key in _ACOUSTIC_DIM_KEYS:
            out.append(_acoustic_dimension(key, label, standard, pronunciation))
        else:
            out.append(DimensionScore(key=key, label=label, score=lo, comment="未作答。"))
    return out


def _acoustic_dimension(
    key: str,
    label: str,
    standard: ScoringStandard,
    pronunciation: PronunciationResult | None,
) -> DimensionScore:
    """发音/流利度类维度：有真实评估则据其填分；否则空缺并标注（ADR-013）。"""
    mapped = _map_pronunciation(key, standard, pronunciation)
    if mapped is not None:
        return DimensionScore(
            key=key, label=label, score=mapped, comment="基于发音评估。", estimated=False
        )
    return DimensionScore(
        key=key, label=label, score=None, comment=_NO_PRON_COMMENT, estimated=True
    )


def _map_pronunciation(
    key: str, standard: ScoringStandard, pronunciation: PronunciationResult | None
) -> float | None:
    """把真实发音评估（0–100）映射到该标准刻度。无真实评估（None/estimated）→ None（空缺）。"""
    if pronunciation is None or pronunciation.estimated:
        return None
    # 发音维度取 accuracy；流利度类（fluency_coherence/delivery）取 fluency。
    raw = pronunciation.accuracy if key == "pronunciation" else pronunciation.fluency
    if raw is None:
        return None
    lo, hi, step = _SCALE[standard]
    return _round_to_step(lo + (hi - lo) * max(0.0, min(100.0, raw)) / 100.0, step)


def _system_prompt(standard: ScoringStandard, mode: PracticeMode) -> str:
    rubric = _rubric_for(standard, mode)
    sample = "口语对话转写" if _is_speaking(mode) else "英文写作"
    return (
        f"你是严格、稳定、可校准的英语{'口语' if _is_speaking(mode) else '写作'}考官。"
        f"依据给定 rubric 为学习者的{sample}逐维度打分，并把全部语言错误结构化标注出来"
        "（延迟纠错：此处只标注、不在分数外额外说教）。母语中文的学习者，所有 "
        "comment/explanation 用中文。只输出 JSON，不要任何前后缀说明。\n\n" + rubric
    )


def _user_prompt(
    text: str,
    text_dims: list[tuple[str, str]],
    *,
    mode: PracticeMode,
    topic: str | None,
    target_band: float | None,
    baseline: str | None,
) -> str:
    dim_lines = "\n".join(f'  - "{k}"：{lbl}' for k, lbl in text_dims)
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
    speaking = _is_speaking(mode)
    body_label = "学习者口语转写（多轮对话，仅评学习者话语）" if speaking else "学习者写作"
    acoustic_note = (
        "注意：发音/流利度维度由系统另行处理，**不要**在此评发音或语流，只评所列维度。\n"
        if speaking
        else ""
    )
    return (
        f"{ctx}"
        f"{body_label}：\n{text}\n\n"
        f"{acoustic_note}"
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


def _converse_system(topic: str | None, baseline: str | None) -> str:
    """F2d 对话回话的 system 提示：自然交流、零纠错、追问引出表达（ADR-005）。"""
    topic_line = f"本次对话话题：{topic}。\n" if topic else ""
    base_line = f"学习者英语水平约 {baseline}（CEFR），用词难度适配。\n" if baseline else ""
    return (
        "You are a friendly, encouraging IELTS speaking examiner having a natural English "
        "conversation with a Chinese learner. Speak only English. Keep each reply short "
        "(1-3 sentences) and end with an open follow-up question to keep the learner talking. "
        "This is EXAM mode with deferred correction: NEVER correct their mistakes, NEVER give "
        "hints, tips, vocabulary, or feedback — just converse naturally. Do not break "
        "character or mention scoring.\n" + topic_line + base_line
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


def _overall(dimensions: list[DimensionScore], standard: ScoringStandard) -> float | None:
    """综合分 = **有分维度**的均值，按该标准步长取整（确定性，不交给 LLM）。

    空缺维度（发音/流利度无评估，score=None）不计入——否则会把综合分错误拖低（ADR-013）。
    全部维度都空缺时返回 None。
    """
    scored = [d.score for d in dimensions if d.score is not None]
    if not scored:
        return None
    lo, hi, step = _SCALE[standard]
    return _round_to_step(sum(scored) / len(scored), step)


def _round_to_step(value: float, step: float) -> float:
    """把 value 四舍五入到最近的 step 倍数，**逢半向上**（half-up）。

    不能用内置 round()：它是「银行家舍入」（round-half-to-even），会把 6.25→6.0、
    雅思半档 x.x5 该进的不进，与 rubric/雅思 band「逢半进位」不符。用 Decimal 显式
    ROUND_HALF_UP，并以字符串构造 Decimal 规避二进制浮点误差（如 0.1 的不精确表示）。
    """
    quotient = Decimal(str(value)) / Decimal(str(step))
    rounded = quotient.to_integral_value(rounding=ROUND_HALF_UP)
    return float(rounded * Decimal(str(step)))
