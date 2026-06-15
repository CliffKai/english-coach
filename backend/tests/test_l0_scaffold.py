"""L0 验证（docs/07）：服务能启动 + 健康检查 + 接口可被 mock 注入 + schema 可加载。"""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from app.adapters import ChatMessage, LLMProvider, LLMResponse, Role, WordRepository
from app.container import Container, get_container, set_container
from app.db import load_schema
from app.main import app
from app.models import DEFAULT_USER_ID, FsrsState, Settings, VocabEntry, VocabStatus


# ── 服务能启动 ──────────────────────────────────────────────
def test_app_boots_and_health_ok():
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_meta_reports_feature_flags():
    client = TestClient(app)
    data = client.get("/api/meta").json()
    # L3 起 F1 / F3a / F2c 已接（话题练习 2a/2b/2d 待 L4）。
    # （具体取值随层级推进，权威断言见 test_l3_routes::test_meta_reports_l3_features_on。）
    assert data["features"]["topic_practice"] is True
    assert set(data["features"]) == {
        "vocab_collection",
        "topic_practice",
        "comprehension_review",
    }


# ── 接口可被 mock 注入 ──────────────────────────────────────
class _MockLLM(LLMProvider):
    async def chat(self, messages, *, model=None, temperature=0.7, max_tokens=None):
        return LLMResponse(content="mock-reply", model=model or "mock")

    def stream_chat(self, messages, *, model=None, temperature=0.7, max_tokens=None):
        async def _gen():
            yield "mock-reply"

        return _gen()


def test_llm_interface_is_mock_injectable():
    set_container(Container(llm=_MockLLM()))
    container = get_container()
    assert isinstance(container.llm, LLMProvider)
    # 重置，避免污染其他测试。
    set_container(Container())


def test_chat_message_roundtrip():
    msg = ChatMessage(role=Role.USER, content="hi")
    assert msg.role == Role.USER


def test_word_repository_is_abstract():
    # 接口不可直接实例化——证明它是「接口骨架」而非实现。
    import pytest

    with pytest.raises(TypeError):
        WordRepository()  # type: ignore[abstract]


# ── 领域模型不变量 ──────────────────────────────────────────
def test_vocab_entry_defaults_local_user_and_no_definition():
    v = VocabEntry(word="bank", lemma="bank", context_sentences=["He sat by the river bank."])
    assert v.user_id == DEFAULT_USER_ID
    assert v.status == VocabStatus.NEW
    # ADR-004：没有任何「释义」字段，只有来源句。
    assert not hasattr(v, "definition")
    assert isinstance(v.fsrs_state, FsrsState)


def test_settings_model_config_alias():
    # docs 用字段名 model_config，pydantic 保留该名，内部存为 model_config_，别名读写应通。
    s = Settings(model_config={"scoring": {"provider": "claude", "model": "opus"}})
    assert s.model_config_.scoring is not None
    assert s.model_config_.scoring.provider == "claude"


# ── DB schema 可加载且合法 ──────────────────────────────────
def test_schema_creates_four_tables_with_user_id():
    ddl = load_schema()
    conn = sqlite3.connect(":memory:")
    conn.executescript(ddl)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"vocab_entries", "error_entries", "practice_sessions", "settings"} <= tables

    # 四张表都带 user_id（ADR-007）。
    for table in ["vocab_entries", "error_entries", "practice_sessions", "settings"]:
        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        assert "user_id" in cols, f"{table} 缺少 user_id"
    conn.close()
