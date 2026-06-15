# Repository Guidelines

## Project Structure & Module Organization

This repository is currently in the design stage. The source of truth is `docs/`, especially `docs/07-implementation-order.md` for build order and `docs/05-decisions.md` for ADRs. `CLAUDE.md` summarizes implementation invariants.

Planned code structure follows the docs: Python FastAPI backend, React + TypeScript + Tailwind frontend, adapter interfaces, and local-first storage. Prefer top-level directories such as `backend/`, `frontend/`, `tests/`, and `.env.example`.

## Build, Test, and Development Commands

Use the project-specific Miniforge Python environment for all backend Python commands:

- `conda run -n english-coach ...` runs commands in the `english-coach` environment.
- From `backend/`, run tests with `conda run -n english-coach pytest`.

There is no build, lint, or test tooling yet. Until L0 scaffolding exists, use documentation checks:

- `rg --files` lists the current repository files.
- `git log --oneline -n 10` checks recent commit style.

After scaffolding, document exact commands such as `pytest`, `npm test`, `npm run lint`, `npm run dev`, and `docker compose up`.

## Coding Style & Naming Conventions

Follow the architecture in `docs/02-architecture.md`: business logic depends on interfaces, not concrete external services. Keep provider integrations behind adapters such as `LLMProvider`, `STTProvider`, `TTSProvider`, and repository interfaces.

Use idiomatic Python for backend code and TypeScript for frontend code. Prefer explicit names like `TokenizerAgent`, `OpenAICompatAdapter`, and `WordRepository`. Keep docs in Chinese when editing existing `docs/*.md` files.

## Testing Guidelines

No test framework is configured yet. When implementation begins, add backend tests with `pytest` and frontend tests with the chosen React test runner. Cover adapter contracts, SQLite repositories, tokenization/lemma filtering, FSRS scheduling, and agent prompt regressions.

Name tests by behavior, for example `test_vocab_entry_preserves_source_sentence` or `TokenizerAgent.spec.ts`.

## Commit & Pull Request Guidelines

The existing history uses short, imperative commit subjects such as `Add CLAUDE.md, implementation-order doc, and .gitignore`. Continue that style: describe the change, not the process.

Pull requests should include a concise summary, linked issue if available, affected docs or ADR updates, test results, and screenshots for UI changes. If behavior changes, update the relevant design doc before or alongside the code.

## Agent-Specific Instructions

The agent's default role is review-only. For code the maintainer plans to commit, inspect the diff, identify bugs, design drift, missing tests, and risky assumptions, then report findings back to the maintainer. Do not write code, modify files, stage changes, or commit unless the maintainer explicitly asks for implementation.

Docs drive code. Before approving behavior changes, reconcile them with `docs/`; if the design changes, request a matching doc update and ADR change in `docs/05-decisions.md`. Preserve key invariants: local single-user baseline, adapter-first external dependencies, no stored vocabulary definitions, and deferred correction in exam mode.
