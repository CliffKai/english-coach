"""L2 验证（docs/07）：spaCy 切词 + lemma 还原 + 词频过滤。

✅ 标准：一段英文 → 词元列表；候选生词按 lemma 去重、按基线/词频过滤、带来源句。
需要 en_core_web_sm 模型（`python -m spacy download en_core_web_sm`），缺失则 skip。
"""

from __future__ import annotations

import pytest

from app.nlp.tokenizer import SpacyTokenizer, cutoff_for_baseline

# 模型未安装则整文件跳过（CI 未装 ML 栈时不红）。
spacy = pytest.importorskip("spacy")
if not spacy.util.is_package("en_core_web_sm"):
    pytest.skip("en_core_web_sm 未安装", allow_module_level=True)


@pytest.fixture(scope="module")
def tokenizer() -> SpacyTokenizer:
    return SpacyTokenizer()


# ── 切词 + lemma ────────────────────────────────────────────────────
def test_tokenize_lemmatizes_and_keeps_sentence(tokenizer: SpacyTokenizer):
    tokens = tokenizer.tokenize("The cats were running quickly.")
    by_text = {t.text.lower(): t for t in tokens}
    # 词形还原：cats→cat, running→run, were→be。
    assert by_text["cats"].lemma == "cat"
    assert by_text["running"].lemma == "run"
    # 来源句保留（供 VocabEntry.context_sentences，ADR-004）。
    assert by_text["running"].sentence == "The cats were running quickly."
    # 内容词标记：cat/run 是内容词；the（停用词）不是。
    assert by_text["cats"].is_content is True
    assert by_text["the"].is_content is False


def test_tokenize_splits_sentences(tokenizer: SpacyTokenizer):
    tokens = tokenizer.tokenize("I went to the bank. He sat by the river bank.")
    sentences = {t.sentence for t in tokens}
    assert "I went to the bank." in sentences
    assert "He sat by the river bank." in sentences


# ── 候选生词：去重 + 过滤 + 来源句合并 ──────────────────────────────
def test_extract_candidates_filters_common_words(tokenizer: SpacyTokenizer):
    text = "The ubiquitous use of ephemeral apps is a serendipitous trend."
    cands = tokenizer.extract_candidates(text, baseline="B1")
    lemmas = {c.lemma for c in cands}
    # 生僻词进候选。
    assert "ubiquitous" in lemmas
    assert "ephemeral" in lemmas
    # 高频/停用词不进候选。
    assert "the" not in lemmas
    assert "use" not in lemmas


def test_extract_candidates_dedups_by_lemma_and_merges_contexts(
    tokenizer: SpacyTokenizer,
):
    # 同一 lemma "ephemeral" 出现在两句中 → 一条候选 + 两条来源句（多义并呈，ADR-010）。
    text = "A fad is ephemeral. Fame can be ephemeral too."
    cands = tokenizer.extract_candidates(text, baseline="B1")
    eph = [c for c in cands if c.lemma == "ephemeral"]
    assert len(eph) == 1
    assert len(eph[0].context_sentences) == 2


def test_baseline_controls_strictness(tokenizer: SpacyTokenizer):
    text = "She made a comprehensive analysis of the problem."
    # 低水平基线 cutoff 高 → 更多词进候选（含 comprehensive/analysis 等中频词）。
    low = {c.lemma for c in tokenizer.extract_candidates(text, baseline="A2")}
    # 高水平基线 cutoff 低 → 只剩更生僻的。
    high = {c.lemma for c in tokenizer.extract_candidates(text, baseline="C2")}
    assert high <= low  # 高基线候选是低基线的子集
    assert len(low) >= len(high)


def test_min_zipf_filters_noise(tokenizer: SpacyTokenizer):
    # 语料外的拼写错误（zipf≈0）被 min_zipf 下界滤掉。
    text = "This is a asdfqwer mistake."
    cands = tokenizer.extract_candidates(text, baseline="B1", min_zipf=1.0)
    assert "asdfqwer" not in {c.lemma for c in cands}


# ── 基线 → cutoff 映射 ──────────────────────────────────────────────
def test_cutoff_mapping():
    # CEFR：水平越高，cutoff 越低（只挑更生僻词）。
    assert cutoff_for_baseline("A1") > cutoff_for_baseline("C2")
    assert cutoff_for_baseline("a1") == cutoff_for_baseline("A1")  # 大小写无关
    # 估算雅思分折算到 CEFR。
    assert cutoff_for_baseline("8.0") == cutoff_for_baseline("C2")
    assert cutoff_for_baseline("3.0") == cutoff_for_baseline("A2")
    # 无法解析 / 缺失 → 回退默认（B1）。
    assert cutoff_for_baseline(None) == cutoff_for_baseline("B1")
    assert cutoff_for_baseline("garbage") == cutoff_for_baseline("B1")
