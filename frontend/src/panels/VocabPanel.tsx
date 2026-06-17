import { useEffect, useState } from 'react'
import { api, type VocabCandidate, type VocabEntry } from '../api'
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

  // 补录生词（ADR-015）：从本文补词 / 凭空加词。
  const [fromTextWord, setFromTextWord] = useState('')
  const [manualWord, setManualWord] = useState('')
  const [manualSentence, setManualSentence] = useState('')
  const [manualBusy, setManualBusy] = useState(false)
  const [manualErr, setManualErr] = useState<string | null>(null)
  const [manualMsg, setManualMsg] = useState<string | null>(null)

  const [vocab, setVocab] = useState<VocabEntry[] | null>(null)
  const [vocabBusy, setVocabBusy] = useState(false)
  const [vocabErr, setVocabErr] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  async function loadVocab(opts: { quiet?: boolean } = {}) {
    if (!opts.quiet) setVocabBusy(true)
    setVocabErr(null)
    try {
      setVocab(await api.vocabList())
    } catch (e) {
      setVocabErr((e as Error).message)
    } finally {
      if (!opts.quiet) setVocabBusy(false)
    }
  }

  useEffect(() => {
    void loadVocab()
  }, [])

  async function addFromText() {
    if (!fromTextWord.trim()) return
    setManualBusy(true)
    setManualErr(null)
    setManualMsg(null)
    try {
      const entry = await api.vocabManual(fromTextWord.trim(), { text })
      const ctx = entry.context_sentences[0]
      setManualMsg(
        ctx ? `已补录「${entry.word}」，来源句：${ctx}` : `已补录「${entry.word}」（该词未在本文中找到，已入库为无语境词）`,
      )
      setFromTextWord('')
      await loadVocab({ quiet: true })
    } catch (e) {
      setManualErr((e as Error).message)
    } finally {
      setManualBusy(false)
    }
  }

  async function addManual() {
    if (!manualWord.trim()) return
    setManualBusy(true)
    setManualErr(null)
    setManualMsg(null)
    try {
      const entry = await api.vocabManual(manualWord.trim(), {
        sentence: manualSentence.trim() || undefined,
      })
      const ctx = entry.context_sentences[0]
      const how = manualSentence.trim() ? '你的例句' : 'AI 造句'
      setManualMsg(ctx ? `已补录「${entry.word}」（${how}）：${ctx}` : `已补录「${entry.word}」（无来源句）`)
      setManualWord('')
      setManualSentence('')
      await loadVocab({ quiet: true })
    } catch (e) {
      setManualErr((e as Error).message)
    } finally {
      setManualBusy(false)
    }
  }

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
      await loadVocab({ quiet: true })
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function deleteEntry(entry: VocabEntry) {
    const ok = window.confirm(`从词库删除「${entry.word}」？删除后不会再参与背词或导出。`)
    if (!ok) return
    setDeletingId(entry.id)
    setVocabErr(null)
    try {
      await api.vocabDelete(entry.id)
      setVocab((items) => (items ? items.filter((item) => item.id !== entry.id) : items))
    } catch (e) {
      setVocabErr((e as Error).message)
    } finally {
      setDeletingId(null)
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

      <Card>
        <h2 className="mb-1 font-medium">补录生词</h2>
        <p className="mb-3 text-sm text-slate-500">
          系统按你的水平自动过滤候选——若它漏掉了你其实不认识的词，在这里手动补。存的仍是来源句，不存释义（ADR-004）。
        </p>

        <div className="space-y-2 rounded-md border border-slate-100 p-3">
          <p className="text-sm font-medium text-slate-700">从本文补词</p>
          <p className="text-xs text-slate-500">
            上面文本框里出现、但没被切出来问的词——填进来，自动取它在本文中的句子作来源句。
          </p>
          <div className="flex gap-2">
            <input
              value={fromTextWord}
              onChange={(e) => setFromTextWord(e.target.value)}
              placeholder="本文中的某个词"
              disabled={!text.trim()}
              className="flex-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-slate-500 focus:outline-none disabled:bg-slate-50"
            />
            <Button onClick={addFromText} disabled={manualBusy || !text.trim() || !fromTextWord.trim()}>
              补录
            </Button>
          </div>
          {!text.trim() && <p className="text-xs text-slate-400">先在上方粘贴文本后可用。</p>}
        </div>

        <div className="mt-3 space-y-2 rounded-md border border-slate-100 p-3">
          <p className="text-sm font-medium text-slate-700">凭空加词</p>
          <p className="text-xs text-slate-500">
            脱离文本直接加一个词。可自填例句；留空则由 AI 造一个例句作来源句。
          </p>
          <div className="flex gap-2">
            <input
              value={manualWord}
              onChange={(e) => setManualWord(e.target.value)}
              placeholder="单词"
              className="w-40 rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-slate-500 focus:outline-none"
            />
            <input
              value={manualSentence}
              onChange={(e) => setManualSentence(e.target.value)}
              placeholder="例句（可选，留空则 AI 造句）"
              className="flex-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-slate-500 focus:outline-none"
            />
            <Button onClick={addManual} disabled={manualBusy || !manualWord.trim()}>
              补录
            </Button>
          </div>
        </div>

        <div className="mt-3 flex items-center gap-3">
          {manualBusy && <Spinner />}
          {manualMsg && <span className="text-sm text-emerald-600">{manualMsg}</span>}
        </div>
        <ErrorNote message={manualErr} />
      </Card>

      <Card>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="font-medium">我的词库</h2>
            <p className="mt-1 text-sm text-slate-500">当前共 {vocab?.length ?? 0} 个词。</p>
          </div>
          <Button variant="ghost" onClick={() => void loadVocab()} disabled={vocabBusy}>
            刷新
          </Button>
        </div>

        {vocabBusy && !vocab ? (
          <Spinner label="加载词库…" />
        ) : vocab && vocab.length > 0 ? (
          <ul className="divide-y divide-slate-100 rounded-md border border-slate-100">
            {vocab.map((entry) => (
              <li key={entry.id} className="flex flex-col gap-3 px-3 py-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-slate-900">{entry.word}</span>
                    {entry.lemma !== entry.word && (
                      <span className="text-xs text-slate-400">lemma: {entry.lemma}</span>
                    )}
                    <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
                      {entry.status}
                    </span>
                    <span className="text-xs text-slate-400">
                      复习 {entry.fsrs_state.review_count} 次
                    </span>
                  </div>
                  {entry.context_sentences[0] && (
                    <p className="mt-1 break-words text-sm text-slate-500">
                      {entry.context_sentences[0]}
                    </p>
                  )}
                </div>
                <Button
                  variant="danger"
                  onClick={() => void deleteEntry(entry)}
                  disabled={deletingId === entry.id}
                >
                  {deletingId === entry.id ? '删除中…' : '删除'}
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-slate-500">词库里还没有生词。</p>
        )}
        <ErrorNote message={vocabErr} />
      </Card>
    </div>
  )
}
