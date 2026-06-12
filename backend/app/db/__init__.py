"""存储 schema。L0 只提供 DDL 与 schema 加载工具；实际 LocalAdapter(SQLite)
实现见 L1（app.adapters 之下）。
"""

from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def load_schema() -> str:
    """返回建表 DDL 文本（供 L1 初始化 SQLite 用）。"""
    return SCHEMA_PATH.read_text(encoding="utf-8")


__all__ = ["SCHEMA_PATH", "load_schema"]
