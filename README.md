> **Language / 语言 / 言語**：**English** · [中文](README.zh.md) · [日本語](README.ja.md)

# English Coach Agent

A **comprehension-first** English-learning app for Chinese native speakers — built around understanding words in context instead of rote memorization.

It runs entirely on your own machine, talks to whichever AI model you choose (cloud or fully local), and keeps all your data local. Local accounts are used only to separate each learner's vocabulary, errors, and practice history.

## What it does

Three features that feed one another:

1. **Vocabulary collection** — paste any English text. The app splits it into words, skips the ones you already know (based on your level), and asks you word-by-word: *know it / skip / don't know*. Words you don't know are saved **together with the sentence they came from**, so later you remember *why* you didn't know them. No dictionary definitions are stored — meaning comes back to you from the sentence.
   - **Missed a word?** If the app filtered out a word you actually don't know, just add it yourself — it'll grab the sentence from your text. You can also add a word out of the blue (type your own example sentence, or let the AI write one).
2. **Topic practice** — write your own topic, or let the AI suggest an editable one, then pick a mode:
   - *Practice mode* (guided writing / speaking): instant corrections and hints as you go.
   - *Exam mode* (free writing / dialogue): no help while you work — errors are noted silently, and when you finish (or hand in early) you get IELTS/TOEFL-style scores plus a full error report.
3. **Comprehension-based review** — instead of flashing a definition at you, the app shows the original sentence and asks you to explain the word *in your own words*, or weaves your words into a short passage to translate. Review timing is scheduled automatically (spaced repetition) so you revisit words right before you'd forget them.

Everything each learner collects (vocabulary) and every mistake they make (errors) flows into that learner's own profile. Model/API setup is still shared for this local app: one configured provider setup is used by all local accounts.

## Quick start (Docker — recommended)

```bash
cp backend/.env.example backend/.env      # then add at least one AI model (see below)
docker compose up --build
# → open http://localhost:5173
```

> **You must configure an AI model first.** The app starts without one, but every AI feature (scoring, review, dialogue, level test) will ask you to set up a model. The easiest path is one OpenAI-compatible provider — DeepSeek, Qwen, Kimi, a local Ollama, etc. See the examples in `backend/.env.example`.
>
> **Runs on localhost only by default.** The app now has local login, but model/API settings are shared and endpoints can spend your configured API key — so it still binds to `127.0.0.1` only. If you really need to reach it from another device, start with `FRONTEND_BIND=0.0.0.0` and put proper network authentication in front of it.

### Fully local, no cloud key

```bash
docker compose --profile ollama up --build
# In backend/.env, point a provider at http://ollama:11434/v1 (kind=openai_compat, leave api_key blank)
# Pull a model: docker compose exec ollama ollama pull qwen2.5
```

Your data (vocabulary, errors, sessions) lives in the `backend-data` volume and survives container rebuilds.

## Running without Docker

<details>
<summary>Backend + frontend setup</summary>

**Backend** (Python 3.11, using conda):

```bash
conda create -n english-coach python=3.11
cd backend
conda run -n english-coach python -m pip install -e .
conda run -n english-coach python -m spacy download en_core_web_sm
cp .env.example .env                         # add your model connection info
conda run -n english-coach uvicorn app.main:app --reload
# → http://127.0.0.1:8000
```

For fully local voice (offline speech-to-text / text-to-speech), also install the optional voice extras — not needed if you use a cloud or OpenAI-compatible audio service:

```bash
conda run -n english-coach python -m pip install -e ".[voice]"
```

**Frontend**:

```bash
cd frontend
npm install
npm run dev      # → http://localhost:5173
```

</details>

## First run: the setup wizard

Register or log in first. A banner on the home page then guides you to the **Settings** page:

1. **Add a model** — in `backend/.env`, fill in your provider's connection info (base URL / API key), then restart the backend. Your keys stay in `.env` and are never stored in the database.
2. **Assign a model to each task** — in Settings, choose a provider + model for scoring, reasoning, conversation, and tokenizing, then click **Test connection** to confirm it works.
3. **Take the level test** — write a short English paragraph and the AI estimates your level (labeled as an estimate, and you can retake it). Your level controls which words are considered "too easy to ask about" and calibrates your scores.

Then head to the **Today** page — it gathers the words due for review, errors worth revisiting, and a suggested topic into one daily study list.

## Voice (optional)

Speaking practice and spoken dialogue need a speech-to-text and text-to-speech service. These work over the standard OpenAI-compatible audio protocol (cloud or local), or fully offline with local models. Pronunciation/fluency scoring stays blank and clearly labeled unless you connect a pronunciation-assessment service — the app won't fake a score it can't measure.

## Import / export (Settings page)

- **Full JSON backup** — exports the current logged-in learner's vocabulary, errors, sessions, plus shared settings, so you can move to a new machine and import it back. Import can **merge** (keep your existing review progress, just add new sentences) or **replace** (wipe and reimport for the current account).
- **Anki export** — exports the current logged-in learner's vocabulary as an Anki-importable CSV. The card front is the word; the back is the source sentences plus your own past explanations — **no canned definition**, true to how the app works. In Anki, choose "File → Import" with comma-separated fields and "allow HTML/newlines in fields".

## Privacy

Everything runs locally. Your text, vocabulary, and recordings stay on your machine; the only data leaving it is whatever you send to the AI model you configured. API keys live only in `backend/.env` and are never written to the database.
