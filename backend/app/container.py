"""依赖注入容器（DI）。

L0 的验证标准之一：「接口可被 mock 注入」。这里提供一个极简容器，持有各适配器
接口的当前实现引用；路由通过 FastAPI Depends 取用。L0 默认全部为 None（未绑定），
测试可注入 mock，L1 注入真实适配器。

刻意保持简单——不引第三方 DI 框架，避免脚手架期过度设计。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.adapters import (
    ErrorRepository,
    LLMProvider,
    PronunciationProvider,
    SessionRepository,
    SettingsRepository,
    STTProvider,
    TTSProvider,
    UserRepository,
    WordRepository,
)
from app.nlp import Tokenizer
from app.scheduling import Scheduler


@dataclass
class Container:
    """适配器/服务实现的持有者。字段为接口类型，值在启动/测试时绑定。"""

    llm: LLMProvider | None = None
    words: WordRepository | None = None
    errors: ErrorRepository | None = None
    sessions: SessionRepository | None = None
    settings: SettingsRepository | None = None
    users: UserRepository | None = None
    stt: STTProvider | None = None
    tts: TTSProvider | None = None
    pronunciation: PronunciationProvider | None = None
    # L2 服务：切词/词频过滤（F1 与水平基线用）、FSRS 调度（F3 用）。
    tokenizer: Tokenizer | None = None
    scheduler: Scheduler | None = None


# 进程级单例。L1 在 app 启动钩子里填充；测试直接替换字段或整个对象。
_container = Container()


def get_container() -> Container:
    return _container


def set_container(container: Container) -> None:
    """整体替换容器（测试用）。"""
    global _container
    _container = container
