"""L3 后半路由验证（docs/07 ✅：写一段文章能拿到分数 + 错题）。

用 TestClient + 注入 mock 容器（FakeLLM + 内存 SQLite），走通 HTTP「错误河」结算：
practice/score → 落库会话 + 回填错题本 → errors/practice 可读回。全程离线。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.adapters.llm import LLMResponse
from app.adapters.local import (
    SqliteErrorRepository,
    SqliteSessionRepository,
    SqliteSettingsRepository,
    SqliteWordRepository,
)
from app.container import Container, set_container
from app.db.connection import Database
from app.main import app


class FakeLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[list] = []  # 记录每次收到的 messages（验证装配/历史）

    async def chat(self, messages, *, model=None, temperature=0.7, max_tokens=None):
        self.calls.append(messages)
        return LLMResponse(content=self.reply, model=model or "fake")

    def stream_chat(self, messages, *, model=None, temperature=0.7, max_tokens=None):
        async def _gen():
            yield self.reply

        return _gen()


# 同一个 FakeLLM 既要回打分 JSON（含 dimensions/errors）也要回复盘 JSON（summary/patterns）。
# 两份 schema 字段不冲突，合在一个回复里：ExaminerAgent 取 dimensions/errors，
# ErrorAnalysisAgent 取 summary/patterns，互不干扰。
_COMBINED_REPLY = json.dumps(
    {
        "dimensions": [
            {"key": "task_response", "score": 6, "comment": "切题"},
            {"key": "coherence_cohesion", "score": 6, "comment": "连贯"},
            {"key": "lexical_resource", "score": 6, "comment": "词汇"},
            {"key": "grammatical_range_accuracy", "score": 6, "comment": "语法"},
        ],
        "errors": [
            {
                "type": "grammar",
                "original": "I has a cat",
                "correction": "I have a cat",
                "explanation": "主谓一致",
                "severity": 2,
            }
        ],
        "summary": "整体清楚，注意主谓一致。",
        "patterns": ["主谓一致"],
    }
)


def _make_container(reply: str) -> tuple[Container, Database]:
    db = Database(":memory:")
    return (
        Container(
            llm=FakeLLM(reply),
            words=SqliteWordRepository(db),
            errors=SqliteErrorRepository(db),
            sessions=SqliteSessionRepository(db),
            settings=SqliteSettingsRepository(db),
        ),
        db,
    )


@pytest.fixture
def client():
    container, db = _make_container(_COMBINED_REPLY)
    with TestClient(app) as c:
        set_container(container)  # lifespan 之后注入，避免被覆盖
        yield c
    set_container(Container())
    db.close()


def test_meta_reports_topic_practice_on(client: TestClient):
    feats = client.get("/api/meta").json()["features"]
    assert feats["topic_practice"] is True


def test_score_returns_dimensions_errors_and_persists(client: TestClient):
    resp = client.post(
        "/api/practice/score",
        json={"text": "I has a cat. It is nice.", "topic": "pets"},
    )
    assert resp.status_code == 200
    body = resp.json()
    # 打分。
    assert body["standard"] == "IELTS"
    assert body["overall"] == 6.0
    assert body["estimated"] is True
    assert len(body["dimensions"]) == 4
    # 错题已落库（带 id）。
    assert len(body["errors"]) == 1
    err = body["errors"][0]
    assert err["id"] and err["type"] == "grammar" and err["session_id"] == body["session_id"]
    # 复盘。
    assert body["report"]["summary"]
    assert body["report"]["type_counts"] == {"grammar": 1}

    # 错题本可读回。
    errors = client.get("/api/errors").json()
    assert len(errors) == 1
    # 仅待巩固（resolved=False）也能读到。
    assert len(client.get("/api/errors?resolved=false").json()) == 1

    # 会话已落库，error_ids/summary 已回填。
    sessions = client.get("/api/practice").json()
    assert len(sessions) == 1
    assert sessions[0]["error_ids"] == [err["id"]]
    assert sessions[0]["summary"]
    assert sessions[0]["scores"]["overall"] == 6.0


def test_score_rejects_practice_mode(client: TestClient):
    """练习模式（即时纠错，TutorAgent/L4）不走考试结算接口 → 400。"""
    resp = client.post(
        "/api/practice/score",
        json={"text": "hello", "mode": "guided_write"},
    )
    assert resp.status_code == 400


def test_score_accepts_dialogue_with_speaking_dims(client: TestClient):
    """L4：对话打分（2d）解禁，用口语维度集；无发音评估时发音/流利度维度空缺并标注（ADR-013）。"""
    resp = client.post(
        "/api/practice/score",
        json={"text": "I think technology make life better.", "mode": "dialogue"},
    )
    assert resp.status_code == 200
    body = resp.json()
    by_key = {d["key"]: d for d in body["dimensions"]}
    # 雅思口语四维。
    assert set(by_key) == {
        "fluency_coherence",
        "lexical_resource",
        "grammatical_range_accuracy",
        "pronunciation",
    }
    # 发音/流利度无评估 → 空缺（score=None）且标 estimated。
    assert by_key["pronunciation"]["score"] is None
    assert by_key["pronunciation"]["estimated"] is True
    assert by_key["fluency_coherence"]["score"] is None
    # 文本可评维度仍有分；overall 只对有分维度求均值（不被空缺拖低）。
    assert by_key["lexical_resource"]["score"] is not None
    assert body["overall"] is not None


def test_dialogue_turn_replies_without_correcting(client: TestClient):
    """F2d 对话单轮：只回自然对话（驱动 TTS），不纠错/不打分（ADR-005 零脚手架）。"""
    resp = client.post(
        "/api/practice/dialogue/turn",
        json={"message": "Hello, I want to talk about travel.", "topic": "travel"},
    )
    assert resp.status_code == 200
    assert resp.json()["reply"]  # 非空回话


def test_first_time_errors_not_counted_as_history():
    """首犯不应被当成『既往反复出现』：复盘取的 history 在写入本次错误之前抓取。

    直接检查复盘 LLM 收到的 user 提示：首次提交时不应出现『既往未解决错题』历史块
    （旧顺序先插错题再取 history，会把本次错误回灌成历史，使首犯被误判为复发）。
    """
    db = Database(":memory:")
    llm = FakeLLM(_COMBINED_REPLY)
    with TestClient(app) as c:
        set_container(
            Container(
                llm=llm,
                errors=SqliteErrorRepository(db),
                sessions=SqliteSessionRepository(db),
                settings=SqliteSettingsRepository(db),
            )
        )
        resp = c.post("/api/practice/score", json={"text": "I has a cat."})
        assert resp.status_code == 200
        # 两次 LLM 调用：打分（含 dimensions 提示）+ 复盘（含『本次错误』提示）。
        analysis_prompt = next(
            msgs[-1].content for msgs in llm.calls if "本次错误" in msgs[-1].content
        )
        assert "既往未解决错题" not in analysis_prompt
    set_container(Container())
    db.close()


def test_score_409_when_no_llm():
    """无 LLM 配置 → scoring 任务解析失败 → 409 提示去配模型。"""
    db = Database(":memory:")
    with TestClient(app) as c:
        set_container(
            Container(
                errors=SqliteErrorRepository(db),
                sessions=SqliteSessionRepository(db),
                settings=SqliteSettingsRepository(db),
            )
        )
        resp = c.post("/api/practice/score", json={"text": "some essay text here"})
        assert resp.status_code == 409
    set_container(Container())
    db.close()


def test_ended_early_is_recorded(client: TestClient):
    """提前交卷（ADR-005）记进会话 ended_early，不是救场。"""
    resp = client.post(
        "/api/practice/score",
        json={"text": "I has a cat.", "ended_early": True},
    )
    assert resp.status_code == 200
    sessions = client.get("/api/practice").json()
    assert sessions[0]["ended_early"] is True
