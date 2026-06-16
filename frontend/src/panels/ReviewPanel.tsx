import { useEffect, useState } from 'react'
import {
  api,
  type PassageResponse,
  type ReviewCard,
  type SubmitResponse,
  type WordCheckResult,
} from '../api'
import { Button, Card, ErrorNote, Spinner } from '../ui'

// 理解式背词：F3a 逐词理解背（来源句复述）+ F3b 语境造句背（短文翻译）。
// 不比对标准释义（ADR-004）：意思由用户当场重新理解出来。

export default function ReviewPanel() {
  const [tab, setTab] = useState<'a' | 'b'>('a')
  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <Button variant={tab === 'a' ? 'primary' : 'ghost'} onClick={() => setTab('a')}>
          逐词理解背 (F3a)
        </Button>
        <Button variant={tab === 'b' ? 'primary' : 'ghost'} onClick={() => setTab('b')}>
          语境造句背 (F3b)
        </Button>
      </div>
      {tab === 'a' ? <RecallExplain /> : <ContextPassage />}
    </div>
  )
}

function RecallExplain() {
  const [card, setCard] = useState<ReviewCard | null>(null)
  const [understanding, setUnderstanding] = useState('')
  const [result, setResult] = useState<SubmitResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [empty, setEmpty] = useState(false)

  async function load() {
    setBusy(true)
    setErr(null)
    setResult(null)
    setUnderstanding('')
    try {
      const next = await api.reviewNext()
      setCard(next)
      setEmpty(next === null)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  async function submit(tooEasy: boolean) {
    if (!card) return
    setBusy(true)
    setErr(null)
    try {
      const r = await api.reviewSubmit(card.entry_id, understanding, tooEasy)
      setResult(r)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (empty) {
    return (
      <Card>
        <p className="text-sm text-slate-500">今日没有到期复习的生词。先去「生词收集」攒一些吧。</p>
        <div className="mt-3">
          <Button onClick={load} variant="ghost">
            刷新
          </Button>
        </div>
      </Card>
    )
  }

  return (
    <Card>
      {busy && !card ? (
        <Spinner label="加载复习卡…" />
      ) : card ? (
        <>
          <div className="mb-1 text-xs text-slate-400">复习过 {card.review_count} 次</div>
          <h2 className="text-2xl font-semibold">{card.word}</h2>
          <p className="mt-2 text-sm text-slate-600">这个词在下面这些句子里，你理解是什么意思？（用自己的话说，中英文皆可）</p>
          <ul className="mt-2 space-y-1">
            {card.context_sentences.map((s, i) => (
              <li key={i} className="rounded bg-slate-50 px-3 py-2 text-sm text-slate-700">
                {s}
              </li>
            ))}
          </ul>
          {!result ? (
            <>
              <textarea
                value={understanding}
                onChange={(e) => setUnderstanding(e.target.value)}
                rows={3}
                placeholder="说说你的理解…"
                className="mt-3 w-full rounded-md border border-slate-300 p-3 text-sm focus:border-slate-500 focus:outline-none"
              />
              <div className="mt-3 flex gap-2">
                <Button onClick={() => submit(false)} disabled={busy}>
                  提交理解
                </Button>
                <Button onClick={() => submit(true)} disabled={busy} variant="ghost">
                  太简单（秒答）
                </Button>
                {busy && <Spinner />}
              </div>
            </>
          ) : (
            <div className="mt-4 space-y-2">
              <Verdict verdict={result.verdict} />
              {result.feedback && <p className="text-sm text-slate-600">{result.feedback}</p>}
              <p className="text-xs text-slate-400">
                状态：{result.status}
                {result.next_due && ` · 下次复习：${new Date(result.next_due).toLocaleString()}`}
              </p>
              <Button onClick={load}>下一张</Button>
            </div>
          )}
        </>
      ) : null}
      <ErrorNote message={err} />
    </Card>
  )
}

function ContextPassage() {
  const [topic, setTopic] = useState('')
  const [passage, setPassage] = useState<PassageResponse | null>(null)
  const [translation, setTranslation] = useState('')
  const [checks, setChecks] = useState<WordCheckResult[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function generate() {
    setBusy(true)
    setErr(null)
    setChecks(null)
    setTranslation('')
    try {
      const p = await api.reviewPassage(topic || undefined)
      setPassage(p)
      if (!p.text) setErr('没有可用于造句的到期生词。')
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function check() {
    if (!passage) return
    setBusy(true)
    setErr(null)
    try {
      const lemmas = passage.words.map((w) => w.lemma)
      const r = await api.reviewPassageCheck(passage.text, lemmas, translation)
      setChecks(r.checks)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <h2 className="mb-2 font-medium">语境造句背</h2>
      <p className="mb-3 text-sm text-slate-500">
        用一批到期生词造一段短文，你大致翻译，在语境中检验对每个词的理解。
      </p>
      <div className="flex gap-2">
        <input
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="话题（可选，贴近你关心的内容）"
          className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
        />
        <Button onClick={generate} disabled={busy}>
          造短文
        </Button>
      </div>

      {passage?.text && (
        <div className="mt-4 space-y-3">
          <p className="rounded-md bg-slate-50 p-3 text-sm leading-relaxed text-slate-800">
            {passage.text}
          </p>
          <div className="text-xs text-slate-400">
            目标词：{passage.words.map((w) => w.word).join('、')}
          </div>
          {!checks ? (
            <>
              <textarea
                value={translation}
                onChange={(e) => setTranslation(e.target.value)}
                rows={4}
                placeholder="用中文大致翻译这段短文…"
                className="w-full rounded-md border border-slate-300 p-3 text-sm focus:border-slate-500 focus:outline-none"
              />
              <Button onClick={check} disabled={busy}>
                检验理解
              </Button>
            </>
          ) : (
            <ul className="space-y-2">
              {checks.map((chk) => (
                <li key={chk.lemma} className="rounded-md border border-slate-100 px-3 py-2">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{chk.lemma}</span>
                    <Verdict verdict={chk.verdict} />
                  </div>
                  {chk.feedback && <p className="mt-1 text-sm text-slate-600">{chk.feedback}</p>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {busy && (
        <div className="mt-3">
          <Spinner />
        </div>
      )}
      <ErrorNote message={err} />
    </Card>
  )
}

function Verdict({ verdict }: { verdict: string }) {
  const map: Record<string, { text: string; cls: string }> = {
    correct: { text: '理解到位', cls: 'bg-emerald-100 text-emerald-700' },
    partial: { text: '沾边', cls: 'bg-amber-100 text-amber-700' },
    wrong: { text: '未掌握', cls: 'bg-rose-100 text-rose-700' },
  }
  const m = map[verdict] ?? { text: verdict, cls: 'bg-slate-100 text-slate-600' }
  return <span className={`rounded px-2 py-0.5 text-xs ${m.cls}`}>{m.text}</span>
}
