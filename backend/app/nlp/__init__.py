"""NLP 层（L2，docs/07）：spaCy 切词 + lemma 还原 + 词频过滤。

供功能1（生词收集）与水平基线分级共用——故必须前置（07 红线：基线先于 F1/F2）。
业务只依赖 `Tokenizer` 接口；默认实现 `SpacyTokenizer`。
"""

from app.nlp.tokenizer import SpacyTokenizer, Token, Tokenizer

__all__ = ["Tokenizer", "SpacyTokenizer", "Token"]
