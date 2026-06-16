"""MemoryWordAgent —— F3 理解式背词（消费 F1 生词 + L2 FSRS 队列）。

两个分支（docs/01 功能3，ADR-004：意思不该被存储，应在复习时被重新理解出来）：

F3a 逐词理解背（L3）：给出**来源句**，问「这个词在这句里你理解是什么意思」，用户用自己
  的话说 → LLM 判断理解是否到位 —— **不比对标准释义**（来源句本身就是消歧钥匙）。
  核心难点（07 已知风险）：开放式判断 vs FSRS 离散评级（again/hard/good/easy），映射规则
  定为 ADR-011：LLM 输出 verdict ∈ {correct, partial, wrong} + 可选 too_easy，映射：
    too_easy=True             → EASY  （用户表示太简单/秒答）
    correct                   → GOOD
    partial                   → HARD  （沾边但不准/漏义/犹豫）
    wrong / 空答 / 无关        → AGAIN
  判分只看「是否抓住该语境下的意思」，不苛求措辞精确（理解式，非默写）。

F3b 语境造句背（L4）：用**一批生词**造一段短文（贴近用户话题）→ 用户大致翻译 → 在语境中
  检验对每个生词的理解（make_passage + check_translation）。同样不比对标准释义：检验的是
  「在这段语境里是否把每个词的意思理解对了」，而非翻译措辞是否精确。
"""

from __future__ import annotations

from pydantic import BaseModel

from app.adapters.llm import ChatMessage, LLMProvider, Role
from app.agents.base import parse_json_object
from app.scheduling import ReviewRating

# verdict → FSRS 评级（ADR-011）。too_easy 优先级最高，在 judge() 里单独处理。
_VERDICT_TO_RATING: dict[str, ReviewRating] = {
    "correct": ReviewRating.GOOD,
    "partial": ReviewRating.HARD,
    "wrong": ReviewRating.AGAIN,
}

_PASSAGE_SYSTEM = (
    "你在帮助母语为中文的学习者做「语境造句背词」。请用给定的一批英文目标词写一段自然、"
    "连贯的英文短文（4–7 句），让每个目标词在真实语境中出现。要求：\n"
    "- 尽量用上全部目标词；个别词实在不自然可省略，但要在 words_used 里如实列出实际用到的。\n"
    "- 难度适配学习者水平，句子自然地道，不要生硬堆砌。\n"
    "- 不要给中文翻译、不要给词义解释（理解由学习者翻译时重新建立，ADR-004）。\n"
    "只输出 JSON，不要多余文字。"
)

_CHECK_SYSTEM = (
    "你在检验母语为中文的学习者对一段英文短文的理解，重点是其中的若干**目标词**。"
    "给定短文、目标词、以及学习者的中文大致翻译。逐个目标词判断：在这段语境下，学习者"
    "是否理解对了这个词的意思。原则：\n"
    "- 这是理解式检验，不是精确翻译比对。只要该词在语境中的意思理解对，措辞不必精确。\n"
    "- 不比对任何标准译文/词典释义，只看是否抓住该语境下的实际含义。\n"
    "- 学习者译文没覆盖到某词、或理解明显错 → 该词判 wrong。\n"
    "只输出 JSON，不要多余文字。"
)

_SYSTEM = (
    "你在帮助母语为中文的学习者做「理解式」单词复习。给定一个英文单词、它的若干来源句、"
    "以及学习者用自己的话说出的理解。请判断：在这些来源句的语境下，学习者是否抓住了这个词的意思。\n"
    "重要原则：\n"
    "- 这是理解式复习，不是默写。只要意思对，措辞不必精确，中英文表达皆可。\n"
    "- 不比对任何「标准词典释义」，只看是否贴合来源句语境下的实际含义。\n"
    "- 多条来源句一起呈现（同词多义/多用法，ADR-010）：学习者解释清楚其中所呈现的义项即可，"
    "若各句义项不同，能说清正在解释的那一个就算对，不强求覆盖全部。\n"
    "只输出 JSON，不要多余文字。"
)


class JudgeResult(BaseModel):
    """判断结果 + 映射出的 FSRS 评级。feedback 给用户看（中文，简短）。"""

    verdict: str  # correct | partial | wrong
    rating: ReviewRating  # 映射出的离散评级（ADR-011）
    feedback: str = ""  # 简短反馈（点出对/偏在哪），不充当「标准答案」


class Passage(BaseModel):
    """F3b 造出的短文 + 实际用上的目标词（前端高亮、检验对齐）。"""

    text: str  # 含目标词的英文短文
    words_used: list[str]  # 短文实际用到的目标词（lemma，可能少于请求集）


class WordCheck(BaseModel):
    """F3b 对单个目标词在语境中的理解检验结果（→ FSRS 评级，复用 ADR-011 映射）。"""

    word: str
    verdict: str  # correct | partial | wrong
    rating: ReviewRating
    feedback: str = ""  # 中文简短反馈


class MemoryWordAgent:
    """F3a 判断。LLM 由功能层按 reasoning 任务解析后注入（ADR-006）。"""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def judge(
        self,
        *,
        word: str,
        context_sentences: list[str],
        understanding: str,
        too_easy: bool = False,
    ) -> JudgeResult:
        """判断复述理解是否到位，映射出 FSRS 评级（ADR-011）。

        context_sentences：复习卡上**实际展示给用户的全部来源句**（多义并呈，ADR-010）。
        全部传给 LLM，避免「卡上展示多句、判断却只看第一句」导致用户解释了后面的句子却被判错。
        too_easy：用户自评「太简单」（秒答）→ 直接 EASY，省一次 LLM 调用。
        空理解 → 直接 AGAIN，不烧 token。
        """
        if too_easy:
            return JudgeResult(
                verdict="correct", rating=ReviewRating.EASY, feedback="标记为太简单，下次间隔拉长。"
            )
        if not understanding or not understanding.strip():
            return JudgeResult(
                verdict="wrong", rating=ReviewRating.AGAIN, feedback="未作答，按未掌握处理。"
            )

        contexts = [s.strip() for s in context_sentences if s and s.strip()]
        if contexts:
            joined = "\n".join(f"{i}. {s}" for i, s in enumerate(contexts, 1))
            context_block = f"来源句（共 {len(contexts)} 条）：\n{joined}\n"
        else:
            context_block = "来源句：（无）\n"
        user = (
            f"单词：{word}\n"
            f"{context_block}"
            f"学习者的理解：{understanding.strip()}\n\n"
            "请判断并输出 JSON：\n"
            '{"verdict": "<correct|partial|wrong>", "feedback": "<中文简短反馈，1 句>"}\n'
            "- correct：抓住了来源句语境下的意思（多句时说清其一即可）。\n"
            "- partial：沾边但不准、漏义或含糊。\n"
            "- wrong：理解错误或答非所问。"
        )
        resp = await self._llm.chat(
            [
                ChatMessage(role=Role.SYSTEM, content=_SYSTEM),
                ChatMessage(role=Role.USER, content=user),
            ],
            temperature=0.0,  # 判分要稳
        )
        return self._parse(resp.content)

    @staticmethod
    def _parse(content: str) -> JudgeResult:
        """解析判断；无法解析或非法 verdict → 保守按 partial(HARD) 处理，宁可多复习。"""
        try:
            obj = parse_json_object(content)
        except ValueError:
            obj = {}
        verdict = str(obj.get("verdict", "")).strip().lower()
        if verdict not in _VERDICT_TO_RATING:
            verdict = "partial"  # 拿不准 → 偏保守，归 HARD（多复习一次不亏）
        return JudgeResult(
            verdict=verdict,
            rating=_VERDICT_TO_RATING[verdict],
            feedback=str(obj.get("feedback", "")).strip(),
        )

    # ── F3b 语境造句背 ──────────────────────────────────────────────
    async def make_passage(
        self, words: list[str], *, topic: str | None = None, baseline: str | None = None
    ) -> Passage:
        """用一批生词造一段短文供翻译检验（F3b）。空词表 → 空短文，不烧 token。

        贴近用户话题（话题联动，docs/01 跨功能补充能力 5）；难度适配水平基线。
        不存释义（ADR-004）：短文是「在语境中重新建立理解」的载体，不是标准答案。
        """
        targets = _dedup_words(words)
        if not targets:
            return Passage(text="", words_used=[])

        resp = await self._llm.chat(
            [
                ChatMessage(role=Role.SYSTEM, content=_PASSAGE_SYSTEM),
                ChatMessage(
                    role=Role.USER, content=_passage_prompt(targets, topic, baseline)
                ),
            ],
            temperature=0.7,  # 造文要自然，可放开
        )
        return self._parse_passage(resp.content, targets)

    async def check_translation(
        self, *, passage: str, words: list[str], translation: str
    ) -> list[WordCheck]:
        """检验用户译文是否在语境中理解对了每个目标词（F3b）。

        不比对标准译文（ADR-004）：只看「这段语境里每个词的意思有没有理解对」。
        每词映射出 FSRS 评级（复用 ADR-011 的 correct/partial/wrong→GOOD/HARD/AGAIN）。
        空译文 → 全部 AGAIN，不烧 token。
        """
        targets = _dedup_words(words)
        if not targets:
            return []
        if not translation or not translation.strip():
            return [
                WordCheck(
                    word=w, verdict="wrong", rating=ReviewRating.AGAIN, feedback="未作答。"
                )
                for w in targets
            ]

        resp = await self._llm.chat(
            [
                ChatMessage(role=Role.SYSTEM, content=_CHECK_SYSTEM),
                ChatMessage(
                    role=Role.USER,
                    content=_check_prompt(passage, targets, translation.strip()),
                ),
            ],
            temperature=0.0,  # 判分要稳
        )
        return _parse_checks(resp.content, targets)

    @staticmethod
    def _parse_passage(content: str, targets: list[str]) -> Passage:
        """解析短文。解析失败 → 退回原始文本、按是否字面出现推断 words_used。"""
        try:
            obj = parse_json_object(content)
            text = str(obj.get("text", "")).strip()
            raw_used = obj.get("words_used")
            used = (
                [str(w).strip().lower() for w in raw_used if str(w).strip()]
                if isinstance(raw_used, list)
                else []
            )
        except ValueError:
            text = content.strip()
            used = []
        if not used and text:
            # LLM 没回 words_used → 按字面出现兜底（够前端高亮/对齐用）。
            low = text.lower()
            used = [w for w in targets if w in low]
        # 只保留确属请求集的词，保序。
        used = [w for w in targets if w in used]
        return Passage(text=text, words_used=used)


# ── F3b 提示词与解析辅助 ────────────────────────────────────────────
def _dedup_words(words: list[str]) -> list[str]:
    """去重保序 + strip + 小写；丢空串。"""
    out: list[str] = []
    for w in words:
        w = (w or "").strip().lower()
        if w and w not in out:
            out.append(w)
    return out


def _passage_prompt(targets: list[str], topic: str | None, baseline: str | None) -> str:
    ctx = ""
    if topic:
        ctx += f"贴近话题：{topic}\n"
    if baseline:
        ctx += f"学习者水平基线（CEFR）：{baseline}\n"
    word_line = ", ".join(targets)
    return (
        f"{ctx}"
        f"目标词（共 {len(targets)} 个）：{word_line}\n\n"
        "请输出 JSON：\n"
        '{"text": "<含目标词的英文短文，4-7句>", "words_used": ["<实际用到的目标词>"]}'
    )


def _check_prompt(passage: str, targets: list[str], translation: str) -> str:
    word_line = ", ".join(targets)
    return (
        f"英文短文：\n{passage}\n\n"
        f"目标词：{word_line}\n"
        f"学习者的中文翻译：\n{translation}\n\n"
        "请逐个目标词判断并输出 JSON：\n"
        '{"checks": [{"word": "<目标词>", "verdict": "<correct|partial|wrong>", '
        '"feedback": "<中文简短反馈,1句>"}]}\n'
        "- correct：在该语境下理解对了这个词的意思。\n"
        "- partial：沾边但不准、漏义或含糊。\n"
        "- wrong：理解错误或译文未覆盖该词。"
    )


def _parse_checks(content: str, targets: list[str]) -> list[WordCheck]:
    """解析逐词检验；缺失/非法的词保守按 partial(HARD)，宁可多复习一次（同 ADR-011 兜底）。"""
    try:
        obj = parse_json_object(content)
    except ValueError:
        obj = {}
    raw = obj.get("checks")
    by_word: dict[str, dict] = {}
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                key = str(item.get("word", "")).strip().lower()
                if key:
                    by_word[key] = item
    out: list[WordCheck] = []
    for w in targets:
        item = by_word.get(w, {})
        verdict = str(item.get("verdict", "")).strip().lower()
        if verdict not in _VERDICT_TO_RATING:
            verdict = "partial"  # 拿不准 → 偏保守
        out.append(
            WordCheck(
                word=w,
                verdict=verdict,
                rating=_VERDICT_TO_RATING[verdict],
                feedback=str(item.get("feedback", "")).strip(),
            )
        )
    return out
