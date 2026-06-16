> **Language / 语言 / 言語**：**English** · [中文](README.zh.md) · [日本語](README.ja.md)

# English Coach Agent

A **comprehension-first** English-learning agent for Chinese native speakers: not rote memorization, but understanding in context.
Three features feed one data loop — vocabulary collection, topic practice (practice mode = instant correction / exam mode = deferred correction + IELTS/TOEFL scoring), and comprehension-based review (FSRS scheduling).

> Design is the source of truth. Every implementation defers to `docs/`; change the docs *before* changing behavior (see `docs/00-overview.md`).
> Doc navigation: `docs/00-overview.md`. Build order: `docs/07-implementation-order.md`. (Docs are written in Chinese.)

## Status

**The full MVP (L0–L5) is in place.** Core loop + voice + the daily-habit layer ("Today" home page, data import/export, setup wizard, one-command start) are all implemented.
See `docs/06-roadmap.md` for details.

| Layer | What it covers |
|---|---|
| L0 | Scaffold: adapter interfaces + config loading + DB schema + front/back shells |
| L1 | LocalAdapter(SQLite) four repos + LLM adapters (OpenAI-compatible / Claude) |
| L2 | spaCy tokenize/lemma/frequency filtering + FSRS scheduler |
| L3 | Core loop: level baseline → F1 vocab collection → F3a review → F2c scoring → ErrorAnalysis error book |
| L4 | Voice: STT/TTS adapters + F2d voice dialogue + F2a/2b guided practice + F3b context-passage review |
| L5 | Daily loop: Today home page · import/export (JSON + Anki CSV) · setup wizard · docker-compose one-command start |

## What this product is

Three features, one user profile, two data rivers:

1. **Vocabulary collection** — paste English text → tokenize → lemmatize → filter by frequency + your level baseline → ask word-by-word "know it / skip / don't know"; unknown words are stored **with their source sentence** for later review (no definitions stored, ADR-004).
2. **Topic practice** — four modes across two graders. *Practice mode* (`guided_write`, `guided_speak`) gives **instant** correction + scaffolding; *exam mode* (`free_write`, `dialogue`) gives **deferred** correction — errors buffered silently, then on "finish/submit early" you get IELTS/TOEFL dimension scores + an error report.
3. **Comprehension-based review** — `recall_explain` shows the source sentence and asks you to explain the word in your own words (no comparison to a "standard" definition); `context_passage` weaves vocab into a short passage to translate. Scheduling is driven by **FSRS** spaced repetition.

## Repository layout

```
backend/     FastAPI backend (Python 3.11, conda env `english-coach`)
  app/
    models/      Domain entities (VocabEntry / ErrorEntry / PracticeSession / Settings)
    adapters/    Adapters (LLM / storage repos / STT / TTS / pronunciation) — interfaces + impls
    agents/      Five agents (Tokenizer / Tutor / Examiner / MemoryWord / ErrorAnalysis) + Leveling
    nlp/         spaCy tokenize/lemma/frequency filtering
    scheduling/  FSRS spaced-repetition scheduler
    api/         HTTP/WS routes (baseline/vocab/review/practice/voice/today/data/settings)
    db/          schema.sql (four-table DDL)
    config.py    Process-level config (.env → AppConfig); secrets live here only, never persisted
    container.py DI container (interfaces are mock-injectable)
    main.py      FastAPI entrypoint (/api/health, /api/meta, router mounting)
  tests/       L0–L5 verification tests (TestClient + mock container + in-memory SQLite, fully offline)
  Dockerfile
frontend/    React + TS + Tailwind (Vite)
  src/panels/  Today / Vocab / Practice / Review / Settings panels
  Dockerfile, nginx.conf
docs/        Design & decisions (source of truth)
docker-compose.yml
```

## One-command start (Docker, recommended for open-source users)

```bash
cp backend/.env.example backend/.env      # ⚠️ Required: at least one LLM provider's connection info
docker compose up --build                 # starts backend + frontend
# → frontend http://localhost:5173 (/api, /ws are reverse-proxied to the backend by the frontend nginx)
```

> **Configure a model first.** The service starts even with no LLM provider in `backend/.env`, but every AI feature (scoring, review judging, dialogue, level baseline) will return 409 telling you to configure a model. The easiest option is one OpenAI-compatible provider (DeepSeek/Qwen/Kimi/local Ollama, …); see the examples in `backend/.env.example`.
>
> **Binds to localhost by default.** The frontend port defaults to `127.0.0.1:5173` (this app has no account/auth yet but exposes import/export and key-spending endpoints). If you genuinely need LAN/remote access, start with `FRONTEND_BIND=0.0.0.0` and add your own auth.

To use a **purely local model** (no cloud key):

```bash
docker compose --profile ollama up --build
# In backend/.env point a provider at http://ollama:11434/v1 (kind=openai_compat, api_key blank)
# Pull a model inside the container: docker compose exec ollama ollama pull qwen2.5
```

Data (vocab/errors/sessions) persists in the named volume `backend-data`; rebuilding containers won't lose it.

## Local development

### Backend

Use miniforge/conda (the project's fixed env name is `english-coach`, Python 3.11):

```bash
conda create -n english-coach python=3.11   # first time
cd backend
conda run -n english-coach python -m pip install -e ".[dev]"
conda run -n english-coach python -m spacy download en_core_web_sm   # for F1 tokenize / level baseline
cp .env.example .env                          # fill in provider connection info as needed
conda run -n english-coach uvicorn app.main:app --reload
# → http://127.0.0.1:8000/api/health
```

Optional: purely local voice (faster-whisper / piper). Not needed when using the default OpenAI-compatible protocol:

```bash
conda run -n english-coach python -m pip install -e ".[voice]"
```

Tests / quality checks (fully offline, no real model needed):

```bash
cd backend
conda run -n english-coach python -m pytest -q
conda run -n english-coach ruff check .
conda run -n english-coach mypy app
```

### Frontend

```bash
cd frontend
npm install
npm run dev      # → http://localhost:5173 (/api, /ws proxied to backend 8000)
```

## First run: the setup wizard

New users complete the setup wizard in the frontend "Settings" page (a banner on the home page nudges you there):

1. **Configure a model** — in `backend/.env`, fill in provider connection info as `ENGLISH_COACH_LLM_PROVIDERS__<NAME>__...` (base_url/api_key/kind), then restart the backend. Secrets live only in `.env` and are never persisted (ADR-006).
2. **Assign models per task** — in "Settings", pick a provider + model name for each of scoring / reasoning / conversation / tokenize, and click "Test connection" to verify. Leaving either provider or model blank = that task falls back to the backend default model (a default exists only if you configured a Claude provider in `.env`; with only an OpenAI-compatible provider you **must** assign explicitly here, otherwise the task returns 409).
3. **Test your level baseline** — write a short English passage; the AI estimates your CEFR level (labeled "AI estimate", re-testable). The baseline affects vocab filtering and scoring (a hard-dependency line in doc 07).

Once configured, go back to the "Today" home page — it ties due vocab, unresolved errors, and a recommended topic into today's study list.

## Data import / export ("Settings" page)

- **Full JSON backup** — exports an all-fields backup (vocab/errors/sessions/settings) that can be imported back into this app verbatim (machine change / migration). Import supports "merge" (default: skip on same id; for the same lemma, merge source sentences/understanding into the existing entry without overwriting local review progress) or "replace" (wipe first, then import).
- **Anki CSV** — exports the vocabulary book as an Anki-importable CSV. Card front = word; **card back = source sentences + your past explanations, no definition** (ADR-014, faithful to ADR-004's "no definitions stored"). In Anki, "File → Import" and choose "fields separated by comma, allow HTML/newlines in fields".

## Design invariants (do not violate without a new ADR)

- **Vocab entries store NO definitions** — only `word + lemma + context_sentences[]` (ADR-004).
- **Exam mode has zero scaffolding**, but "submit early" is allowed (ADR-005).
- **No accounts, single local user**; schema keeps a `user_id` field (ADR-007).
- **Every external dependency is an adapter** (ADR-002); secrets come only from `.env`, never persisted.
- **Anki card back = source sentences + understanding, not definitions; CSV first** (ADR-014).
