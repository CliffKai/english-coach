"""用户配置 + 配置向导支撑路由（L5，ADR-009 配置向导收尾）。

GET  /api/settings        读当前用户配置（含 per-task model_config）；无则返回默认。
PUT  /api/settings        覆盖写用户配置（向导/设置页保存）。
GET  /api/providers       暴露 .env 里已配置的 provider 名（LLM/STT/TTS），**绝不含密钥**，
                          供向导下拉选择「哪个 provider 跑哪个任务」。
POST /api/settings/test-llm  按 provider+model 跑一次最小 chat，验证连通性（向导「测连通」步）。

向导首次引导流程（前端串）：选存储(本地默认) → 配模型 provider/key(.env) → 测连通(本接口)
→ 水平基线测试(复用 /api/baseline) → 保存 model_config(本接口 PUT)。

密钥边界（ADR-006/config.py）：连接凭证只在 AppConfig/.env，绝不入库、绝不经接口返回。
Settings.model_config 只存 provider 名 + model；真正 base_url/api_key 按名在 .env 查得。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.adapters.llm import ChatMessage, Role
from app.adapters.llm_factory import build_for_provider
from app.api import deps
from app.config import get_config
from app.container import Container
from app.models import Settings

router = APIRouter(tags=["settings"])

ContainerDep = Annotated[Container, Depends(deps.container)]


@router.get("/api/settings")
async def get_settings(c: ContainerDep) -> Settings:
    """读当前用户配置；未初始化（首次运行）→ 返回默认 Settings，不报错。"""
    return await deps.load_settings(c)


@router.put("/api/settings")
async def put_settings(payload: Settings, c: ContainerDep) -> Settings:
    """覆盖写用户配置（向导/设置页保存）。无存储则原样回（不持久化）。

    by_alias 入参：前端用 `model_config` 这个外部别名传 per-task 模型分配
    （pydantic 内部字段名 model_config_）；Settings.model_config 设了 populate_by_name，
    两种名都能解析。
    """
    if c.settings is None:
        return payload
    return await c.settings.save(payload)


class ProvidersResponse(BaseModel):
    """已配置 provider 名清单（**不含密钥**，仅供向导选择）。

    名字即 .env 里 ENGLISH_COACH_LLM_PROVIDERS__<名字>__... 的 <名字>，
    与 Settings.model_config 各任务引用的 provider 对应。
    """

    llm: list[str]
    stt: list[str]
    tts: list[str]


@router.get("/api/providers")
def list_providers() -> ProvidersResponse:
    """暴露 .env 里已配置的 provider 名（不泄露 base_url/api_key）。"""
    config = get_config()
    return ProvidersResponse(
        llm=sorted(config.llm_providers),
        stt=sorted(config.stt_providers),
        tts=sorted(config.tts_providers),
    )


class TestLLMRequest(BaseModel):
    """测连通：指定一个已配置的 provider + model，跑一次最小 chat。"""

    provider: str
    model: str


class TestLLMResponse(BaseModel):
    ok: bool
    detail: str  # 成功回模型片段，失败回错误原因（供向导显示）


@router.post("/api/settings/test-llm")
async def test_llm(req: TestLLMRequest) -> TestLLMResponse:
    """向导「测连通」：按 provider 名查 .env 连接信息 → 造适配器 → 发一句最小 prompt。

    成功返回 ok=True + 回复片段；provider 未配置 / 网络 / 鉴权失败都收成 ok=False + 原因，
    不抛 500（向导要把失败原因显示给用户去改 .env）。
    """
    config = get_config()
    if req.provider not in config.llm_providers:
        raise HTTPException(
            status_code=404,
            detail=f"provider {req.provider!r} 未在 .env 配置（见 ENGLISH_COACH_LLM_PROVIDERS）。",
        )
    try:
        llm = build_for_provider(config, req.provider, req.model)
        resp = await llm.chat(
            [ChatMessage(role=Role.USER, content="ping")],
            max_tokens=8,
            temperature=0.0,
        )
    except Exception as exc:  # noqa: BLE001 向导要把任何连通失败原因回给用户
        return TestLLMResponse(ok=False, detail=f"{type(exc).__name__}: {exc}")
    snippet = resp.content.strip()[:80] or "(空回复)"
    return TestLLMResponse(ok=True, detail=f"连通成功，模型回复：{snippet}")
