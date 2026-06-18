"""句子精读验证：SentenceAnalysisAgent + /api/sentence/analyze。

全程离线 mock LLM；第一版只做即时分析，不落库。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.adapters.llm import LLMResponse
from app.agents.sentence_analysis import SentenceAnalysisAgent
from app.container import Container, set_container
from app.main import app


class FakeLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[tuple[list, float]] = []

    async def chat(self, messages, *, model=None, temperature=0.7, max_tokens=None):
        self.calls.append((messages, temperature))
        return LLMResponse(content=self.reply, model=model or "fake")

    def stream_chat(self, messages, *, model=None, temperature=0.7, max_tokens=None):
        async def _gen():
            yield self.reply

        return _gen()


_REPLY = json.dumps(
    {
        "translation_zh": "尽管雨下得很大，我们还是继续徒步。",
        "literal_translation": "虽然它正在下大雨，我们继续了这次徒步。",
        "structure": "Although 引导让步状语从句，主句是 we continued the hike。",
        "grammar_points": [
            {
                "title": "让步状语从句",
                "explanation": "Although 表示“尽管”，从句放句首时后面通常用逗号隔开。",
                "example": "Although it was late, we kept working.",
            }
        ],
        "vocabulary_notes": [
            {"term": "continued", "meaning": "继续", "note": "后面可直接接名词或动名词。"}
        ],
        "phrase_notes": [
            {"phrase": "the hike", "meaning": "这次徒步", "note": "hike 是徒步旅行。"}
        ],
        "common_pitfalls": ["不要把 although 和 but 连用成 Although ..., but ...。"],
        "rewrites": [{"style": "更简单", "text": "It was raining hard, but we kept hiking."}],
        "takeaways": ["学习 although 引导的让步关系。"],
        "exercise": "用 Although 仿写一句。",
    }
)


@pytest.mark.asyncio
async def test_sentence_analysis_agent_parses_structured_result():
    llm = FakeLLM(_REPLY)
    result = await SentenceAnalysisAgent(llm).analyze(
        "Although it was raining heavily, we continued the hike.",
        baseline="B1",
    )

    assert result.translation_zh == "尽管雨下得很大，我们还是继续徒步。"
    assert result.grammar_points[0].title == "让步状语从句"
    assert result.vocabulary_notes[0].term == "continued"
    assert result.phrase_notes[0].term == "the hike"
    assert result.rewrites[0].text.startswith("It was raining")
    messages, temperature = llm.calls[0]
    assert temperature == 0.2
    assert "B1" in messages[-1].content


def test_sentence_analysis_route_returns_analysis():
    llm = FakeLLM(_REPLY)
    with TestClient(app) as c:
        set_container(Container(llm=llm))
        resp = c.post(
            "/api/sentence/analyze",
            json={"sentence": "Although it was raining heavily, we continued the hike."},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["translation_zh"] == "尽管雨下得很大，我们还是继续徒步。"
        assert body["grammar_points"][0]["title"] == "让步状语从句"
        assert body["vocabulary_notes"][0]["term"] == "continued"
    set_container(Container())


def test_sentence_analysis_route_409_when_no_llm():
    with TestClient(app) as c:
        set_container(Container())
        resp = c.post("/api/sentence/analyze", json={"sentence": "This is a test."})
        assert resp.status_code == 409
    set_container(Container())


def test_sentence_analysis_route_rejects_empty_sentence():
    with TestClient(app) as c:
        set_container(Container(llm=FakeLLM(_REPLY)))
        resp = c.post("/api/sentence/analyze", json={"sentence": "   "})
        assert resp.status_code == 422
    set_container(Container())
