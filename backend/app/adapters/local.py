"""LocalAdapter —— SQLite 实现四个 Repository（L1，docs/07）。

业务只依赖 app.adapters.repository 的抽象接口；这里是「本地优先」的具体实现。
所有方法带 user_id（默认 local-user，ADR-007）。嵌套结构（context_sentences /
fsrs_state / user_understanding / scores / error_ids / model_config）以 JSON 文本入库，
读写借 pydantic 完成（datetime 等的序列化交给模型，避免手搓）。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from pydantic import TypeAdapter

from app.adapters.repository import (
    ErrorRepository,
    SessionRepository,
    SettingsRepository,
    WordRepository,
)
from app.db.connection import Database
from app.models import (
    DEFAULT_USER_ID,
    ErrorEntry,
    FsrsState,
    PracticeSession,
    Settings,
    VocabEntry,
)
from app.models.entities import ModelConfig, UserUnderstanding

# 复用 pydantic 处理 list[...] 的 JSON 编解码（含 datetime）。
_UNDERSTANDING_LIST = TypeAdapter(list[UserUnderstanding])


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


# ── VocabEntry 行 <-> 模型 ──────────────────────────────────────────
def _vocab_to_row(v: VocabEntry) -> dict:
    return {
        "id": v.id,
        "user_id": v.user_id,
        "word": v.word,
        "lemma": v.lemma,
        "context_sentences": json.dumps(v.context_sentences, ensure_ascii=False),
        "status": v.status.value,
        "fsrs_state": v.fsrs_state.model_dump_json(),
        "user_understanding": _UNDERSTANDING_LIST.dump_json(v.user_understanding).decode(),
        "source_text_id": v.source_text_id,
        "created_at": v.created_at.isoformat(),
    }


def _row_to_vocab(row: sqlite3.Row) -> VocabEntry:
    return VocabEntry(
        id=row["id"],
        user_id=row["user_id"],
        word=row["word"],
        lemma=row["lemma"],
        context_sentences=json.loads(row["context_sentences"]),
        status=row["status"],
        fsrs_state=FsrsState.model_validate_json(row["fsrs_state"]),
        user_understanding=_UNDERSTANDING_LIST.validate_json(row["user_understanding"]),
        source_text_id=row["source_text_id"],
        created_at=_dt(row["created_at"]),
    )


class SqliteWordRepository(WordRepository):
    def __init__(self, db: Database) -> None:
        self._db = db

    async def add(self, entry: VocabEntry) -> VocabEntry:
        row = _vocab_to_row(entry)
        cols = ", ".join(row)
        placeholders = ", ".join(f":{c}" for c in row)
        await self._db.run(
            lambda c: c.execute(
                f"INSERT INTO vocab_entries ({cols}) VALUES ({placeholders})", row
            )
        )
        return entry

    async def get(self, entry_id: str, *, user_id: str = DEFAULT_USER_ID) -> VocabEntry | None:
        rows = await self._db.run(
            lambda c: c.execute(
                "SELECT * FROM vocab_entries WHERE id = ? AND user_id = ?",
                (entry_id, user_id),
            ).fetchone()
        )
        return _row_to_vocab(rows) if rows else None

    async def get_by_lemma(
        self, lemma: str, *, user_id: str = DEFAULT_USER_ID
    ) -> VocabEntry | None:
        row = await self._db.run(
            lambda c: c.execute(
                "SELECT * FROM vocab_entries WHERE lemma = ? AND user_id = ?",
                (lemma, user_id),
            ).fetchone()
        )
        return _row_to_vocab(row) if row else None

    async def list(self, *, user_id: str = DEFAULT_USER_ID) -> list[VocabEntry]:
        rows = await self._db.run(
            lambda c: c.execute(
                "SELECT * FROM vocab_entries WHERE user_id = ? ORDER BY created_at",
                (user_id,),
            ).fetchall()
        )
        return [_row_to_vocab(r) for r in rows]

    async def list_due(
        self, *, user_id: str = DEFAULT_USER_ID, limit: int | None = None
    ) -> list[VocabEntry]:
        """到期复习队列。真正的调度（FSRS）在 L2；L1 先给出可用语义：

        due 为空（刚收集、未排程）或 due <= 现在 即到期；按 due 升序、空值优先。
        L2 接 FSRS 时维护 fsrs_state.due，此处排序即生效。
        """
        rows = await self._db.run(
            lambda c: c.execute(
                "SELECT * FROM vocab_entries WHERE user_id = ? AND status != 'known'",
                (user_id,),
            ).fetchall()
        )
        entries = [_row_to_vocab(r) for r in rows]
        now = datetime.now(UTC)
        due = [e for e in entries if e.fsrs_state.due is None or e.fsrs_state.due <= now]
        # 空 due 排最前（视为立即可学），其余按到期时间升序。
        due.sort(key=lambda e: (e.fsrs_state.due is not None, e.fsrs_state.due or now))
        return due[:limit] if limit is not None else due

    async def update(self, entry: VocabEntry) -> VocabEntry:
        row = _vocab_to_row(entry)
        assignments = ", ".join(f"{c} = :{c}" for c in row if c not in ("id", "user_id"))
        await self._db.run(
            lambda c: c.execute(
                f"UPDATE vocab_entries SET {assignments} WHERE id = :id AND user_id = :user_id",
                row,
            )
        )
        return entry

    async def delete(self, entry_id: str, *, user_id: str = DEFAULT_USER_ID) -> None:
        await self._db.run(
            lambda c: c.execute(
                "DELETE FROM vocab_entries WHERE id = ? AND user_id = ?",
                (entry_id, user_id),
            )
        )


# ── ErrorEntry ──────────────────────────────────────────────────────
def _error_to_row(e: ErrorEntry) -> dict:
    return {
        "id": e.id,
        "user_id": e.user_id,
        "type": e.type.value,
        "original": e.original,
        "correction": e.correction,
        "explanation": e.explanation,
        "session_id": e.session_id,
        "topic": e.topic,
        "severity": e.severity,
        "resolved": 1 if e.resolved else 0,
        "created_at": e.created_at.isoformat(),
    }


def _row_to_error(row: sqlite3.Row) -> ErrorEntry:
    return ErrorEntry(
        id=row["id"],
        user_id=row["user_id"],
        type=row["type"],
        original=row["original"],
        correction=row["correction"],
        explanation=row["explanation"],
        session_id=row["session_id"],
        topic=row["topic"],
        severity=row["severity"],
        resolved=bool(row["resolved"]),
        created_at=_dt(row["created_at"]),
    )


class SqliteErrorRepository(ErrorRepository):
    def __init__(self, db: Database) -> None:
        self._db = db

    async def add(self, entry: ErrorEntry) -> ErrorEntry:
        await self.add_many([entry])
        return entry

    async def add_many(self, entries: list[ErrorEntry]) -> list[ErrorEntry]:
        if not entries:
            return []
        rows = [_error_to_row(e) for e in entries]
        cols = ", ".join(rows[0])
        placeholders = ", ".join(f":{c}" for c in rows[0])
        await self._db.run(
            lambda c: c.executemany(
                f"INSERT INTO error_entries ({cols}) VALUES ({placeholders})", rows
            )
        )
        return entries

    async def get(self, entry_id: str, *, user_id: str = DEFAULT_USER_ID) -> ErrorEntry | None:
        row = await self._db.run(
            lambda c: c.execute(
                "SELECT * FROM error_entries WHERE id = ? AND user_id = ?",
                (entry_id, user_id),
            ).fetchone()
        )
        return _row_to_error(row) if row else None

    async def list(
        self, *, user_id: str = DEFAULT_USER_ID, resolved: bool | None = None
    ) -> list[ErrorEntry]:
        if resolved is None:
            query = "SELECT * FROM error_entries WHERE user_id = ? ORDER BY created_at"
            params: tuple = (user_id,)
        else:
            query = (
                "SELECT * FROM error_entries WHERE user_id = ? AND resolved = ? "
                "ORDER BY created_at"
            )
            params = (user_id, 1 if resolved else 0)
        rows = await self._db.run(lambda c: c.execute(query, params).fetchall())
        return [_row_to_error(r) for r in rows]

    async def update(self, entry: ErrorEntry) -> ErrorEntry:
        row = _error_to_row(entry)
        assignments = ", ".join(f"{c} = :{c}" for c in row if c not in ("id", "user_id"))
        await self._db.run(
            lambda c: c.execute(
                f"UPDATE error_entries SET {assignments} WHERE id = :id AND user_id = :user_id",
                row,
            )
        )
        return entry


# ── PracticeSession ─────────────────────────────────────────────────
def _session_to_row(s: PracticeSession) -> dict:
    return {
        "id": s.id,
        "user_id": s.user_id,
        "mode": s.mode.value,
        "topic": s.topic,
        "transcript": s.transcript,
        "scores": json.dumps(s.scores, ensure_ascii=False) if s.scores is not None else None,
        "error_ids": json.dumps(s.error_ids),
        "summary": s.summary,
        "ended_early": 1 if s.ended_early else 0,
        "created_at": s.created_at.isoformat(),
    }


def _row_to_session(row: sqlite3.Row) -> PracticeSession:
    return PracticeSession(
        id=row["id"],
        user_id=row["user_id"],
        mode=row["mode"],
        topic=row["topic"],
        transcript=row["transcript"],
        scores=json.loads(row["scores"]) if row["scores"] is not None else None,
        error_ids=json.loads(row["error_ids"]),
        summary=row["summary"],
        ended_early=bool(row["ended_early"]),
        created_at=_dt(row["created_at"]),
    )


class SqliteSessionRepository(SessionRepository):
    def __init__(self, db: Database) -> None:
        self._db = db

    async def add(self, session: PracticeSession) -> PracticeSession:
        row = _session_to_row(session)
        cols = ", ".join(row)
        placeholders = ", ".join(f":{c}" for c in row)
        await self._db.run(
            lambda c: c.execute(
                f"INSERT INTO practice_sessions ({cols}) VALUES ({placeholders})", row
            )
        )
        return session

    async def get(
        self, session_id: str, *, user_id: str = DEFAULT_USER_ID
    ) -> PracticeSession | None:
        row = await self._db.run(
            lambda c: c.execute(
                "SELECT * FROM practice_sessions WHERE id = ? AND user_id = ?",
                (session_id, user_id),
            ).fetchone()
        )
        return _row_to_session(row) if row else None

    async def list(self, *, user_id: str = DEFAULT_USER_ID) -> list[PracticeSession]:
        rows = await self._db.run(
            lambda c: c.execute(
                "SELECT * FROM practice_sessions WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        )
        return [_row_to_session(r) for r in rows]

    async def update(self, session: PracticeSession) -> PracticeSession:
        row = _session_to_row(session)
        assignments = ", ".join(f"{c} = :{c}" for c in row if c not in ("id", "user_id"))
        await self._db.run(
            lambda c: c.execute(
                "UPDATE practice_sessions SET "
                f"{assignments} WHERE id = :id AND user_id = :user_id",
                row,
            )
        )
        return session


# ── Settings（单行 per user）────────────────────────────────────────
def _settings_to_row(s: Settings) -> dict:
    return {
        "user_id": s.user_id,
        "storage_backend": s.storage_backend.value,
        "scoring_standard": s.scoring_standard.value,
        "target_band": s.target_band,
        "native_lang": s.native_lang,
        "level_baseline": s.level_baseline,
        "voice_enabled": 1 if s.voice_enabled else 0,
        "model_config": s.model_config_.model_dump_json(),
        "pronunciation_provider": s.pronunciation_provider,
    }


def _row_to_settings(row: sqlite3.Row) -> Settings:
    return Settings(
        user_id=row["user_id"],
        storage_backend=row["storage_backend"],
        scoring_standard=row["scoring_standard"],
        target_band=row["target_band"],
        native_lang=row["native_lang"],
        level_baseline=row["level_baseline"],
        voice_enabled=bool(row["voice_enabled"]),
        model_config=ModelConfig.model_validate_json(row["model_config"]),
        pronunciation_provider=row["pronunciation_provider"],
    )


class SqliteSettingsRepository(SettingsRepository):
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, *, user_id: str = DEFAULT_USER_ID) -> Settings | None:
        row = await self._db.run(
            lambda c: c.execute(
                "SELECT * FROM settings WHERE user_id = ?", (user_id,)
            ).fetchone()
        )
        return _row_to_settings(row) if row else None

    async def save(self, settings: Settings) -> Settings:
        """UPSERT 单行配置（首次写入 / 后续覆盖）。"""
        row = _settings_to_row(settings)
        cols = ", ".join(row)
        placeholders = ", ".join(f":{c}" for c in row)
        updates = ", ".join(f"{c} = :{c}" for c in row if c != "user_id")
        await self._db.run(
            lambda c: c.execute(
                f"INSERT INTO settings ({cols}) VALUES ({placeholders}) "
                f"ON CONFLICT(user_id) DO UPDATE SET {updates}",
                row,
            )
        )
        return settings
