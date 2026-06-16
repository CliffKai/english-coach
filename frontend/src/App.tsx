import { useEffect, useState } from 'react'
import { api, type MetaResponse } from './api'
import PracticePanel from './panels/PracticePanel'
import ReviewPanel from './panels/ReviewPanel'
import VocabPanel from './panels/VocabPanel'

// 三大功能 + 后端连通状态。L3/L4 已接入：F1 生词、F2 话题练习（含语音对话）、F3 背词。

type Conn = 'checking' | 'ok' | 'down'
type Tab = 'vocab' | 'practice' | 'review'

const TABS: { key: Tab; title: string; desc: string }[] = [
  { key: 'vocab', title: '生词收集', desc: '粘贴英文 → 切词 → 逐词问询 → 不认识者入库' },
  { key: 'practice', title: '话题练习', desc: '引导写/说（即时纠错）· 自由写作/语音对话（打分）' },
  { key: 'review', title: '理解式背单词', desc: '来源句复述 + 语境造句翻译，FSRS 调度' },
]

export default function App() {
  const [conn, setConn] = useState<Conn>('checking')
  const [meta, setMeta] = useState<MetaResponse | null>(null)
  const [tab, setTab] = useState<Tab>('vocab')

  useEffect(() => {
    api
      .meta()
      .then((m) => {
        setMeta(m)
        setConn('ok')
      })
      .catch(() => setConn('down'))
  }, [])

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-4xl items-center justify-between px-6 py-4">
          <div>
            <h1 className="text-xl font-semibold">English Coach</h1>
            <p className="text-sm text-slate-500">理解式英语学习 Agent</p>
          </div>
          <div className="flex items-center gap-3">
            <VoiceBadge meta={meta} />
            <ConnBadge conn={conn} version={meta?.version} />
          </div>
        </div>
        <nav className="mx-auto flex max-w-4xl gap-1 px-6">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium transition ${
                tab === t.key
                  ? 'border-slate-900 text-slate-900'
                  : 'border-transparent text-slate-500 hover:text-slate-700'
              }`}
            >
              {t.title}
            </button>
          ))}
        </nav>
      </header>

      <main className="mx-auto max-w-4xl px-6 py-8">
        <p className="mb-5 text-sm text-slate-600">{TABS.find((t) => t.key === tab)!.desc}</p>
        {conn === 'down' ? (
          <p className="rounded-md bg-rose-50 px-4 py-3 text-sm text-rose-700">
            后端未连接。请先启动后端：<code className="rounded bg-rose-100 px-1">uvicorn app.main:app --reload</code>
          </p>
        ) : (
          <>
            {tab === 'vocab' && <VocabPanel />}
            {tab === 'practice' && <PracticePanel />}
            {tab === 'review' && <ReviewPanel />}
          </>
        )}
      </main>
    </div>
  )
}

function ConnBadge({ conn, version }: { conn: Conn; version?: string }) {
  const map = {
    checking: { dot: 'bg-amber-400', text: '连接后端…' },
    ok: { dot: 'bg-emerald-500', text: `后端已连接 v${version ?? '?'}` },
    down: { dot: 'bg-rose-500', text: '后端未连接' },
  }[conn]
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-slate-200 px-3 py-1 text-xs text-slate-600">
      <span className={`h-2 w-2 rounded-full ${map.dot}`} />
      {map.text}
    </span>
  )
}

function VoiceBadge({ meta }: { meta: MetaResponse | null }) {
  if (!meta) return null
  const on = meta.voice_enabled
  return (
    <span
      className={`rounded-full px-3 py-1 text-xs ${
        on ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'
      }`}
      title={on ? 'STT + TTS 已配置' : '语音未配置（配置 STT/TTS provider 后启用对话）'}
    >
      {on ? '🎙 语音已启用' : '🎙 语音未配置'}
    </span>
  )
}
