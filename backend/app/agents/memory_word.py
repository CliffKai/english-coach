"""MemoryWordAgent —— F3a 理解式背词（L3 第 3 步，消费 F1 生词 + L2 FSRS 队列）。

逻辑（docs/01 功能3a，ADR-004）：给出**来源句**，问「这个词在这句里你理解是什么意思」，
用户用自己的话说 → LLM 判断理解是否到位 —— **不比对标准释义**（来源句本身就是消歧钥匙，
意思应被重新理解出来，而非比对存储的定义）。

核心难点（07 已知风险）：F3a 是开放式判断，FSRS 却要离散评级（again/hard/good/easy）。
本 Agent 负责「模糊判断 → 离散评级」的映射，映射规则定为 ADR-011：
  LLM 输出 verdict ∈ {correct, partial, wrong} + 可选 too_easy 标志，映射：
    too_easy=True             → EASY  （用户表示太简单/秒答）
    correct                   → GOOD
    partial                   → HARD  （沾边但不准/漏义/犹豫）
    wrong / 空答 / 无关        → AGAIN
判分只看「是否抓住该语境下的意思」，不苛求措辞精确（理解式，非默写）。
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
