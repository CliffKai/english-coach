# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

This is a **design-stage** repository. There is no code yet — only `docs/` (the complete design) and an empty `README.md`. Phase 0 (design) is done, **including the implementation plan** (`docs/07-implementation-order.md`). The next step is to start building **L0 (scaffold + adapter interfaces + DB schema)**, following the dependency order in `docs/07-implementation-order.md`. There is no build, lint, or test tooling to run until the scaffold exists.

## Working model: docs drive code

`docs/` is the source of truth, not an afterthought. The repo's own rule (`docs/00-overview.md`):

> 修改设计前先更新文档，再改代码，保持文档与实现一致。
> (Update the design docs *before* changing code; keep docs and implementation consistent.)

When implementing or changing behavior, first reconcile against the relevant doc; if the design itself changes, edit the doc (and add/append an ADR in `docs/05-decisions.md`) in the same change. Docs are written in Chinese — keep that language when editing them.

Doc map: `00-overview` (定位/导航) · `01-product-spec` (三大功能的完整定义) · `02-architecture` (分层、Agent 职责、数据流) · `03-data-model` (实体字段) · `04-tech-stack` (选型与适配器) · `05-decisions` (ADR-001…009) · `06-roadmap` (MVP 切分与进度) · `07-implementation-order` (依赖拓扑：先写什么后写什么 — **start here when building**).

## What this product is

A *comprehension-first* English-learning agent for Chinese native speakers. Three features feed one data loop:

1. **生词收集 (vocab collection)** — tokenize input English, lemmatize, filter by frequency + the user's level baseline, ask word-by-word "know it / skip / don't know"; unknown words are stored **with their source sentence** for later review.
2. **话题练习 (topic practice)** — four modes split across two graders: **practice mode** (`guided_write`, `guided_speak`) gives *immediate* correction + scaffolding; **exam mode** (`free_write`, `dialogue`) gives *deferred* correction — errors are buffered silently, then on "finish/submit early" the user gets IELTS/TOEFL dimension scores + an error report.
3. **理解式背单词 (comprehension-based review)** — `recall_explain` shows the source sentence and asks the user to explain the word in their own words (no comparison to a "standard" definition); `context_passage` weaves vocab into a short passage to translate. Scheduling is driven by **FSRS** spaced repetition.

Two data rivers (vocab from feature 1, errors from feature 2) flow into one user profile that feeds back into all features.

## Architecture the implementation must follow

**Every external dependency is an adapter behind an interface** (ADR-002). Business code depends only on interfaces; users swap cloud vs. self-hosted via settings. The interfaces:

- `LLMProvider` — focus on `OpenAICompatAdapter` (one adapter covers ~80% of models via `base_url`/`api_key`/`model_name`: DeepSeek, Qwen, Kimi, vLLM, Ollama, LM Studio…) plus a native `ClaudeAdapter` for scoring. Models are assigned **per task** (`scoring` → strongest, `tokenize` → local/cheap, `conversation` → cost-effective), user-configurable.
- `WordRepository` / `ErrorRepository` / `SessionRepository` — `LocalAdapter` (SQLite) first, `CloudAdapter` (Postgres) later.
- `STTProvider` (faster-whisper local), `TTSProvider`, `PronunciationProvider` (defaults to `NoneAdapter` — pronunciation/fluency dims are marked "estimated from text" until an Azure key is supplied; ADR-003).

**Five agents** map to the features: `TokenizerAgent` (F1), `TutorAgent` (2a/2b practice), `ExaminerAgent` (2c/2d exam), `MemoryWordAgent` (3a/3b), `ErrorAnalysisAgent` (post-session review + error-book writeback).

**Deferred correction mechanism**: in exam mode `ExaminerAgent` annotates each user turn's errors into a *hidden buffer* while replying only with natural conversation; on submit the whole buffer goes to `ErrorAnalysisAgent` for the review report.

Stack (ADR-008): backend **Python + FastAPI** (chosen because spaCy tokenization/lemmatization, faster-whisper STT, and the FSRS library all live in Python); frontend **React + TypeScript + Tailwind**; WebSocket for streaming voice/dialogue, `MediaRecorder` for capture.

## Design invariants — do not violate without a new ADR

- **Vocab entries store NO definitions** (ADR-004) — only `word + lemma + context_sentences[]`. Meaning is re-derived from the source sentence at review time. Same word with different senses → multiple `context_sentences`, not multiple definitions.
- **Exam mode has zero scaffolding** (ADR-005) — no hints, no rescue. "Submit early" is allowed (scores what exists) and is *not* a rescue. Hesitations/pauses are a fluency signal and must be recorded, not smoothed over.
- **No accounts, single local user** (ADR-007) — `user_id` defaults to `"local-user"` but the field is kept in every schema so a future multi-user fork only needs an auth layer.
- **Open-source "can-actually-run" baseline is in the MVP, not phase 2** (ADR-009): first-run config wizard, docker-compose one-command start, JSON import/export + Anki export, and the "今日学习" aggregate home page.

## Core data entities

`VocabEntry` (word, lemma, `context_sentences[]`, status new/learning/known, `fsrs_state`, `user_understanding` history) · `ErrorEntry` (type grammar/collocation/spelling/logic/vocabulary/pronunciation, original, correction, explanation, severity, `resolved`) · `PracticeSession` (mode, topic, transcript, scores JSON, `error_ids[]`, summary, `ended_early`) · `Settings` (storage_backend, scoring_standard, target_band, native_lang, level_baseline, voice_enabled, per-task `model_config`, pronunciation_provider). Full field lists in `docs/03-data-model.md`.

## MVP build order

The authoritative build order is the dependency topology in `docs/07-implementation-order.md` (L0→L5); `06-roadmap.md` tracks scope/progress. In short: L0 scaffold (FE + FastAPI + adapter interfaces + DB schema) → L1 LocalAdapter(SQLite) + LLM adapters → L2 spaCy tokenize + FSRS scheduler → L3 core loop (level baseline → F1 collect → F3a review → F2c scoring → ErrorAnalysis) → L4 voice (STT/TTS, F2d, F2a/2b, F3b) → L5 habit layer (home page, import/export, wizard finalize).

**Hard dependency lines** (from `07`): interfaces before implementations · level baseline before F1/F2 · F1 before F3 · F2c immediately followed by ErrorAnalysis (the error buffer is transient) · STT/TTS before F2d · aggregate home/export last.
