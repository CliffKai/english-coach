"""TutorAgent —— F2a/2b 引导式写作/口语（L4，练习模式 = 即时纠错 + 脚手架）。

与 ExaminerAgent 正相反（docs/01 功能2 / docs/02）：
  练习模式**当场**纠错并给脚手架引导（不打分、不延迟）——降低焦虑、即时巩固，
  与考试模式「零脚手架、延迟纠错、压力刻意设计」（ADR-005）形成互补的两种训练。

每一轮，Tutor 对用户的英文输出做三件事并**立刻**返回：
  ① corrections：逐条「原句→修正→中文解释」（即时纠错，不进隐藏 buffer，不落错题本——
     错题本是考试模式的产物 F2c/F2d；练习模式重在当场学会，不积累「错题」语义）。
  ② encouragement：一句鼓励 / 做得好的地方（练习模式要正反馈）。
  ③ scaffold：脚手架——继续写/说的引导（追问、可用句型/词、下一步提示），帮用户往下推进。
  ④ follow_up：一句自然的引导性回话（口语模式驱动 TTS；写作模式作提示语）。

不打分（打分是考试模式的事）。LLM 由功能层按 reasoning 任务解析后注入（ADR-006）。
"""

from __future__ import annotations

from pydantic import BaseModel

from app.adapters.llm import ChatMessage, LLMProvider, Role
from app.agents.base import parse_json_object
from app.models import PracticeMode


class Correction(BaseModel):
    """一条即时纠错（不落错题本——练习模式重当场学会，不积累错题语义）。"""

    original: str
    correction: str
    explanation: str = ""  # 中文解释


class TutorTurn(BaseModel):
    """Tutor 一轮的产出：即时纠错 + 鼓励 + 脚手架 + 引导回话。"""

    corrections: list[Correction] = []
    encouragement: str = ""  # 一句鼓励 / 正反馈
    scaffold: str = ""  # 脚手架引导（可用句型/词、追问、下一步）
    follow_up: str = ""  # 自然引导回话（口语驱动 TTS / 写作作提示）


class TutorAgent:
    """F2a/2b 练习模式即时纠错 + 脚手架。reasoning 档模型（ADR-006）。"""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def tutor(
        self,
        text: str,
        *,
        mode: PracticeMode = PracticeMode.GUIDED_WRITE,
        topic: str | None = None,
        baseline: str | None = None,
        history: list[ChatMessage] | None = None,
    ) -> TutorTurn:
        """对用户本轮输出即时纠错 + 给脚手架。空输入 → 只给开场脚手架，不烧 token 纠错。"""
        if not text or not text.strip():
            return TutorTurn(
                scaffold="可以先从一句话开始，围绕话题写/说出你的第一个想法。",
                follow_up=_opening_followup(topic),
            )

        messages = [ChatMessage(role=Role.SYSTEM, content=_system_prompt(mode))]
        if history:
            messages.extend(history)
        messages.append(
            ChatMessage(role=Role.USER, content=_user_prompt(text.strip(), topic, baseline))
        )
        # 纠错要稳（低温），但脚手架/鼓励容许一点自然度，折中取 0.3。
        resp = await self._llm.chat(messages, temperature=0.3)
        return self._parse(resp.content)

    @staticmethod
    def _parse(content: str) -> TutorTurn:
        """解析；失败则回落「无纠错 + 通用鼓励/脚手架」，保证总有可用引导。"""
        try:
            obj = parse_json_object(content)
        except ValueError:
            obj = {}
        corrections: list[Correction] = []
        raw = obj.get("corrections")
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                original = str(item.get("original", "")).strip()
                correction = str(item.get("correction", "")).strip()
                if not original or not correction:
                    continue
                corrections.append(
                    Correction(
                        original=original,
                        correction=correction,
                        explanation=str(item.get("explanation", "")).strip(),
                    )
                )
        return TutorTurn(
            corrections=corrections,
            encouragement=str(obj.get("encouragement", "")).strip(),
            scaffold=str(obj.get("scaffold", "")).strip(),
            follow_up=str(obj.get("follow_up", "")).strip(),
        )


def _system_prompt(mode: PracticeMode) -> str:
    speaking = mode is PracticeMode.GUIDED_SPEAK
    skill = "口语" if speaking else "写作"
    return (
        f"你是耐心、鼓励式的英语{skill}教练，正在做**练习模式**的即时引导（与考试模式相反："
        "当场纠错、给脚手架、不打分、不施压）。学习者母语中文。对学习者本轮的英文输出：\n"
        "1) 逐条找出语言错误并修正，给简短中文解释（corrections）；没有错误就给空数组。\n"
        "2) 一句鼓励 / 指出做得好的地方（encouragement，中文）。\n"
        "3) 脚手架引导（scaffold，中文）：可用的句型/词、如何把想法展开、下一步写/说什么。\n"
        f"4) 一句自然的英文引导回话（follow_up），{'念给学习者听并' if speaking else ''}"
        "引导其继续表达。\n"
        "只输出 JSON，不要任何前后缀说明。"
    )


def _user_prompt(text: str, topic: str | None, baseline: str | None) -> str:
    ctx = ""
    if topic:
        ctx += f"话题：{topic}\n"
    if baseline:
        ctx += f"学习者水平基线（CEFR）：{baseline}\n"
    return (
        f"{ctx}"
        f"学习者本轮英文输出：\n{text}\n\n"
        "请输出 JSON：\n"
        "{\n"
        '  "corrections": [\n'
        '    {"original": "<原句片段>", "correction": "<修正>", "explanation": "<中文解释>"}\n'
        "  ],\n"
        '  "encouragement": "<一句中文鼓励>",\n'
        '  "scaffold": "<中文脚手架引导：句型/词/下一步>",\n'
        '  "follow_up": "<一句自然的英文引导回话>"\n'
        "}\n"
        "无错误则 corrections 为空数组。"
    )


def _opening_followup(topic: str | None) -> str:
    if topic:
        return f"Let's talk about {topic}. What's the first thing that comes to your mind?"
    return "Let's begin. What would you like to talk about?"
