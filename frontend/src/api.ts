// 后端 API 客户端。dev 下 /api 经 Vite 代理到后端（见 vite.config.ts）。

export interface HealthResponse {
  status: string
  version: string
}

export interface MetaResponse {
  version: string
  storage_backend: string
  voice_enabled: boolean
  voice: { stt: boolean; tts: boolean }
  features: {
    vocab_collection: boolean
    topic_practice: boolean
    comprehension_review: boolean
  }
}

// ── F1 生词收集 ─────────────────────────────────────────────
export interface VocabCandidate {
  word: string
  lemma: string
  zipf: number
  context_sentences: string[]
}
export interface ExtractResponse {
  baseline: string | null
  candidates: VocabCandidate[]
}
export interface VocabEntry {
  id: string
  word: string
  lemma: string
  context_sentences: string[]
  status: string
  fsrs_state: { review_count: number; due: string | null }
}

// ── F3a/F3b 背词 ────────────────────────────────────────────
export interface ReviewCard {
  entry_id: string
  word: string
  lemma: string
  context_sentences: string[]
  review_count: number
}
export interface SubmitResponse {
  verdict: string
  rating: number
  feedback: string
  status: string
  next_due: string | null
}
export interface PassageWord {
  entry_id: string
  word: string
  lemma: string
}
export interface PassageResponse {
  text: string
  words: PassageWord[]
}
export interface WordCheckResult {
  verdict: string
  rating: number
  feedback: string
  lemma: string
  status: string
  next_due: string | null
}

// ── F2 话题练习 ─────────────────────────────────────────────
export interface DimensionScore {
  key: string
  label: string
  score: number | null
  comment: string
  estimated: boolean
}
export interface ErrorEntry {
  id: string
  type: string
  original: string
  correction: string
  explanation: string
  severity: number
}
export interface AnalysisReport {
  summary: string
  patterns: string[]
  type_counts: Record<string, number>
}
export interface ScoreResponse {
  session_id: string
  standard: string
  dimensions: DimensionScore[]
  overall: number | null
  estimated: boolean
  errors: ErrorEntry[]
  report: AnalysisReport
}
export interface Correction {
  original: string
  correction: string
  explanation: string
}
export interface TutorResponse {
  corrections: Correction[]
  encouragement: string
  scaffold: string
  follow_up: string
}
export interface DialogueTurnResponse {
  reply: string
}

async function getJson<T>(path: string): Promise<T> {
  const resp = await fetch(path)
  if (!resp.ok) throw new Error(await errText(path, resp))
  return resp.json() as Promise<T>
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!resp.ok) throw new Error(await errText(path, resp))
  return resp.json() as Promise<T>
}

async function errText(path: string, resp: Response): Promise<string> {
  try {
    const j = await resp.json()
    return j.detail ? `${j.detail}` : `${path} → ${resp.status}`
  } catch {
    return `${path} → ${resp.status}`
  }
}

export const api = {
  health: () => getJson<HealthResponse>('/api/health'),
  meta: () => getJson<MetaResponse>('/api/meta'),

  // F1
  vocabExtract: (text: string) =>
    postJson<ExtractResponse>('/api/vocab/extract', { text }),
  vocabCollect: (items: { word: string; lemma: string; context_sentences: string[] }[]) =>
    postJson<VocabEntry[]>('/api/vocab/collect', { items }),
  vocabList: () => getJson<VocabEntry[]>('/api/vocab'),

  // F3a
  reviewNext: () => getJson<ReviewCard | null>('/api/review/next'),
  reviewSubmit: (entry_id: string, understanding: string, too_easy = false) =>
    postJson<SubmitResponse>('/api/review/submit', { entry_id, understanding, too_easy }),
  // F3b
  reviewPassage: (topic?: string, limit = 5) =>
    postJson<PassageResponse>('/api/review/passage', { topic, limit }),
  reviewPassageCheck: (passage: string, lemmas: string[], translation: string) =>
    postJson<{ checks: WordCheckResult[] }>('/api/review/passage/check', {
      passage,
      lemmas,
      translation,
    }),

  // F2c / F2d
  practiceScore: (text: string, mode: string, topic?: string, ended_early = false) =>
    postJson<ScoreResponse>('/api/practice/score', { text, mode, topic, ended_early }),
  // F2a / F2b
  practiceTutor: (
    text: string,
    mode: string,
    topic: string | undefined,
    history: { role: string; content: string }[],
  ) => postJson<TutorResponse>('/api/practice/tutor', { text, mode, topic, history }),
  // F2d 文本对话单轮（语音版走 WS）
  dialogueTurn: (
    message: string,
    history: { role: string; content: string }[],
    topic?: string,
  ) => postJson<DialogueTurnResponse>('/api/practice/dialogue/turn', { message, history, topic }),

  errors: () => getJson<ErrorEntry[]>('/api/errors'),
}
