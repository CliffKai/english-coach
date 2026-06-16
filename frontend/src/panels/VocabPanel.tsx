import { useState } from 'react'
import { api, type VocabCandidate } from '../api'
import { Button, Card, ErrorNote, Spinner } from '../ui'

// F1 生词收集：粘贴文本 → 切词候选 → 逐词「认识/跳过/不认识」→「不认识」入库（含来源句）。

type Decision = 'unknown' | 'known' | undefined

export default function VocabPanel() {
  const [text, setText] = useState('')
  const [candidates, setCandidates] = useState<VocabCandidate[] | null>(null)
  const [decisions, setDecisions] = useState<Record<string, Decision>>({})
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [savedCount, setSavedCount] = useState<number | null>(null)

  async function extract() {
    setBusy(true)
    setErr(null)
    setSavedCount(null)
    try {
      const resp = await api.vocabExtract(text)
      setCandidates(resp.candidates)
      setDecisions({})
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function collect() {
    if (!candidates) return
    const items = candidates
      .filter((c) => decisions[c.lemma] === 'unknown')
      .map((c) => ({ word: c.word, lemma: c.lemma, context_sentences: c.context_sentences }))
    if (items.length === 0) {
      setErr('没有标记为「不认识」的词。')
      return
    }
    setBusy(true)
    setErr(null)
    try {
      const saved = await api.vocabCollect(items)
      setSavedCount(saved.length)
      setCandidates(null)
      setText('')
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <h2 className="mb-2 font-medium">粘贴英文文本</h2>
        <p className="mb-3 text-sm text-slate-500">
          切词 → 按你的水平基线/词频过滤 → 只问「可能不认识」的词。不认识的连同来源句入库（不存释义，ADR-004）。
        </p>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={5}
          placeholder="Paste an English paragraph here…"
          className="w-full rounded-md border border-slate-300 p-3 text-sm focus:border-slate-500 focus:outline-none"
        />
        <div className="mt-3 flex items-center gap-3">
          <Button onClick={extract} disabled={busy || !text.trim()}>
            切词
          </Button>
          {busy && <Spinner />}
          {savedCount !== null && (
            <span className="text-sm text-emerald-600">已入库 {savedCount} 个生词。</span>
          )}
        </div>
        <ErrorNote message={err} />
      </Card>

      {candidates && (
        <Card>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-medium">逐词判断（{candidates.length} 个候选）</h2>
            <Button onClick={collect} disabled={busy}>
              入库「不认识」的词
            </Button>
          </div>
          {candidates.length === 0 ? (
            <p className="text-sm text-slate-500">没有候选生词——这段文本对你的水平都算已掌握。</p>
          ) : (
            <ul className="space-y-2">
              {candidates.map((c) => (
                <li
                  key={c.lemma}
                  className="flex items-center justify-between rounded-md border border-slate-100 px-3 py-2"
                >
                  <div>
                    <span className="font-medium">{c.word}</span>
                    <span className="ml-2 text-xs text-slate-400">zipf {c.zipf.toFixed(1)}</span>
                    {c.context_sentences[0] && (
                      <p className="mt-0.5 text-xs text-slate-500">{c.context_sentences[0]}</p>
                    )}
                  </div>
                  <div className="flex gap-2">
                    <Button
                      variant={decisions[c.lemma] === 'unknown' ? 'danger' : 'ghost'}
                      onClick={() => setDecisions((d) => ({ ...d, [c.lemma]: 'unknown' }))}
                    >
                      不认识
                    </Button>
                    <Button
                      variant={decisions[c.lemma] === 'known' ? 'primary' : 'ghost'}
                      onClick={() => setDecisions((d) => ({ ...d, [c.lemma]: 'known' }))}
                    >
                      认识
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}
    </div>
  )
}
