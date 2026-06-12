"""SQLite 连接与初始化（LocalAdapter 的底座，L1）。

Repository 接口是 async（见 app/adapters/repository.py），但 SQLite 是同步库。
做法：持有一个 `check_same_thread=False` 的连接，所有写/读经一把锁串行化，
再用 `asyncio.to_thread` 把同步调用丢进线程池——既满足 async 接口，又不引重型
异步驱动。单机单用户量级足够；CloudAdapter(Postgres) 时换真正的异步驱动。
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from app.db import load_schema

T = TypeVar("T")


class Database:
    """单文件 SQLite 连接的薄封装。

    - 启动时建表（幂等，schema.sql 全是 IF NOT EXISTS）。
    - `run` 把同步函数（接收游标）丢线程池执行并自动提交，外部 await 即可。
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        # data/ 目录可能尚不存在（首次启动）。:memory: 不需要建目录。
        if str(self._path) != ":memory:":
            self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(load_schema())
        self._conn.commit()

    def _run_sync(self, fn: Callable[[sqlite3.Cursor], T]) -> T:
        """串行执行 fn(cursor)，成功提交、失败回滚。"""
        with self._lock:
            cur = self._conn.cursor()
            try:
                result = fn(cur)
                self._conn.commit()
                return result
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    async def run(self, fn: Callable[[sqlite3.Cursor], T]) -> T:
        """async 入口：把同步 DB 操作丢线程池。"""
        return await asyncio.to_thread(self._run_sync, fn)

    def close(self) -> None:
        with self._lock:
            self._conn.close()
