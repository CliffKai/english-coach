import { useState, type FormEvent } from 'react'
import { api, type LearningPoint, type LexicalNote, type SentenceAnalysisResponse } from '../api'
import { Button, Card, ErrorNote, Estimated, Spinner } from '../ui'

// 句子精读：输入一句英文 → 翻译 + 结构/语法/词汇/表达讲解。
// 第一版不落库；用户主动补录重点词时，复用 F1 /api/vocab/manual，只存「词 + 来源句」。

export default function SentencePanel({ onSendToVocab }: { onSendToVocab: (sentence: string) => void }) {
  const [sentence, setSentence] = useState('')
  const [result, setResult] = useState<SentenceAnalysisResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [savingTerm, setSavingTerm] = useState<string | null>(null)
  const [saved, setSaved] = useState<Record<string, string>>({})

  async function analyze(e?: FormEvent) {
    e?.preventDefault()
    if (!sentence.trim()) return
    setBusy(true)
    setErr(null)
    setSaved({})
    try {
      const r = await api.sentenceAnalyze(sentence)
      setResult(r)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function saveTerm(note: LexicalNote) {
    const term = note.term.trim()
    const sourceSentence = result?.original || sentence
    if (!term || !sourceSentence.trim()) return
    setSavingTerm(term)
    setErr(null)
    try {
      const entry = await api.vocabManual(term, { sentence: sourceSentence })
      setSaved((s) => ({ ...s, [term]: '已加入生词本：' + entry.word }))
    } catch (e) {
      setSaved((s) => ({ ...s, [term]: '补录失败：' + (e as Error).message }))
    } finally {
      setSavingTerm(null)
    }
  }

  const sourceSentence = result?.original || sentence

  return (
    <div className="space-y-4">
      <Card>
        <h2 className="mb-2 font-medium">输入一句英文</h2>
        <p className="mb-3 text-sm text-slate-500">
          AI 会给出自然翻译、句子结构、语法点、词汇/短语用法、常见误区和仿写任务。精读结果不落库。
        </p>
        <form onSubmit={analyze}>
          <textarea
            value={sentence}
            onChange={(e) => setSentence(e.target.value)}
            rows={4}
            placeholder="Paste one English sentence here…"
            className="w-full rounded-md border border-slate-300 p-3 text-sm focus:border-slate-500 focus:outline-none"
          />
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <Button type="submit" disabled={busy || !sentence.trim()}>
              精读这个句子
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                setSentence('')
                setResult(null)
                setSaved({})
                setErr(null)
              }}
              disabled={busy || (!sentence && !result)}
            >
              清空
            </Button>
            {busy && <Spinner label="精读中…" />}
          </div>
        </form>
        <ErrorNote message={err} />
      </Card>

      {result && (
        <>
          <Card>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2 className="font-medium">精读结果</h2>
              {result.estimated && <Estimated />}
            </div>
            <p className="rounded-md bg-slate-50 p-3 text-sm text-slate-700">{result.original}</p>

            <div className="mt-4 grid gap-3 md:grid-cols-2">
              <InfoBlock title="自然翻译" text={result.translation_zh} />
              <InfoBlock title="贴近结构的直译" text={result.literal_translation} muted />
            </div>

            {result.structure && (
              <div className="mt-4">
                <h3 className="mb-1 text-sm font-medium text-slate-700">句子结构</h3>
                <p className="text-sm leading-6 text-slate-600">{result.structure}</p>
              </div>
            )}

            <div className="mt-4 flex flex-wrap gap-2">
              <Button variant="ghost" onClick={() => onSendToVocab(sourceSentence)}>
                送去「生词收集」切词
              </Button>
            </div>
          </Card>

          {result.grammar_points.length > 0 && (
            <Card>
              <h3 className="mb-3 font-medium">语法与结构点</h3>
              <LearningPointList points={result.grammar_points} />
            </Card>
          )}

          {(result.vocabulary_notes.length > 0 || result.phrase_notes.length > 0) && (
            <Card>
              <h3 className="mb-3 font-medium">词汇与短语用法</h3>
              {result.vocabulary_notes.length > 0 && (
                <LexicalNoteList
                  title="重点词"
                  notes={result.vocabulary_notes}
                  saved={saved}
                  savingTerm={savingTerm}
                  onSave={saveTerm}
                />
              )}
              {result.phrase_notes.length > 0 && (
                <LexicalNoteList
                  title="短语 / 表达"
                  notes={result.phrase_notes}
                  saved={saved}
                  savingTerm={savingTerm}
                  onSave={saveTerm}
                />
              )}
              <p className="mt-3 text-xs text-slate-400">
                加入生词本时只保存词和当前句子作为来源句，不保存 AI 生成的释义。
              </p>
            </Card>
          )}

          {(result.common_pitfalls.length > 0 || result.takeaways.length > 0 || result.rewrites.length > 0) && (
            <Card>
              <div className="grid gap-4 md:grid-cols-2">
                {result.takeaways.length > 0 && (
                  <SimpleList title="最值得学" items={result.takeaways} tone="emerald" />
                )}
                {result.common_pitfalls.length > 0 && (
                  <SimpleList title="常见误区" items={result.common_pitfalls} tone="rose" />
                )}
              </div>

              {result.rewrites.length > 0 && (
                <div className="mt-4">
                  <h3 className="mb-2 text-sm font-medium text-slate-700">表达迁移</h3>
                  <ul className="space-y-2">
                    {result.rewrites.map((r, i) => (
                      <li key={r.style + '-' + i} className="rounded-md border border-slate-100 p-3 text-sm">
                        <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500">{r.style}</span>
                        <p className="mt-1 text-slate-700">{r.text}</p>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {result.exercise && (
                <div className="mt-4 rounded-md bg-sky-50 p-3 text-sm text-sky-800">
                  <span className="font-medium">跟练任务：</span>
                  {result.exercise}
                </div>
              )}
            </Card>
          )}
        </>
      )}
    </div>
  )
}

function InfoBlock({ title, text, muted = false }: { title: string; text: string; muted?: boolean }) {
  if (!text) return null
  const boxClass = 'rounded-md p-3 ' + (muted ? 'bg-slate-50' : 'bg-emerald-50')
  const titleClass = 'mb-1 text-sm font-medium ' + (muted ? 'text-slate-600' : 'text-emerald-800')
  const textClass = 'text-sm leading-6 ' + (muted ? 'text-slate-500' : 'text-emerald-900')
  return (
    <div className={boxClass}>
      <h3 className={titleClass}>{title}</h3>
      <p className={textClass}>{text}</p>
    </div>
  )
}

function LearningPointList({ points }: { points: LearningPoint[] }) {
  return (
    <ul className="space-y-3">
      {points.map((p, i) => (
        <li key={p.title + '-' + i} className="rounded-md border border-slate-100 p-3">
          <p className="text-sm font-medium text-slate-800">{p.title}</p>
          {p.explanation && <p className="mt-1 text-sm leading-6 text-slate-600">{p.explanation}</p>}
          {p.example && <p className="mt-1 text-xs text-slate-500">例：{p.example}</p>}
        </li>
      ))}
    </ul>
  )
}

function LexicalNoteList({
  title,
  notes,
  saved,
  savingTerm,
  onSave,
}: {
  title: string
  notes: LexicalNote[]
  saved: Record<string, string>
  savingTerm: string | null
  onSave: (note: LexicalNote) => void
}) {
  return (
    <div className="mb-4 last:mb-0">
      <h4 className="mb-2 text-sm font-medium text-slate-700">{title}</h4>
      <ul className="space-y-2">
        {notes.map((n, i) => (
          <li key={n.term + '-' + i} className="rounded-md border border-slate-100 p-3">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-sm font-medium text-slate-800">{n.term}</p>
                {n.meaning && <p className="mt-1 text-sm text-slate-600">{n.meaning}</p>}
                {n.note && <p className="mt-1 text-xs leading-5 text-slate-500">{n.note}</p>}
                {saved[n.term] && <p className="mt-1 text-xs text-emerald-600">{saved[n.term]}</p>}
              </div>
              <Button variant="ghost" onClick={() => onSave(n)} disabled={savingTerm === n.term}>
                {savingTerm === n.term ? '补录中…' : '加入生词本'}
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

function SimpleList({ title, items, tone }: { title: string; items: string[]; tone: 'emerald' | 'rose' }) {
  const toneClass = tone === 'emerald' ? 'bg-emerald-50 text-emerald-800' : 'bg-rose-50 text-rose-800'
  return (
    <div>
      <h3 className="mb-2 text-sm font-medium text-slate-700">{title}</h3>
      <ul className="space-y-2">
        {items.map((item, i) => (
          <li key={i} className={'rounded-md px-3 py-2 text-sm ' + toneClass}>
            {item}
          </li>
        ))}
      </ul>
    </div>
  )
}
