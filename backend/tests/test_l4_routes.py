"""L4 路由验证（docs/07）：F2a/2b 引导 /tutor、F2d 文本对话 /dialogue/turn、
F3b 造句 /review/passage(/check)、voice WS 未配置语音时的优雅拒绝。

用 TestClient + 注入 mock 容器（FakeLLM + 内存 SQLite），全程离线。
"""

from __future__ import annotations

import json

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
from app.models import VocabEntry
from app.scheduling import FsrsScheduler


class FakeLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[list] = []

    async def chat(self, messages, *, model=None, temperature=0.7, max_tokens=None):
        self.calls.append(messages)
        return LLMResponse(content=self.reply, model=model or "fake")

    def stream_chat(self, messages, *, model=None, temperature=0.7, max_tokens=None):
        async def _gen():
            yield self.reply

        return _gen()


def _container(reply: str) -> tuple[Container, Database]:
    db = Database(":memory:")
    return (
        Container(
            llm=FakeLLM(reply),
            words=SqliteWordRepository(db),
            errors=SqliteErrorRepository(db),
            sessions=SqliteSessionRepository(db),
            settings=SqliteSettingsRepository(db),
            scheduler=FsrsScheduler(),
        ),
        db,
    )


# ── F2a/2b /tutor ───────────────────────────────────────────────────
_TUTOR_REPLY = json.dumps(
    {
        "corrections": [{"original": "I goes", "correction": "I go", "explanation": "主谓一致"}],
        "encouragement": "不错！",
        "scaffold": "补个例子。",
        "follow_up": "Why?",
    }
)


def test_tutor_route_returns_corrections():
    container, db = _container(_TUTOR_REPLY)
    with TestClient(app) as c:
        set_container(container)
        resp = c.post(
            "/api/practice/tutor",
            json={"text": "I goes to school.", "mode": "guided_write", "topic": "school"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["corrections"][0]["correction"] == "I go"
        assert body["scaffold"] and body["follow_up"]
    set_container(Container())
    db.close()


def test_tutor_route_rejects_exam_mode():
    container, db = _container(_TUTOR_REPLY)
    with TestClient(app) as c:
        set_container(container)
        resp = c.post("/api/practice/tutor", json={"text": "hi", "mode": "free_write"})
        assert resp.status_code == 400
    set_container(Container())
    db.close()


# ── F2d 文本对话 /dialogue/turn ────────────────────────────────────
def test_dialogue_turn_returns_reply():
    container, db = _container("Tell me more about that.")
    with TestClient(app) as c:
        set_container(container)
        resp = c.post(
            "/api/practice/dialogue/turn",
            json={
                "message": "I traveled to Japan.",
                "history": [{"role": "assistant", "content": "Hello!"}],
                "topic": "travel",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["reply"] == "Tell me more about that."
    set_container(Container())
    db.close()


def test_practice_topic_suggests_editable_topic():
    container, db = _container(json.dumps({"topic": "Should students learn how to use AI tools at school?"}))
    with TestClient(app) as c:
        set_container(container)
        resp = c.post("/api/practice/topic", json={"mode": "guided_write"})
        assert resp.status_code == 200
        assert resp.json() == {
            "topic": "Should students learn how to use AI tools at school?"
        }
        prompt = container.llm.calls[0][-1].content
        assert "guided writing" in prompt
    set_container(Container())
    db.close()


def test_practice_topic_409_when_no_llm():
    db = Database(":memory:")
    with TestClient(app) as c:
        set_container(Container(settings=SqliteSettingsRepository(db)))
        resp = c.post("/api/practice/topic", json={"mode": "free_write"})
        assert resp.status_code == 409
    set_container(Container())
    db.close()


# ── F3b /review/passage + /review/passage/check ────────────────────
def test_passage_make_and_check_advances_fsrs():
    passage_reply = json.dumps(
        {"text": "An obscure idea became ubiquitous.", "words_used": ["obscure", "ubiquitous"]}
    )
    import asyncio

    container, db = _container(passage_reply)

    async def _seed():
        await container.words.add(
            VocabEntry(word="obscure", lemma="obscure", context_sentences=["s1"])
        )
        await container.words.add(
            VocabEntry(word="ubiquitous", lemma="ubiquitous", context_sentences=["s2"])
        )

    asyncio.run(_seed())

    with TestClient(app) as c:
        set_container(container)
        # 造短文。
        resp = c.post("/api/review/passage", json={"limit": 5, "topic": "tech"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["text"]
        lemmas = [w["lemma"] for w in body["words"]]
        assert set(lemmas) == {"obscure", "ubiquitous"}

        # 检验翻译 → 推进 FSRS。
        check_reply = json.dumps(
            {
                "checks": [
                    {"word": "obscure", "verdict": "correct"},
                    {"word": "ubiquitous", "verdict": "partial"},
                ]
            }
        )
        container.llm.reply = check_reply
        resp2 = c.post(
            "/api/review/passage/check",
            json={
                "passage": body["text"],
                "lemmas": lemmas,
                "translation": "一个冷门的想法变得无处不在。",
            },
        )
        assert resp2.status_code == 200
        checks = resp2.json()["checks"]
        by_word = {ch["lemma"]: ch for ch in checks}
        # correct → GOOD(3)；partial → HARD(2)。
        assert by_word["obscure"]["rating"] == 3
        assert by_word["ubiquitous"]["rating"] == 2
        # 推进后 status 脱离 new。
        assert by_word["obscure"]["status"] == "learning"
    set_container(Container())
    db.close()


def test_passage_no_due_words_returns_empty():
    container, db = _container("{}")
    with TestClient(app) as c:
        set_container(container)
        resp = c.post("/api/review/passage", json={"limit": 5})
        assert resp.status_code == 200
        assert resp.json()["text"] == ""
    set_container(Container())
    db.close()


# ── 语音 WS 未配置 STT/TTS → 优雅拒绝（ADR-012）───────────────────
def test_voice_ws_without_stt_tts_sends_error():
    container, db = _container("{}")  # 无 stt/tts
    with TestClient(app) as c:
        set_container(container)
        with c.websocket_connect("/ws/practice/dialogue") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "语音未配置" in msg["detail"]
    set_container(Container())
    db.close()


class _FakeSTT:
    async def transcribe(self, audio, *, language=None):
        from app.adapters.speech import Transcript

        return Transcript(text="I like travel.", segments=[])


class _FakeTTS:
    content_type = "audio/wav"  # 模拟本地 Piper（非 mp3）

    async def synthesize(self, text, *, voice=None):
        return b"RIFFfake"

    async def stream_synthesize(self, text, *, voice=None):
        yield b"RIFFfake"


def test_voice_ws_submit_httpexception_becomes_error_frame(monkeypatch):
    """结算时缺 scoring/reasoning 配置：settle_exam 经 require_task_llm 抛 HTTPException（非
    LLMNotConfiguredError）。WS 须把它翻译成 error 帧告知客户端，而非让连接以服务端错误静默
    关闭（回归测试，对应 review P2）。

    用默认 llm 让对话（conversation）正常解析，再 monkeypatch settle_exam 抛 HTTPException
    模拟「conversation 配了但 scoring/reasoning 没配」的分叉配置——精准隔离提交路径的异常处理。
    """
    from fastapi import HTTPException

    from app.api import voice as voice_mod

    async def _boom(*args, **kwargs):
        raise HTTPException(status_code=409, detail="任务 scoring 无可用模型：请配置 provider。")

    monkeypatch.setattr(voice_mod, "settle_exam", _boom)

    container, db = _container("Tell me more.")  # 默认 llm → conversation 可解析
    container.stt = _FakeSTT()
    container.tts = _FakeTTS()
    with TestClient(app) as c:
        set_container(container)
        with c.websocket_connect("/ws/practice/dialogue") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "submit", "ended_early": True})
            # 不应崩溃关连接，而应收到 error 帧（翻译自 HTTPException.detail）。
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "scoring" in msg["detail"]
    set_container(Container())
    db.close()


def test_voice_ws_audio_start_carries_content_type(monkeypatch):
    """audio_start 帧须带 TTS 的 content_type（本地 Piper 出 WAV，非 mp3）——前端据此选解码器
    （回归测试，对应 review P2）。"""
    container, db = _container("Tell me more.")  # 默认 llm → conversation 可解析
    container.stt = _FakeSTT()
    container.tts = _FakeTTS()  # content_type=audio/wav
    with TestClient(app) as c:
        set_container(container)
        with c.websocket_connect("/ws/practice/dialogue") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_bytes(b"fake-audio")
            # transcript → reply → audio_start(带 content_type) → 二进制块 → audio_end。
            assert ws.receive_json()["type"] == "transcript"
            assert ws.receive_json()["type"] == "reply"
            start = ws.receive_json()
            assert start["type"] == "audio_start"
            assert start["content_type"] == "audio/wav"  # 非硬编码 mp3
    set_container(Container())
    db.close()
