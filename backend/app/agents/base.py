"""Agent 公共件：按任务挑模型 + 解析 LLM 的 JSON 输出。

按任务分配模型（ADR-006）的落地点在这里：Agent 不自己 new 适配器，而是声明
「我要 scoring / reasoning / tokenize / conversation 哪档」，由 resolve_task_llm
按 Settings.model_config 选 provider+model，回落到容器里的默认 LLM。
"""

from __future__ import annotations

import json
import re
from typing import Literal

from app.adapters.llm import LLMProvider
from app.adapters.llm_factory import build_for_provider
from app.config import AppConfig
from app.models import Settings

# 任务键，对齐 ModelConfig 的四个字段（docs/02 模型按任务分配）。
TaskKind = Literal["scoring", "reasoning", "tokenize", "conversation"]


class LLMNotConfiguredError(RuntimeError):
    """该任务既无 per-task 模型分配、容器也无默认 LLM —— 提示用户去配置向导配模型。"""


def resolve_task_llm(
    task: TaskKind,
    *,
    settings: Settings | None,
    config: AppConfig,
    default_llm: LLMProvider | None,
) -> LLMProvider:
    """为某任务选定 LLM。

    优先级：Settings.model_config 里该任务的显式分配（provider+model，按名查连接信息）
    → 否则用容器绑定的默认 LLM（L1 build_default_llm，通常是 Claude）。
    都没有则抛 LLMNotConfiguredError（功能层转成 400/409 提示去配模型）。
    """
    assignment = None
    if settings is not None:
        assignment = getattr(settings.model_config_, task, None)
    if assignment is not None:
        try:
            return build_for_provider(config, assignment.provider, assignment.model)
        except KeyError as exc:
            # provider 在 Settings.model_config 里被引用，却不在 AppConfig.llm_providers
            # （未配 / 拼错 / 与环境变量名大小写不符）。这是配置问题，转成 LLMNotConfiguredError
            # 让功能层回 409，而非 build_for_provider 的裸 KeyError 冒成 500。
            raise LLMNotConfiguredError(
                f"任务 {task} 指定的 provider {assignment.provider!r} 未在环境配置中找到："
                "请检查 ENGLISH_COACH_LLM_PROVIDERS__<NAME>__... 是否配置、名称大小写是否一致。"
            ) from exc
    if default_llm is not None:
        return default_llm
    raise LLMNotConfiguredError(
        f"任务 {task} 无可用模型：请为该任务分配 provider/model，或配置一个默认 Claude provider。"
    )


# ```json ... ``` 代码围栏：不少模型会把 JSON 包在 markdown 里，先扒掉。
_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def parse_json_object(text: str) -> dict:
    """从 LLM 文本里抠出一个 JSON 对象。

    依次尝试：整体直接 parse → 去 markdown 围栏 → 截取第一个 `{` 到最后一个 `}`。
    LLM 输出不保证纯净（前后常带说明文字），故容错解析而非严格要求。
    解析不出抛 ValueError，调用方决定回退策略。
    """
    candidates: list[str] = [text.strip()]
    m = _FENCE.search(text)
    if m:
        candidates.append(m.group(1).strip())
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])

    for cand in candidates:
        try:
            obj = json.loads(cand)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict):
            return obj
    raise ValueError(f"无法从 LLM 输出解析出 JSON 对象：{text[:200]!r}")
