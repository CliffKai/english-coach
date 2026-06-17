"""spaCy 切词 + lemma 还原 + wordfreq 词频过滤（L2，docs/07）。

为什么用 spaCy 而非纯 LLM 切词（ADR-008 / docs/04）：lemma 还原比 LLM 更稳更省，
高频任务不该每次烧 token。LLM 只在「逐词问询/判断」环节介入（TokenizerAgent，L3）。

本模块只做**确定性**的预处理：把一段英文 → 词元 → 去重 → 按词频/水平基线过滤，
产出「值得问用户认不认识」的候选生词（连同来源句，ADR-004）。问询与入库在 L3。

接口（ABC）+ 默认实现（SpacyTokenizer），延续 ADR-002 的可替换风格；
但切词是纯 CPU 同步任务，故接口是同步的——调用方（FastAPI 路由/Agent）需要时用
`asyncio.to_thread` 包装即可，不强加 async。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from functools import lru_cache

from pydantic import BaseModel

# 内容词词性（值得收集为生词的）：名/动/形/副。
# 刻意排除 PROPN（人名/地名等专有名词不是要背的词汇）与功能词。
_CONTENT_POS = frozenset({"NOUN", "VERB", "ADJ", "ADV"})


class Token(BaseModel):
    """单个词元的切词结果。`sentence` 保留来源句，供生词条目存 context（ADR-004）。"""

    text: str  # 原始表面形式（如 "running"）
    lemma: str  # 词元（如 "run"），已小写
    pos: str  # 粗粒度词性（spaCy pos_）
    is_content: bool  # 是否内容词（alpha + 非停用词 + 词性 ∈ 内容词）
    zipf: float  # wordfreq zipf 词频（0=语料外，越大越常见）
    sentence: str  # 该词所在的来源句（已 strip）


class VocabCandidate(BaseModel):
    """一个候选生词（已按 lemma 去重）。直接喂给 L3 的逐词问询 / VocabEntry 入库。

    同一 lemma 在文中多次出现 → 合并多条来源句（多义并呈，ADR-004 / ADR-010）。
    """

    word: str  # 首次出现的表面形式
    lemma: str
    zipf: float
    context_sentences: list[str]  # 出现过的来源句（去重，按出现顺序）


# ── 水平基线 → 词频截断（zipf）────────────────────────────────────
# 语义：zipf < cutoff 的词才算「可能不认识」，进入候选；>= cutoff 视为「该水平已掌握」，
# 不打扰用户。水平越低 → cutoff 越高（更多词被标为候选）；越高 → cutoff 越低（只挑生僻词）。
# zipf 参考刻度：7+ 极常见(the) · 5-6 常见(run/make) · 3-4 中等(ubiquitous) · <3 生僻(serendipity)。
_CEFR_CUTOFF: dict[str, float] = {
    "A1": 4.5,
    "A2": 4.0,
    "B1": 3.5,
    "B2": 3.0,
    "C1": 2.7,
    "C2": 2.3,
}
# 基线缺失（未做分级）时的默认 cutoff，取 B1 档（不过滤太狠也不太松）。
_DEFAULT_CUTOFF = _CEFR_CUTOFF["B1"]


def cutoff_for_baseline(baseline: str | None) -> float:
    """把 `Settings.level_baseline` 映射到 zipf 截断。

    支持两种基线写法（docs/03 Settings.level_baseline = CEFR / 估算雅思分）：
    - CEFR 字母码（"A1".."C2"，大小写不限）→ 查表。
    - 估算雅思分（数字串，如 "6.5"）→ 先折算到 CEFR 再查表。
    解析不了则回退默认档（B1）。
    """
    if not baseline:
        return _DEFAULT_CUTOFF
    key = baseline.strip().upper()
    if key in _CEFR_CUTOFF:
        return _CEFR_CUTOFF[key]
    # 估算雅思分 → CEFR（雅思官方对照的粗映射）。
    try:
        band = float(key)
    except ValueError:
        return _DEFAULT_CUTOFF
    if band < 4.0:
        return _CEFR_CUTOFF["A2"]
    if band < 5.0:
        return _CEFR_CUTOFF["B1"]
    if band < 6.5:
        return _CEFR_CUTOFF["B2"]
    if band < 7.5:
        return _CEFR_CUTOFF["C1"]
    return _CEFR_CUTOFF["C2"]


class Tokenizer(ABC):
    """切词/词元/过滤接口。业务只依赖它；默认实现见 SpacyTokenizer。"""

    @abstractmethod
    def tokenize(self, text: str) -> list[Token]:
        """切词 + lemma 还原，按出现顺序返回全部词元（含来源句）。"""

    @abstractmethod
    def extract_candidates(
        self, text: str, *, baseline: str | None = None, min_zipf: float = 0.0
    ) -> list[VocabCandidate]:
        """提取候选生词：内容词 → 去重(lemma) → 按基线/词频过滤 → 合并来源句。

        过滤条件（同时满足才入候选）：
        - 是内容词（名/动/形/副、非停用词、纯字母）；
        - `min_zipf <= zipf < cutoff_for_baseline(baseline)`：上界滤掉「该水平已会」的高频词，
          下界 `min_zipf` 滤掉语料外的噪音（拼写错误、罕见专名等，默认 0=不滤下界）。
        """

    def locate_in_text(self, word: str, text: str) -> Token | None:
        """在 text 中定位 word（按表面形式或 lemma 匹配），返回首个命中的 Token。

        用户补录生词时（ADR-015「从本文补词」）：词就在原文里，来源句天然存在，
        故对原文切词、匹配该词、取它所在句——纯确定性，无 LLM。
        匹配优先精确表面形式，再退到 lemma（用户填 "running" 也能命中 lemma "run"）。
        基于 `tokenize` 实现，对所有 Tokenizer 子类通用，未命中返回 None。
        """
        needle = word.strip().lower()
        if not needle:
            return None
        fallback: Token | None = None
        for tok in self.tokenize(text):
            if tok.text.lower() == needle:
                return tok
            if fallback is None and tok.lemma == needle:
                fallback = tok
        return fallback


# spaCy pipeline 加载开销大，按模型名缓存单例（进程内复用）。
@lru_cache(maxsize=2)
def _load_nlp(model: str):
    import spacy

    # 只需切词/词性/lemma，关掉 NER/parser 省时间；用 senter 切句（轻量）。
    nlp = spacy.load(model, disable=["ner", "parser"])
    if "senter" not in nlp.pipe_names and "sentencizer" not in nlp.pipe_names:
        nlp.add_pipe("sentencizer")
    return nlp


class SpacyTokenizer(Tokenizer):
    """spaCy 实现。默认英文小模型 en_core_web_sm（需 `python -m spacy download` 装好）。"""

    def __init__(self, model: str = "en_core_web_sm") -> None:
        self._model = model

    def tokenize(self, text: str) -> list[Token]:
        from wordfreq import zipf_frequency

        nlp = _load_nlp(self._model)
        tokens: list[Token] = []
        for sent in nlp(text).sents:
            sentence = sent.text.strip()
            for tok in sent:
                if tok.is_space or tok.is_punct:
                    continue
                lemma = tok.lemma_.lower()
                is_content = (
                    tok.is_alpha and not tok.is_stop and tok.pos_ in _CONTENT_POS
                )
                tokens.append(
                    Token(
                        text=tok.text,
                        lemma=lemma,
                        pos=tok.pos_,
                        is_content=is_content,
                        zipf=zipf_frequency(lemma, "en"),
                        sentence=sentence,
                    )
                )
        return tokens

    def extract_candidates(
        self, text: str, *, baseline: str | None = None, min_zipf: float = 0.0
    ) -> list[VocabCandidate]:
        cutoff = cutoff_for_baseline(baseline)
        # 按 lemma 聚合，保留首次表面形式与去重来源句（dict 保序）。
        merged: dict[str, VocabCandidate] = {}
        for tok in self.tokenize(text):
            if not tok.is_content:
                continue
            if not (min_zipf <= tok.zipf < cutoff):
                continue
            existing = merged.get(tok.lemma)
            if existing is None:
                merged[tok.lemma] = VocabCandidate(
                    word=tok.text,
                    lemma=tok.lemma,
                    zipf=tok.zipf,
                    context_sentences=[tok.sentence] if tok.sentence else [],
                )
            elif tok.sentence and tok.sentence not in existing.context_sentences:
                existing.context_sentences.append(tok.sentence)
        return list(merged.values())
