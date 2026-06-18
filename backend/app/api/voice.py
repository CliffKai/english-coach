"""语音 WebSocket 路由 —— F2d 口语对话打分的流式管线（L4，docs/02 语音/对话流式）。

一条 WS 连接 = 一场口语对话（考试模式，延迟纠错 ADR-005）。协议（JSON 控制帧 +
二进制音频帧）：

  客户端 → 服务端：
    {"type": "start", "topic": "..."}                        开场（可选 topic）
    <binary audio bytes>                                      用户一轮录音（webm/wav）
    {"type": "submit", "ended_early": true|false}            交卷 → 结算打分
    {"type": "end"}                                          主动结束

  服务端 → 客户端：
    {"type": "ready"}                                        已就绪
    {"type": "transcript", "text": "...", "segments": [...]} 本轮转写（用户说了什么）
    {"type": "reply", "text": "..."}                         考官自然回话（随后是音频）
    {"type": "audio_start"} <binary chunks...> {"type":"audio_end"}  回话 TTS 流式音频
    {"type": "result", ...ScoreResponse}                     交卷结算结果
    {"type": "error", "detail": "..."}                       错误（缺配置等）

每轮把用户转写累积起来；submit 时对累积的**用户话语**整体 settle_exam（复用 F2c 链路，
07 红线：buffer 临时、产出即消费）。发音/流利度：用每轮音频喂 PronunciationProvider，
默认 NoneAdapter → estimated=True → 这些维度空缺并标注（ADR-013）；配了发音 API 才有真分。

无状态约束的例外：WS 天然有连接级会话态，故对话历史/累积转写存在连接内存里（随连接销毁），
不落库——与 HTTP 无状态路由（前端持有历史）互补，不引入服务端持久会话。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from app.adapters.llm import ChatMessage, Role
from app.adapters.speech import PronunciationResult
from app.agents.base import LLMNotConfiguredError
from app.agents.examiner import ExaminerAgent
from app.api import deps
from app.api.practice import settle_exam
from app.container import get_container
from app.models import PracticeMode

router = APIRouter(tags=["voice"])


@router.websocket("/ws/practice/dialogue")
async def dialogue_ws(ws: WebSocket, token: str | None = None) -> None:
    """F2d 语音对话：录音→STT→考官回话→TTS 流式播放；交卷→结算打分。"""
    await ws.accept()
    c = get_container()
    try:
        user = await deps.user_from_token(c, token)
    except HTTPException as exc:
        await ws.send_json({"type": "error", "detail": str(exc.detail)})
        await ws.close()
        return

    # 语音前置：STT/TTS 未配置则告知并关闭（ADR-012：默认走 API，未配为 None）。
    if c.stt is None or c.tts is None:
        await ws.send_json({"type": "error", "detail": "语音未配置（需 STT 与 TTS provider）"})
        await ws.close()
        return

    settings = await deps.load_settings(c)
    try:
        conversation_llm = deps.resolve_llm_or_raise(c, "conversation", settings=settings)
    except LLMNotConfiguredError as exc:
        await ws.send_json({"type": "error", "detail": str(exc)})
        await ws.close()
        return

    examiner = ExaminerAgent(conversation_llm)
    pronunciation = c.pronunciation  # 默认 NoneAdapter（发音维度空缺，ADR-013）

    topic: str | None = None
    history: list[ChatMessage] = []  # 考官/用户来回（驱动 converse 上下文）
    user_turns: list[str] = []  # 累积用户话语（交卷时整体打分）
    # 发音评估按轮累积（多轮取分数均值；NoneAdapter 各轮均 estimated=True）。
    pron_acc: list[float] = []
    pron_flu: list[float] = []
    pron_real = False  # 是否拿到过真实（非估算）发音评估

    await ws.send_json({"type": "ready"})

    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break

            # 二进制 = 用户一轮录音。
            if (audio := msg.get("bytes")) is not None:
                transcript = await c.stt.transcribe(audio)
                await ws.send_json(
                    {
                        "type": "transcript",
                        "text": transcript.text,
                        "segments": transcript.segments,
                    }
                )
                if not transcript.text.strip():
                    continue
                user_turns.append(transcript.text.strip())
                history.append(ChatMessage(role=Role.USER, content=transcript.text.strip()))

                # 发音评估（对照本轮转写）；NoneAdapter 回 estimated=True。
                if pronunciation is not None:
                    pr = await pronunciation.assess(audio, reference_text=transcript.text)
                    if not pr.estimated:
                        pron_real = True
                        if pr.accuracy is not None:
                            pron_acc.append(pr.accuracy)
                        if pr.fluency is not None:
                            pron_flu.append(pr.fluency)

                # 考官自然回话（零纠错，ADR-005）→ 文本 + TTS 流式音频。
                conv = await examiner.converse(
                    transcript.text.strip(),
                    history=history[:-1],  # 不含刚加的本轮（converse 内部会再加）
                    topic=topic,
                    baseline=settings.level_baseline,
                )
                history.append(ChatMessage(role=Role.ASSISTANT, content=conv.reply))
                await ws.send_json({"type": "reply", "text": conv.reply})
                await _stream_tts(ws, c.tts, conv.reply)
                continue

            # 文本控制帧。
            data = msg.get("text")
            if not data:
                continue
            ctrl = _parse_json(data)
            kind = ctrl.get("type")

            if kind == "start":
                topic = ctrl.get("topic") or None
                # 打分标准（雅思/托福）取用户 Settings.scoring_standard（settle_exam 内读取），
                # 不在此按帧覆盖——保持「打分标准是用户配置」的单一来源。
                await ws.send_json({"type": "ready"})

            elif kind == "submit":
                result = await _settle(
                    c,
                    user_id=user.id,
                    user_turns=user_turns,
                    topic=topic,
                    ended_early=bool(ctrl.get("ended_early", False)),
                    pron=_aggregate_pron(pron_real, pron_acc, pron_flu),
                )
                await ws.send_json({"type": "result", **result})
                break

            elif kind == "end":
                break

    except WebSocketDisconnect:
        return
    except LLMNotConfiguredError as exc:
        await _safe_send(ws, {"type": "error", "detail": str(exc)})
    except HTTPException as exc:
        # 结算路径复用 HTTP 助手（settle_exam → require_task_llm）：缺 scoring/reasoning
        # 配置时它抛 HTTPException（如 409）而非 LLMNotConfiguredError。WS 无 HTTP 状态码，
        # 在此翻译成 error 帧告知客户端去配模型，而不是让连接以服务端错误静默关闭。
        await _safe_send(ws, {"type": "error", "detail": str(exc.detail)})
    finally:
        await _safe_close(ws)


async def _settle(c, *, user_id, user_turns, topic, ended_early, pron) -> dict:
    """交卷结算：累积用户话语整体打分 + 错误检测 + 复盘 + 落库（复用 F2c 链路）。"""
    text = "\n".join(user_turns)
    resp = await settle_exam(
        c,
        user_id=user_id,
        text=text,
        mode=PracticeMode.DIALOGUE,
        topic=topic,
        ended_early=ended_early,
        pronunciation=pron,
    )
    # ScoreResponse → 可 JSON 化（pydantic 模型）。
    return resp.model_dump(mode="json")


def _aggregate_pron(real: bool, acc: list[float], flu: list[float]) -> PronunciationResult | None:
    """把多轮发音评估聚合成一个结果喂给打分。无真实评估 → None（维度空缺，ADR-013）。"""
    if not real:
        return None
    return PronunciationResult(
        accuracy=(sum(acc) / len(acc)) if acc else None,
        fluency=(sum(flu) / len(flu)) if flu else None,
        estimated=False,
    )


async def _stream_tts(ws: WebSocket, tts, text: str) -> None:
    """把考官回话 TTS 流式发给客户端（audio_start → 二进制块 → audio_end）。

    audio_start 带上 content_type，让前端按正确解码器播放（mp3→audio/mpeg、
    本地 Piper→audio/wav…），否则浏览器用错解码器会播放失败。
    """
    content_type = getattr(tts, "content_type", "audio/mpeg")
    await ws.send_json({"type": "audio_start", "content_type": content_type})
    async for chunk in tts.stream_synthesize(text):
        await ws.send_bytes(chunk)
    await ws.send_json({"type": "audio_end"})


def _parse_json(data: str) -> dict:
    import json

    try:
        obj = json.loads(data)
        return obj if isinstance(obj, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}


async def _safe_send(ws: WebSocket, payload: dict) -> None:
    try:
        await ws.send_json(payload)
    except RuntimeError:
        pass  # 连接已关，忽略


async def _safe_close(ws: WebSocket) -> None:
    try:
        await ws.close()
    except RuntimeError:
        pass
