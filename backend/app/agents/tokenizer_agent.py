"""TokenizerAgent —— F1 生词收集（L3 第 2 步，吃水平基线的产物）。

流程（docs/01 功能1 / docs/02）：
  英文文本 → 切词+lemma+词频过滤（L2 SpacyTokenizer，按 Settings.level_baseline）
          → 逐词问「认识/跳过/不认识」（前端交互）
          → 「不认识」者连同来源句入库 VocabEntry（功能3 消费）

为什么这层不调 LLM：切词/还原/过滤是确定性任务，L2 已用 spaCy+wordfreq 做完
（ADR-008：高频任务不烧 token，LLM 只在确有必要时介入）。本 Agent 只做「编排」：
取候选 → 接收用户判断 → 按 lemma 查重入库（同词不同义追加来源句，ADR-004/010）。

入库查重（ADR-004）：按 lemma 命中已有条目则**合并来源句**，不新建；schema 在
(user_id, lemma) 上有唯一索引，重复 add 会撞键，故必经 get_by_lemma 分流。
"""

from __future__ import annotations

from pydantic import BaseModel

from app.adapters.llm import ChatMessage, LLMProvider, Role
from app.adapters.repository import WordRepository
from app.models import DEFAULT_USER_ID, VocabEntry, VocabStatus
from app.nlp.tokenizer import Tokenizer, VocabCandidate


class CollectItem(BaseModel):
    """前端回传的一条「不认识」判断：词 + 来源句。

    只收「不认识」的（认识/跳过不入库）。context_sentences 取自切词阶段的候选来源句，
    由前端原样回传，避免后端重切。lemma 用于查重；前端可直接回传候选里的 lemma。
    """

    word: str
    lemma: str
    context_sentences: list[str] = []


class TokenizerAgent:
    """F1 编排。tokenizer 来自容器（L2 SpacyTokenizer），words 是 WordRepository。"""

    def __init__(self, tokenizer: Tokenizer, words: WordRepository) -> None:
        self._tokenizer = tokenizer
        self._words = words

    async def manual_candidate(
        self,
        word: str,
        *,
        text: str | None = None,
        sentence: str | None = None,
        llm: LLMProvider | None = None,
    ) -> VocabCandidate:
        """用户补录一个生词，按优先级取来源句产出候选（ADR-015）。

        过滤会漏词（被基线判"已掌握"的词、或脱离文本临时想起的词），故给用户补录出口。
        来源句优先级（越靠前越真实，越省 token）：
          1. 用户自填 `sentence` → 直接用（零 LLM）。
          2. 否则该词能在 `text` 中定位 → 取原文句（零 LLM，「从本文补词」）。
          3. 否则有 `llm` → 造一个自然例句（conversation 档，「凭空加词」）。
          4. 兜底：无来源句的纯词（不报错，背词仍可凭 word 复习，只是缺语境）。
        lemma：能从文本/造句切出就用切出的，否则退化为 word 小写。
        """
        word = word.strip()
        lemma = word.lower()

        # 1. 用户自填例句：直接采用，并尽量用切词器还原 lemma。
        if sentence and sentence.strip():
            located = self._tokenizer.locate_in_text(word, sentence)
            if located is not None:
                lemma = located.lemma
            return VocabCandidate(
                word=word, lemma=lemma, zipf=0.0, context_sentences=[sentence.strip()]
            )

        # 2. 从当前文本定位（「从本文补词」）：取该词所在原句，纯确定性。
        if text and text.strip():
            located = self._tokenizer.locate_in_text(word, text)
            if located is not None:
                return VocabCandidate(
                    word=located.text,
                    lemma=located.lemma,
                    zipf=located.zipf,
                    context_sentences=[located.sentence] if located.sentence else [],
                )

        # 3. LLM 造句（「凭空加词」）：轻任务，走 conversation 档（调用方传入）。
        if llm is not None:
            generated = await self._generate_sentence(word, llm)
            if generated:
                located = self._tokenizer.locate_in_text(word, generated)
                if located is not None:
                    lemma = located.lemma
                return VocabCandidate(
                    word=word, lemma=lemma, zipf=0.0, context_sentences=[generated]
                )

        # 4. 兜底：无来源句的纯词。
        return VocabCandidate(word=word, lemma=lemma, zipf=0.0, context_sentences=[])

    @staticmethod
    async def _generate_sentence(word: str, llm: LLMProvider) -> str | None:
        """让 LLM 为 word 造一个自然、地道的英文例句作来源句（ADR-015）。

        造的是「用法示例」非「释义」（忠于 ADR-004）：只回一句话，不附中文、不附定义。
        失败（网络/空回复）返回 None，由调用方降级为无来源句，不报错。
        """
        messages = [
            ChatMessage(
                role=Role.SYSTEM,
                content=(
                    "You write a single natural English example sentence that uses the "
                    "given word in a clear, everyday context. Reply with ONLY the sentence "
                    "— no definition, no translation, no quotes, no extra text."
                ),
            ),
            ChatMessage(role=Role.USER, content=f"Word: {word}"),
        ]
        try:
            resp = await llm.chat(messages, temperature=0.7, max_tokens=60)
        except Exception:  # noqa: BLE001 造句失败不该阻断补录，降级为无来源句
            return None
        text = resp.content.strip().strip('"').strip()
        return text or None

    def extract(
        self, text: str, *, baseline: str | None, min_zipf: float = 1.0
    ) -> list[VocabCandidate]:
        """切词+过滤，产出「值得问用户」的候选生词（确定性，无 LLM）。

        baseline 由功能层从 Settings.level_baseline 取得（07 红线：基线先于 F1）。
        min_zipf 默认 1.0：滤掉语料外噪音（拼写错误/罕见专名 zipf≈0），避免问无意义的词。
        """
        return self._tokenizer.extract_candidates(
            text, baseline=baseline, min_zipf=min_zipf
        )

    async def collect(
        self, items: list[CollectItem], *, user_id: str = DEFAULT_USER_ID
    ) -> list[VocabEntry]:
        """把「不认识」的词连同来源句入库，按 lemma 查重合并。

        返回最终入库/更新后的条目（新建或合并）。空来源句的项也入库（仅词，无句），
        但通常前端会带上候选的来源句。
        """
        result: list[VocabEntry] = []
        # 同一批里同 lemma 多次出现也要合并，故用本地缓存避免批内重复新建。
        seen: dict[str, VocabEntry] = {}
        for item in items:
            lemma = item.lemma.strip().lower()
            if not lemma:
                continue
            entry = seen.get(lemma) or await self._words.get_by_lemma(
                lemma, user_id=user_id
            )
            if entry is None:
                entry = VocabEntry(
                    user_id=user_id,
                    word=item.word,
                    lemma=lemma,
                    context_sentences=_dedup(item.context_sentences),
                )
                await self._words.add(entry)
            else:
                merged = _merge_contexts(entry.context_sentences, item.context_sentences)
                if merged != entry.context_sentences:
                    entry.context_sentences = merged
                    # 已毕业（known）的词又被标为「不认识」并带来新义项/用法 → 拉回 learning，
                    # 否则 list_due 会把它过滤掉，用户永远复习不到这条新收集的来源句（ADR-010）。
                    if entry.status == VocabStatus.KNOWN:
                        entry.status = VocabStatus.LEARNING
                    await self._words.update(entry)
            seen[lemma] = entry
            result.append(entry)
        # 同 lemma 在 result 里只保留一条最终态（去重，保序）。
        return list({e.lemma: e for e in result}.values())


def _dedup(sentences: list[str]) -> list[str]:
    """去重保序 + strip 空白，丢掉空句。"""
    out: list[str] = []
    for s in sentences:
        s = s.strip()
        if s and s not in out:
            out.append(s)
    return out


def _merge_contexts(existing: list[str], incoming: list[str]) -> list[str]:
    """已有来源句 + 新来源句，去重保序合并（同词不同义并呈，ADR-004/010）。"""
    merged = list(existing)
    for s in incoming:
        s = s.strip()
        if s and s not in merged:
            merged.append(s)
    return merged
