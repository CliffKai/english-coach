"""L5 验证：日常闭环 / 开源落地（docs/07 L5）。

覆盖：
- 「今日学习」聚合首页 /api/today（待复习生词 + 待巩固错题 + 推荐话题）。
- 数据导入/导出：JSON 全量往返 + Anki CSV（卡背=来源句+理解，不含释义，ADR-014）。
- 配置：settings 读写 + provider 列表（不泄密钥）+ test-llm 连通。

沿用现有风格：TestClient + 注入 mock 容器（FakeLLM + 内存 SQLite + 真实 scheduler），全程离线。
"""

from __future__ import annotations

import csv
import io

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
from app.models import (
    ErrorEntry,
    ErrorType,
    PracticeMode,
    PracticeSession,
    Settings,
    VocabEntry,
)
from app.models.entities import UserUnderstanding
from app.scheduling import FsrsScheduler


class FakeLLM:
    """恒回固定文本的 LLM（测 test-llm 连通用）。"""

    def __init__(self, reply: str = "pong") -> None:
        self.reply = reply

    async def chat(self, messages, *, model=None, temperature=0.7, max_tokens=None):
        return LLMResponse(content=self.reply, model=model or "fake")

    def stream_chat(self, messages, *, model=None, temperature=0.7, max_tokens=None):
        async def _gen():
            yield self.reply

        return _gen()


def _make_container(db: Database, *, llm=None) -> Container:
    return Container(
        llm=llm,
        words=SqliteWordRepository(db),
        errors=SqliteErrorRepository(db),
        sessions=SqliteSessionRepository(db),
        settings=SqliteSettingsRepository(db),
        scheduler=FsrsScheduler(),
    )


@pytest.fixture
def client():
    """注入「有存储、无 LLM」容器（多数 L5 接口不调 LLM）。

    注意：lifespan 会先绑真实适配器，故在进入 TestClient 上下文之后再注入 mock 容器。
    """
    db = Database(":memory:")
    container = _make_container(db)
    with TestClient(app) as c:
        set_container(container)
        yield c, container
    set_container(Container())
    db.close()


# ── 今日学习聚合 ────────────────────────────────────────────────
def test_today_empty(client):
    """上游全空 → 各计数 0、预览空、推荐话题回落到内置池（rotating）。"""
    c, _ = client
    body = c.get("/api/today").json()
    assert body["due_count"] == 0
    assert body["unresolved_error_count"] == 0
    assert body["due_preview"] == [] and body["error_preview"] == []
    # 无未解决错题 → 回落内置池轮换。
    assert body["recommended_topic"]["reason"] == "rotating"
    assert body["recommended_topic"]["topic"]


@pytest.mark.asyncio
async def test_today_aggregates_due_and_errors(client):
    """有生词 + 未解决错题 → 计数/预览正确，推荐取错题最多的话题（weak_area）。"""
    c, container = client
    # 两个新词（未排程 → 立即到期）。
    await container.words.add(VocabEntry(word="ephemeral", lemma="ephemeral",
                                         context_sentences=["It was ephemeral."]))
    await container.words.add(VocabEntry(word="ubiquitous", lemma="ubiquitous",
                                         context_sentences=["Phones are ubiquitous."]))
    # 三条未解决错题：topic "Education" 两条、"Travel" 一条 → 推荐 Education。
    await container.errors.add_many([
        ErrorEntry(type=ErrorType.GRAMMAR, original="he go", correction="he goes",
                   explanation="", topic="Education"),
        ErrorEntry(type=ErrorType.SPELLING, original="recieve", correction="receive",
                   explanation="", topic="Education"),
        ErrorEntry(type=ErrorType.LOGIC, original="x", correction="y",
                   explanation="", topic="Travel"),
    ])
    # 一条已解决错题：不应计入待巩固。
    await container.errors.add(ErrorEntry(type=ErrorType.VOCABULARY, original="a", correction="b",
                                          explanation="", topic="Education", resolved=True))

    body = c.get("/api/today").json()
    assert body["due_count"] == 2
    assert {w["word"] for w in body["due_preview"]} == {"ephemeral", "ubiquitous"}
    assert body["unresolved_error_count"] == 3  # 已解决的那条被排除
    assert body["recommended_topic"]["reason"] == "weak_area"
    assert body["recommended_topic"]["topic"] == "Education"


# ── 配置 / 向导 ────────────────────────────────────────────────
def test_settings_get_default_then_put(client):
    """无配置 → 默认 Settings；PUT 覆盖写 → 再 GET 生效。"""
    c, _ = client
    got = c.get("/api/settings").json()
    assert got["level_baseline"] is None
    assert got["scoring_standard"] == "IELTS"

    got["level_baseline"] = "B2"
    got["target_band"] = 7.0
    # per-task 模型分配走外部别名 model_config。
    got["model_config"]["scoring"] = {"provider": "deepseek", "model": "deepseek-chat"}
    saved = c.put("/api/settings", json=got).json()
    assert saved["level_baseline"] == "B2"

    reread = c.get("/api/settings").json()
    assert reread["level_baseline"] == "B2"
    assert reread["target_band"] == 7.0
    assert reread["model_config"]["scoring"]["provider"] == "deepseek"


def test_providers_lists_names_without_secrets(client, monkeypatch):
    """/api/providers 只回 provider 名，绝不含 base_url/api_key。"""
    from app.config import AppConfig, LLMProviderConnection, get_config

    fake = AppConfig(
        llm_providers={
            "deepseek": LLMProviderConnection(base_url="http://secret/v1", api_key="sk-SECRET"),
            "claude": LLMProviderConnection(kind="claude", api_key="sk-ant-SECRET"),
        }
    )
    monkeypatch.setattr("app.api.settings.get_config", lambda: fake)
    c, _ = client
    resp = c.get("/api/providers")
    body = resp.json()
    assert body["llm"] == ["claude", "deepseek"]  # 排序
    # 密钥/连接信息绝不出现在响应里。
    assert "SECRET" not in resp.text
    assert "secret" not in resp.text

    get_config.cache_clear()


def test_test_llm_404_when_provider_missing(client, monkeypatch):
    """test-llm 指定未配置的 provider → 404。"""
    from app.config import AppConfig

    monkeypatch.setattr("app.api.settings.get_config", lambda: AppConfig(llm_providers={}))
    c, _ = client
    resp = c.post("/api/settings/test-llm", json={"provider": "nope", "model": "x"})
    assert resp.status_code == 404


def test_test_llm_ok_with_configured_provider(client, monkeypatch):
    """provider 已配 + 适配器可跑 → ok=True，回复片段带在 detail。"""
    from app.config import AppConfig, LLMProviderConnection

    monkeypatch.setattr(
        "app.api.settings.get_config",
        lambda: AppConfig(
            llm_providers={"local": LLMProviderConnection(base_url="http://x/v1", api_key="k")}
        ),
    )
    # build_for_provider 会造真实 OpenAICompatAdapter；patch 成 FakeLLM 免真实网络。
    monkeypatch.setattr("app.api.settings.build_for_provider", lambda *a, **k: FakeLLM("pong"))
    c, _ = client
    resp = c.post("/api/settings/test-llm", json={"provider": "local", "model": "m"})
    body = resp.json()
    assert body["ok"] is True
    assert "pong" in body["detail"]


def test_test_llm_reports_failure_not_500(client, monkeypatch):
    """连通失败（适配器抛错）→ ok=False + 原因，不冒成 500（向导要显示原因）。"""
    from app.config import AppConfig, LLMProviderConnection

    monkeypatch.setattr(
        "app.api.settings.get_config",
        lambda: AppConfig(
            llm_providers={"local": LLMProviderConnection(base_url="http://x/v1")}
        ),
    )

    class Boom:
        async def chat(self, *a, **k):
            raise RuntimeError("connection refused")

        def stream_chat(self, *a, **k):  # pragma: no cover - 不会被调用
            raise RuntimeError

    monkeypatch.setattr("app.api.settings.build_for_provider", lambda *a, **k: Boom())
    c, _ = client
    resp = c.post("/api/settings/test-llm", json={"provider": "local", "model": "m"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "connection refused" in body["detail"]


# ── 导入 / 导出 ────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_export_json_then_import_roundtrip(client):
    """全量导出 → 清空 → 覆盖导入 → 数据原样回来（无损往返）。"""
    c, container = client
    # 造数据：生词（含理解历史）+ 会话 + 挂会话的错题 + 配置。
    session = PracticeSession(mode=PracticeMode.FREE_WRITE, topic="Education", transcript="hi")
    await container.sessions.add(session)
    await container.errors.add(ErrorEntry(type=ErrorType.GRAMMAR, original="he go",
                                          correction="he goes", explanation="时态",
                                          session_id=session.id, topic="Education"))
    v = VocabEntry(word="ephemeral", lemma="ephemeral", context_sentences=["It was ephemeral."],
                   user_understanding=[UserUnderstanding(text="短暂的")])
    await container.words.add(v)
    s = await container.settings.get() or Settings()
    s.level_baseline = "B2"
    await container.settings.save(s)

    # 导出。
    bundle = c.get("/api/export/json").json()
    assert len(bundle["vocab"]) == 1
    assert len(bundle["errors"]) == 1
    assert len(bundle["sessions"]) == 1
    assert bundle["settings"]["level_baseline"] == "B2"

    # 覆盖导入回同一库（replace=True 先清空再写）→ 计数与字段不变。
    result = c.post("/api/import/json", json={"bundle": bundle, "replace": True}).json()
    assert result["vocab_imported"] == 1
    assert result["errors_imported"] == 1
    assert result["sessions_imported"] == 1
    assert result["settings_imported"] is True

    # 校验往返无损：生词理解历史、错题外键、基线都在。
    vocab = c.get("/api/vocab").json()
    assert len(vocab) == 1 and vocab[0]["lemma"] == "ephemeral"
    errs = c.get("/api/errors").json()
    assert len(errs) == 1 and errs[0]["original"] == "he go"
    assert c.get("/api/settings").json()["level_baseline"] == "B2"


def test_import_merge_skips_existing(client):
    """合并模式（replace=False）：与现有 id 冲突的条目跳过，不抢覆盖。"""
    c, _ = client
    bundle = {
        "version": 1,
        "vocab": [
            {"id": "v1", "word": "alpha", "lemma": "alpha", "context_sentences": ["a"]},
        ],
        "errors": [],
        "sessions": [],
        "settings": None,
    }
    first = c.post("/api/import/json", json={"bundle": bundle, "replace": False}).json()
    assert first["vocab_imported"] == 1
    # 再导一次同 id → 跳过。
    second = c.post("/api/import/json", json={"bundle": bundle, "replace": False}).json()
    assert second["vocab_imported"] == 0
    assert second["skipped"] == 1
    # 库里仍只有一条。
    assert len(c.get("/api/vocab").json()) == 1


@pytest.mark.asyncio
async def test_import_merges_same_lemma_different_id(client):
    """合并不同安装的备份：新 id、同 (user_id, lemma) → 并入来源句，不撞唯一索引崩 500。"""
    c, container = client
    # 库里已有 ephemeral（含一条来源句 + 一条理解）。
    await container.words.add(VocabEntry(
        word="ephemeral", lemma="ephemeral",
        context_sentences=["It was ephemeral."],
        user_understanding=[UserUnderstanding(text="短暂的")],
    ))
    # 另一台机器的备份：同 lemma 但不同 id、不同来源句/理解。
    bundle = {
        "version": 1,
        "vocab": [
            {
                "id": "fresh-id-xyz",  # 与现有不同
                "word": "ephemeral",
                "lemma": "ephemeral",
                "context_sentences": ["The beauty was ephemeral."],
                "user_understanding": [{"text": "转瞬即逝"}],
            },
        ],
        "errors": [],
        "sessions": [],
        "settings": None,
    }
    resp = c.post("/api/import/json", json={"bundle": bundle, "replace": False})
    assert resp.status_code == 200  # 不再 500
    body = resp.json()
    assert body["vocab_imported"] == 0
    assert body["vocab_merged"] == 1

    # 库里仍是一条（按 lemma 唯一），来源句与理解都已并入。
    vocab = c.get("/api/vocab").json()
    assert len(vocab) == 1
    assert set(vocab[0]["context_sentences"]) == {"It was ephemeral.", "The beauty was ephemeral."}


@pytest.mark.asyncio
async def test_import_same_lemma_no_new_content_skips(client):
    """同 lemma 且无新增来源句/理解 → 计入 skipped，不产生空更新。"""
    c, container = client
    await container.words.add(VocabEntry(
        word="ephemeral", lemma="ephemeral", context_sentences=["It was ephemeral."],
    ))
    bundle = {
        "version": 1,
        "vocab": [{
            "id": "another-id",
            "word": "ephemeral",
            "lemma": "ephemeral",
            "context_sentences": ["It was ephemeral."],  # 与现有相同
        }],
        "errors": [], "sessions": [], "settings": None,
    }
    body = c.post("/api/import/json", json={"bundle": bundle, "replace": False}).json()
    assert body["vocab_imported"] == 0
    assert body["vocab_merged"] == 0
    assert body["skipped"] == 1


def test_import_rejects_incompatible_version(client):
    """备份版本不符 → 422，不静默吞。"""
    c, _ = client
    bundle = {"version": 999, "vocab": [], "errors": [], "sessions": [], "settings": None}
    resp = c.post("/api/import/json", json={"bundle": bundle, "replace": False})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_export_anki_csv_back_has_context_and_understanding_no_definition(client):
    """Anki CSV：正面=word；卡背=来源句+理解，绝不含释义（ADR-014）。"""
    c, container = client
    await container.words.add(VocabEntry(
        word="ephemeral", lemma="ephemeral",
        context_sentences=["Ephemeral apps are a trend.", "The beauty was ephemeral."],
        user_understanding=[UserUnderstanding(text="短暂的、转瞬即逝的")],
    ))
    resp = c.get("/api/export/anki")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert "attachment" in resp.headers["content-disposition"]

    rows = list(csv.reader(io.StringIO(resp.text)))
    assert rows[0] == ["Front", "Back"]
    front, back = rows[1]
    assert front == "ephemeral"
    # 卡背含来源句区 + 理解区。
    assert "【来源句】" in back
    assert "Ephemeral apps are a trend." in back
    assert "The beauty was ephemeral." in back
    assert "【我的理解】" in back
    assert "短暂的、转瞬即逝的" in back


@pytest.mark.asyncio
async def test_export_anki_csv_back_without_understanding(client):
    """从未复习的词：卡背只有来源句区，无理解区，仍可导出。"""
    c, container = client
    await container.words.add(VocabEntry(word="quaint", lemma="quaint",
                                         context_sentences=["A quaint village."]))
    resp = c.get("/api/export/anki")
    rows = list(csv.reader(io.StringIO(resp.text)))
    _, back = rows[1]
    assert "【来源句】" in back
    assert "A quaint village." in back
    assert "【我的理解】" not in back


def test_meta_setup_status(client):
    """/api/meta 暴露配置向导状态：无 LLM/无基线 → needs_wizard=True。"""
    c, _ = client
    setup = c.get("/api/meta").json()["setup"]
    # 容器无 llm 且测试环境通常无 .env provider → 缺模型。
    assert setup["has_baseline"] is False
    assert setup["needs_wizard"] is True


def test_meta_needs_wizard_when_only_openai_provider_unassigned(client, monkeypatch):
    """回归：只配了 OpenAI 兼容 provider（如 DeepSeek/Ollama）、没在 model_config 给任务分配时，
    scoring 仍解析不出模型（build_default_llm 只对 Claude 回非 None）→ has_llm_provider 必须为
    False、needs_wizard 为 True。修复前用 bool(config.llm_providers) 会误报「已配好」。"""
    from app.config import AppConfig, LLMProviderConnection, get_config

    fake = AppConfig(
        llm_providers={"deepseek": LLMProviderConnection(base_url="http://x/v1", api_key="k")}
    )
    # deps.resolve_llm_or_raise 经 get_config() 读 provider（meta 走真实解析路径判断）。
    monkeypatch.setattr("app.api.deps.get_config", lambda: fake)
    c, _ = client
    setup = c.get("/api/meta").json()["setup"]
    assert setup["has_llm_provider"] is False
    assert setup["needs_wizard"] is True
    get_config.cache_clear()


@pytest.mark.asyncio
async def test_meta_has_llm_provider_when_scoring_assigned(client, monkeypatch):
    """配了 OpenAI 兼容 provider 且 Settings.model_config.scoring 指向它 → scoring 能解析出模型
    → has_llm_provider=True。再补上基线则 needs_wizard=False。"""
    from app.config import AppConfig, LLMProviderConnection, get_config
    from app.models.entities import ModelAssignment

    fake = AppConfig(
        llm_providers={"deepseek": LLMProviderConnection(base_url="http://x/v1", api_key="k")}
    )
    monkeypatch.setattr("app.api.deps.get_config", lambda: fake)
    c, container = client
    # 给 scoring 分配该 provider + 补基线。
    s = await container.settings.get() or Settings()
    s.model_config_.scoring = ModelAssignment(provider="deepseek", model="deepseek-chat")
    s.level_baseline = "B2"
    await container.settings.save(s)

    setup = c.get("/api/meta").json()["setup"]
    assert setup["has_llm_provider"] is True
    assert setup["has_baseline"] is True
    assert setup["needs_wizard"] is False
    get_config.cache_clear()
