import { useEffect, useState } from 'react'
import { api, type MetaResponse } from './api'

// L0 脚手架首页：四大功能区占位 + 后端连通状态。
// 各功能区随实现层级（L3/L4）逐步替换为真实页面。

type Conn = 'checking' | 'ok' | 'down'

const FEATURES = [
  {
    key: 'vocab_collection' as const,
    title: '生词收集',
    desc: '粘贴英文 → 切词 → 逐词问询 → 不认识者连同来源句入库',
    layer: 'L3',
  },
  {
    key: 'topic_practice' as const,
    title: '话题练习',
    desc: '四模式：引导写/说（即时纠错）· 自由写作/对话（延迟纠错 + 打分）',
    layer: 'L3 / L4',
  },
  {
    key: 'comprehension_review' as const,
    title: '理解式背单词',
    desc: '来源句复述理解 + 语境造句翻译，FSRS 调度',
    layer: 'L3 / L4',
  },
]

export default function App() {
  const [conn, setConn] = useState<Conn>('checking')
  const [meta, setMeta] = useState<MetaResponse | null>(null)

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
          <ConnBadge conn={conn} version={meta?.version} />
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-6 py-10">
        <p className="mb-6 text-sm text-slate-600">
          脚手架阶段（L0）。三大功能区占位中，按 <code className="rounded bg-slate-200 px-1">docs/07</code> 依赖顺序逐层接入。
        </p>
        <div className="grid gap-4 sm:grid-cols-3">
          {FEATURES.map((f) => (
            <FeatureCard
              key={f.key}
              title={f.title}
              desc={f.desc}
              layer={f.layer}
              ready={meta?.features[f.key] ?? false}
            />
          ))}
        </div>
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

function FeatureCard({
  title,
  desc,
  layer,
  ready,
}: {
  title: string
  desc: string
  layer: string
  ready: boolean
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="font-medium">{title}</h2>
        <span
          className={`rounded px-2 py-0.5 text-xs ${
            ready ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'
          }`}
        >
          {ready ? '可用' : `即将到来 · ${layer}`}
        </span>
      </div>
      <p className="text-sm text-slate-500">{desc}</p>
    </div>
  )
}
