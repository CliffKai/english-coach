"""数据导入/导出路由（L5，ADR-009 开源落地基线）。

GET  /api/export/json   全量备份/迁移：生词 + 错题 + 会话 + 配置，一个 JSON，可再导回。
POST /api/import/json   从备份恢复：写入四类实体（默认合并；replace=True 先清空同 user 数据）。
GET  /api/export/anki   生词本导出 Anki CSV（卡正面=word，卡背=来源句+用户理解，ADR-014）。

两种导出分工（ADR-014）：
- JSON 全量 = 无损迁移（含 fsrs_state/status/时间戳全字段），用于「换机器/备份后原样导回」。
- Anki CSV = 对接外部 Anki 工作流，只取 word + 卡背文本，FSRS 调度交给 Anki 自己，不回传。

导出/导入都不调 LLM、不触密钥（密钥在 AppConfig/.env，绝不入库也绝不进备份）；
Settings 备份里的 model_config 只含 provider 名 + model（连接凭证另在 .env，ADR-006）。
"""

from __future__ import annotations

import csv
import io
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api import deps
from app.container import Container
from app.models import (
    DEFAULT_USER_ID,
    ErrorEntry,
    PracticeSession,
    Settings,
    VocabEntry,
)
from app.models.entities import UserUnderstanding

router = APIRouter(tags=["data"])

ContainerDep = Annotated[Container, Depends(deps.container)]

# 备份格式版本：未来 schema 演进时据此做迁移/拒绝不兼容的旧备份。
EXPORT_VERSION = 1


class BackupBundle(BaseModel):
    """全量备份包。字段即四类实体的完整模型列表（pydantic 负责无损序列化/校验）。"""

    version: int = EXPORT_VERSION
    vocab: list[VocabEntry] = Field(default_factory=list)
    errors: list[ErrorEntry] = Field(default_factory=list)
    sessions: list[PracticeSession] = Field(default_factory=list)
    settings: Settings | None = None


class ImportRequest(BaseModel):
    """导入请求：备份包 + 是否覆盖。

    replace=False（默认，合并）：逐条写入；与现有 id 冲突的条目跳过（不抢覆盖既有数据）。
    replace=True（覆盖）：先删该 user 的生词/错题/会话再写入——用于「换机器后原样恢复」。
      注意只清空可重建的三类业务数据，不动 settings（settings 用 UPSERT 覆盖）。
    """

    bundle: BackupBundle
    replace: bool = False


class ImportResult(BaseModel):
    """导入结果计数（前端反馈「导入了 N 个生词…」）。"""

    vocab_imported: int  # 新建的生词条数
    vocab_merged: int = 0  # 同 lemma 已存在、把来源句/理解并入的条数（合并模式）
    errors_imported: int
    sessions_imported: int
    settings_imported: bool
    skipped: int  # 因 id 已存在 / 无新增内容而跳过的条数


@router.get("/api/export/json")
async def export_json(c: ContainerDep) -> BackupBundle:
    """全量备份：四类实体打包成一个 JSON（含全字段，可再 import 回来）。"""
    words = deps.require_words(c)
    errors_repo = deps.require_errors(c)
    sessions = deps.require_sessions(c)
    settings_repo = deps.require_settings_repo(c)

    return BackupBundle(
        vocab=await words.list(),
        errors=await errors_repo.list(),
        sessions=await sessions.list(),
        settings=await settings_repo.get(),
    )


@router.post("/api/import/json")
async def import_json(req: ImportRequest, c: ContainerDep) -> ImportResult:
    """从备份恢复。replace=True 先清空业务三表再写；否则合并（id 冲突跳过）。"""
    words = deps.require_words(c)
    errors_repo = deps.require_errors(c)
    sessions = deps.require_sessions(c)
    settings_repo = deps.require_settings_repo(c)

    bundle = req.bundle
    if bundle.version != EXPORT_VERSION:
        raise HTTPException(
            status_code=422,
            detail=f"备份版本 {bundle.version} 与当前 {EXPORT_VERSION} 不兼容，无法导入。",
        )

    # 覆盖模式：删该 user 的生词/错题/会话（settings 走 UPSERT，无需先删）。
    # 顺序：先错题（外键引用会话）再会话，避免 FK 约束（schema.sql 外键 ON）。
    if req.replace:
        uid = bundle.settings.user_id if bundle.settings else DEFAULT_USER_ID
        for e in await errors_repo.list(user_id=uid):
            await errors_repo.delete(e.id, user_id=e.user_id)
        for s in await sessions.list(user_id=uid):
            await sessions.delete(s.id, user_id=s.user_id)
        for v in await words.list(user_id=uid):
            await words.delete(v.id, user_id=v.user_id)

    skipped = 0

    # 已存在 id 的集合（合并模式下据此跳过，避免主键冲突报错）。
    existing_vocab = {v.id for v in await words.list()}
    existing_errors = {e.id for e in await errors_repo.list()}
    existing_sessions = {s.id for s in await sessions.list()}
    # 已存在 (user_id, lemma) → 条目：vocab 表在 (user_id, lemma) 上有唯一索引（schema.sql），
    # 合并不同安装的备份时常见「新 id、同 lemma」——只查 id 会撞唯一索引 500。故按 lemma 合并
    # 来源句/理解（ADR-004/010：同词不同义并呈），而非新建或崩溃。
    existing_by_lemma = {(v.user_id, v.lemma): v for v in await words.list()}

    # 顺序：先会话后错题——error_entries.session_id 外键引用 practice_sessions。
    sessions_imported = 0
    for s in bundle.sessions:
        if s.id in existing_sessions:
            skipped += 1
            continue
        await sessions.add(s)
        sessions_imported += 1

    vocab_imported = 0
    vocab_merged = 0
    for v in bundle.vocab:
        if v.id in existing_vocab:
            skipped += 1
            continue
        key = (v.user_id, v.lemma)
        existing = existing_by_lemma.get(key)
        if existing is not None:
            # 同词：把来源句与理解历史并入已有条目（去重保序），不动其 fsrs_state/status
            # （本地调度进度优先于导入的副本）。
            merged_ctx = _merge_unique(existing.context_sentences, v.context_sentences)
            merged_und = _merge_understanding(existing.user_understanding, v.user_understanding)
            if merged_ctx != existing.context_sentences or len(merged_und) != len(
                existing.user_understanding
            ):
                existing.context_sentences = merged_ctx
                existing.user_understanding = merged_und
                await words.update(existing)
                vocab_merged += 1
            else:
                skipped += 1
            continue
        await words.add(v)
        vocab_imported += 1
        # 注册进两索引，使同批内后续「同 id / 同 lemma」也能正确跳过/合并。
        existing_vocab.add(v.id)
        existing_by_lemma[key] = v

    errors_imported = 0
    if bundle.errors:
        fresh = [e for e in bundle.errors if e.id not in existing_errors]
        skipped += len(bundle.errors) - len(fresh)
        if fresh:
            await errors_repo.add_many(fresh)
            errors_imported = len(fresh)

    settings_imported = False
    if bundle.settings is not None:
        await settings_repo.save(bundle.settings)
        settings_imported = True

    return ImportResult(
        vocab_imported=vocab_imported,
        vocab_merged=vocab_merged,
        errors_imported=errors_imported,
        sessions_imported=sessions_imported,
        settings_imported=settings_imported,
        skipped=skipped,
    )


@router.get("/api/export/anki")
async def export_anki(c: ContainerDep) -> StreamingResponse:
    """生词本导出 Anki CSV（ADR-014）。

    两列 Front,Back：正面=word；背面=来源句 + 用户理解历史（不含释义）。
    导出已知词也一并带（用户在 Anki 里自行管理节奏）；空生词本 → 仅表头。
    """
    words = deps.require_words(c)
    entries = await words.list()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Front", "Back"])
    for e in entries:
        writer.writerow([e.word, _anki_back(e)])

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="english-coach-vocab.csv"'},
    )


def _anki_back(entry: VocabEntry) -> str:
    """拼一张卡的卡背：来源句区 + 用户理解区（ADR-014，不放释义）。

    用换行分区；csv 模块负责把含换行的字段正确加引号转义。理解为空则只出来源句区。
    """
    lines: list[str] = []
    if entry.context_sentences:
        lines.append("【来源句】")
        lines.extend(f"• {s}" for s in entry.context_sentences)
    if entry.user_understanding:
        lines.append("【我的理解】")
        lines.extend(f"• {u.text}" for u in entry.user_understanding)
    return "\n".join(lines)


# ── 合并辅助（导入时同 lemma 并入，ADR-004/010）──────────────────────
def _merge_unique(existing: list[str], incoming: list[str]) -> list[str]:
    """已有来源句 + 新来源句去重保序合并（同词不同义并呈，ADR-004/010）。"""
    merged = list(existing)
    for s in incoming:
        s = s.strip()
        if s and s not in merged:
            merged.append(s)
    return merged


def _merge_understanding(
    existing: list[UserUnderstanding], incoming: list[UserUnderstanding]
) -> list[UserUnderstanding]:
    """理解历史去重合并（按文本判重，保留各自时间戳）。"""
    seen = {u.text for u in existing}
    merged = list(existing)
    for u in incoming:
        if u.text not in seen:
            merged.append(u)
            seen.add(u.text)
    return merged
