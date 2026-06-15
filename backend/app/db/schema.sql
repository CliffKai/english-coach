-- English Coach Agent — 数据库 schema（DDL）
-- 对应 docs/03-data-model.md 的四个实体。
-- 方言：SQLite（LocalAdapter，L1）。CloudAdapter(Postgres) 时另起一份或用迁移工具。
--
-- 约定：
--   - 所有表带 user_id，默认 'local-user'（ADR-007）。
--   - 列表/嵌套结构（context_sentences / scores / error_ids / fsrs_state / model_config）
--     以 JSON 文本存储（SQLite 无原生数组）。
--   - 时间统一存 ISO-8601 UTC 文本。

PRAGMA foreign_keys = ON;

-- ── 生词条目（功能1产出，功能3消费）──────────────────────────────
-- 关键：不存释义，只存 word + lemma + context_sentences[]（ADR-004）。
CREATE TABLE IF NOT EXISTS vocab_entries (
    id                 TEXT PRIMARY KEY,
    user_id            TEXT NOT NULL DEFAULT 'local-user',
    word               TEXT NOT NULL,
    lemma              TEXT NOT NULL,
    context_sentences  TEXT NOT NULL DEFAULT '[]',   -- JSON: string[]
    status             TEXT NOT NULL DEFAULT 'new',   -- new | learning | known
    fsrs_state         TEXT NOT NULL DEFAULT '{}',    -- JSON: {difficulty,stability,due,review_count,consecutive_good,last_review}
    user_understanding TEXT NOT NULL DEFAULT '[]',    -- JSON: {text,created_at}[]
    source_text_id     TEXT,
    created_at         TEXT NOT NULL
);
-- 按词元查重（同词不同义追加 context，而非新建）。
CREATE UNIQUE INDEX IF NOT EXISTS idx_vocab_user_lemma ON vocab_entries (user_id, lemma);
-- FSRS 到期复习队列扫描。due 从 fsrs_state JSON 抽出冗余存一列便于排序（L1 维护）。
CREATE INDEX IF NOT EXISTS idx_vocab_user_status ON vocab_entries (user_id, status);

-- ── 错题条目（功能2考试模式产出）────────────────────────────────
CREATE TABLE IF NOT EXISTS error_entries (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL DEFAULT 'local-user',
    type        TEXT NOT NULL,    -- grammar|collocation|spelling|logic|vocabulary|pronunciation
    original    TEXT NOT NULL,
    correction  TEXT NOT NULL,
    explanation TEXT NOT NULL DEFAULT '',
    session_id  TEXT,
    topic       TEXT,
    severity    INTEGER NOT NULL DEFAULT 1,
    resolved    INTEGER NOT NULL DEFAULT 0,   -- 0/1；连续 N 次未犯标记 resolved
    created_at  TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES practice_sessions (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_error_user_resolved ON error_entries (user_id, resolved);
CREATE INDEX IF NOT EXISTS idx_error_user_type ON error_entries (user_id, type);

-- ── 练习会话（功能2）──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS practice_sessions (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL DEFAULT 'local-user',
    mode        TEXT NOT NULL,    -- guided_write|guided_speak|free_write|dialogue
    topic       TEXT,
    transcript  TEXT NOT NULL DEFAULT '',
    scores      TEXT,             -- JSON: 各维度分数；NULL 表示未打分
    error_ids   TEXT NOT NULL DEFAULT '[]',  -- JSON: string[]
    summary     TEXT,
    ended_early INTEGER NOT NULL DEFAULT 0,   -- 0/1（ADR-005 提前交卷）
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_session_user_created ON practice_sessions (user_id, created_at);

-- ── 用户配置（单行 per user）──────────────────────────────────
CREATE TABLE IF NOT EXISTS settings (
    user_id                TEXT PRIMARY KEY DEFAULT 'local-user',
    storage_backend        TEXT NOT NULL DEFAULT 'local',     -- local | cloud
    scoring_standard       TEXT NOT NULL DEFAULT 'IELTS',     -- IELTS | TOEFL
    target_band            REAL,
    native_lang            TEXT NOT NULL DEFAULT 'zh',
    level_baseline         TEXT,                              -- CEFR / 估算雅思分
    voice_enabled          INTEGER NOT NULL DEFAULT 0,        -- 0/1
    model_config           TEXT NOT NULL DEFAULT '{}',        -- JSON: per-task 模型分配
    pronunciation_provider TEXT NOT NULL DEFAULT 'none'       -- none | azure
);
