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
  setup: {
    has_llm_provider: boolean
    has_baseline: boolean
    needs_wizard: boolean
  }
}

// ── L5「今日学习」聚合首页 ───────────────────────────────────
export interface DueWordPreview {
  entry_id: string
  word: string
  lemma: string
}
export interface ErrorPreview {
  id: string
  type: string
  original: string
  correction: string
}
export interface TodayResponse {
  due_count: number
  due_preview: DueWordPreview[]
  unresolved_error_count: number
  error_preview: ErrorPreview[]
  recommended_topic: { topic: string; reason: string }
}

// ── L5 配置向导 / 设置 ───────────────────────────────────────
export interface ModelAssignment {
  provider: string
  model: string
}
export interface Settings {
  user_id: string
  storage_backend: string
  scoring_standard: string
  target_band: number | null
  native_lang: string
  level_baseline: string | null
  voice_enabled: boolean
  model_config: {
    scoring: ModelAssignment | null
    reasoning: ModelAssignment | null
    tokenize: ModelAssignment | null
    conversation: ModelAssignment | null
  }
  pronunciation_provider: string
}
export interface ProvidersResponse {
  llm: string[]
  stt: string[]
  tts: string[]
}
export interface TestLLMResponse {
  ok: boolean
  detail: string
}
export interface BaselineResult {
  baseline: string
  estimated_band: number | null
  rationale: string
  estimated: boolean
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

async function postJson<T>(path: string, body: unknown, method = 'POST'): Promise<T> {
  const resp = await fetch(path, {
    method,
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
  // 用户补录生词（ADR-015）：text=从本文补词取原句；sentence=自填例句；都无则 LLM 造句。
  vocabManual: (word: string, opts: { text?: string; sentence?: string } = {}) =>
    postJson<VocabEntry>('/api/vocab/manual', { word, ...opts }),
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

  // L5 今日学习聚合首页
  today: () => getJson<TodayResponse>('/api/today'),

  // L5 配置向导 / 设置
  getSettings: () => getJson<Settings>('/api/settings'),
  putSettings: (s: Settings) => postJson<Settings>('/api/settings', s, 'PUT'),
  providers: () => getJson<ProvidersResponse>('/api/providers'),
  testLlm: (provider: string, model: string) =>
    postJson<TestLLMResponse>('/api/settings/test-llm', { provider, model }),

  // 水平基线（向导复用 L3 接口）
  baselinePrompt: () => getJson<{ prompt: string }>('/api/baseline/prompt'),
  baselineAssess: (sample: string, prompt?: string) =>
    postJson<BaselineResult>('/api/baseline/assess', { sample, prompt }),

  // L5 导入/导出
  exportJsonUrl: '/api/export/json',
  exportAnkiUrl: '/api/export/anki',
  importJson: (bundle: unknown, replace: boolean) =>
    postJson<{
      vocab_imported: number
      vocab_merged: number
      errors_imported: number
      sessions_imported: number
      settings_imported: boolean
      skipped: number
    }>('/api/import/json', { bundle, replace }),
}
