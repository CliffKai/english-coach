"""存储 schema 与连接。schema.sql 是建表 DDL；Database（L1）据此初始化 SQLite，
供 app.adapters.local 的四个 Repository 使用。
"""

from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def load_schema() -> str:
    """返回建表 DDL 文本（供 L1 初始化 SQLite 用）。"""
    return SCHEMA_PATH.read_text(encoding="utf-8")


__all__ = ["SCHEMA_PATH", "load_schema"]
