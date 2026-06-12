"""L1 验证：app 启动后容器绑定真实适配器（SQLite Repo + None 发音）。

用 TestClient 触发 lifespan（绑定/收尾），用临时 DB 路径避免污染 data/。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.adapters import (
    NonePronunciationAdapter,
    SqliteSettingsRepository,
    SqliteWordRepository,
)
from app.config import get_config
from app.container import get_container, set_container


def test_lifespan_binds_local_adapters(tmp_path, monkeypatch):
    # 用临时 DB，避免写入真实 data/。
    monkeypatch.setenv(
        "ENGLISH_COACH_DATABASE_URL", f"sqlite:///{tmp_path / 'l1_test.db'}"
    )
    get_config.cache_clear()

    # main 在导入时读 config，需在 patch 后重导入。
    import importlib

    import app.main as main

    importlib.reload(main)

    with TestClient(main.app):
        c = get_container()
        assert isinstance(c.words, SqliteWordRepository)
        assert isinstance(c.settings, SqliteSettingsRepository)
        assert isinstance(c.pronunciation, NonePronunciationAdapter)
        # 无 LLM 配置 → llm 未绑定（功能层用到时再报）。
        assert c.llm is None
        # STT/TTS 推迟到 L4。
        assert c.stt is None and c.tts is None

    # 收尾：重置容器与配置缓存，避免污染其他测试。
    from app.container import Container

    set_container(Container())
    get_config.cache_clear()
    importlib.reload(main)
