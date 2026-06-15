"""L3 路由验证（docs/07 ✅：粘贴文本能攒生词并背诵）。

用 TestClient + 注入 mock 容器（FakeLLM + 内存 SQLite + 真实 tokenizer/scheduler），
走通 HTTP 闭环：分级 → extract → collect → due → review/next → review/submit。
全程离线。缺 en_core_web_sm 时 extract 用例跳过。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.adapters.llm import LLMResponse
from app.adapters.local import (
    SqliteSettingsRepository,
    SqliteWordRepository,
)
from app.container import Container, set_container
from app.db.connection import Database
from app.main import app
from app.scheduling import FsrsScheduler

spacy = pytest.importorskip("spacy")
_HAS_MODEL = spacy.util.is_package("en_core_web_sm")


class FakeLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    async def chat(self, messages, *, model=None, temperature=0.7, max_tokens=None):
        return LLMResponse(content=self.reply, model=model or "fake")

    def stream_chat(self, messages, *, model=None, temperature=0.7, max_tokens=None):
        async def _gen():
            yield self.reply

        return _gen()


def _make_container(reply: str) -> tuple[Container, Database]:
    db = Database(":memory:")
    tokenizer = None
    if _HAS_MODEL:
        from app.nlp.tokenizer import SpacyTokenizer

        tokenizer = SpacyTokenizer()
    return (
        Container(
            llm=FakeLLM(reply),
            words=SqliteWordRepository(db),
            settings=SqliteSettingsRepository(db),
            tokenizer=tokenizer,
            scheduler=FsrsScheduler(),
        ),
        db,
    )


@pytest.fixture
def client_correct():
    """容器的 LLM 恒回 correct/B2，供闭环走通。

    注意：必须在进入 TestClient 上下文（触发 lifespan 绑真实适配器）**之后**再注入
    mock 容器，否则会被 lifespan 覆盖（lifespan 无配置时 llm=None，scoring 任务 409）。
    """
    reply = json.dumps({"verdict": "correct", "feedback": "对", "baseline": "B2"})
    container, db = _make_container(reply)
    with TestClient(app) as c:
        set_container(container)
        yield c
    set_container(Container())
    db.close()


def test_meta_reports_l3_features_on(client_correct: TestClient):
    feats = client_correct.get("/api/meta").json()["features"]
    assert feats["vocab_collection"] is True
    assert feats["comprehension_review"] is True
    assert feats["topic_practice"] is False  # F2 待接


def test_baseline_prompt_and_assess_persists(client_correct: TestClient):
    assert "prompt" in client_correct.get("/api/baseline/prompt").json()
    # 未分级。
    assert client_correct.get("/api/baseline").json()["baseline"] is None
    # 分级 → 写库。
    resp = client_correct.post("/api/baseline/assess", json={"sample": "My town is quiet."})
    body = resp.json()
    assert resp.status_code == 200
    assert body["baseline"] == "B2" and body["estimated"] is True
    # 持久化生效。
    assert client_correct.get("/api/baseline").json()["baseline"] == "B2"


@pytest.mark.skipif(not _HAS_MODEL, reason="en_core_web_sm 未安装")
def test_full_loop_extract_collect_due_review(client_correct: TestClient):
    # 1) 切词出候选（按基线过滤）。
    text = "The ubiquitous use of ephemeral apps is a serendipitous trend."
    ex = client_correct.post("/api/vocab/extract", json={"text": text, "baseline": "B1"}).json()
    lemmas = {c["lemma"] for c in ex["candidates"]}
    assert "ephemeral" in lemmas

    # 2) 把「不认识」的连同来源句入库。
    items = [
        {"word": c["word"], "lemma": c["lemma"], "context_sentences": c["context_sentences"]}
        for c in ex["candidates"]
        if c["lemma"] in {"ephemeral", "ubiquitous"}
    ]
    collected = client_correct.post("/api/vocab/collect", json={"items": items}).json()
    assert len(collected) == 2

    # 3) 进 due 队列。
    due = client_correct.get("/api/vocab/due").json()
    assert {e["lemma"] for e in due} >= {"ephemeral", "ubiquitous"}

    # 4) 取一张复习卡（只给词+来源句，无释义）。
    card = client_correct.get("/api/review/next").json()
    assert card is not None
    assert "definition" not in card  # ADR-004
    assert card["context_sentences"]

    # 5) 提交理解 → 判断 → 推进 FSRS。
    sub = client_correct.post(
        "/api/review/submit",
        json={"entry_id": card["entry_id"], "understanding": "短暂的、转瞬即逝"},
    ).json()
    assert sub["verdict"] == "correct"
    assert sub["rating"] == 3  # GOOD
    assert sub["next_due"] is not None


def test_review_submit_404_on_missing_entry(client_correct: TestClient):
    resp = client_correct.post(
        "/api/review/submit", json={"entry_id": "nope", "understanding": "x"}
    )
    assert resp.status_code == 404


def test_baseline_assess_409_when_no_llm():
    """无 LLM 配置 → scoring 任务解析失败 → 409 提示去配模型。"""
    db = Database(":memory:")
    with TestClient(app) as c:
        # lifespan 之后注入「有存储、无 LLM」的容器。
        set_container(
            Container(words=SqliteWordRepository(db), settings=SqliteSettingsRepository(db))
        )
        resp = c.post("/api/baseline/assess", json={"sample": "hello world this is a test"})
        assert resp.status_code == 409
    set_container(Container())
    db.close()
