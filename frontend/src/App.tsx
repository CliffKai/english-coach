import { useCallback, useEffect, useState } from 'react'
import { api, type MetaResponse } from './api'
import PracticePanel from './panels/PracticePanel'
import ReviewPanel from './panels/ReviewPanel'
import SettingsPanel from './panels/SettingsPanel'
import TodayPanel from './panels/TodayPanel'
import VocabPanel from './panels/VocabPanel'

// L5 起：「今日」聚合首页串起平行三大功能 + 配置向导/设置。
// 三大功能：F1 生词、F2 话题练习（含语音对话）、F3 背词。

type Conn = 'checking' | 'ok' | 'down'
type Tab = 'today' | 'vocab' | 'practice' | 'review' | 'settings'

const TABS: { key: Tab; title: string; desc: string }[] = [
  { key: 'today', title: '今日', desc: '把待复习生词、待巩固错题、推荐话题串成今天的学习清单' },
  { key: 'vocab', title: '生词收集', desc: '粘贴英文 → 切词 → 逐词问询 → 不认识者入库' },
  { key: 'practice', title: '话题练习', desc: '引导写/说（即时纠错）· 自由写作/语音对话（打分）' },
  { key: 'review', title: '理解式背单词', desc: '来源句复述 + 语境造句翻译，FSRS 调度' },
  { key: 'settings', title: '设置', desc: '配置模型、水平基线测试、数据导入导出' },
]

export default function App() {
  const [conn, setConn] = useState<Conn>('checking')
  const [meta, setMeta] = useState<MetaResponse | null>(null)
  const [tab, setTab] = useState<Tab>('today')
  const activeTab = TABS.find((t) => t.key === tab)!

  const refreshMeta = useCallback(() => {
    return api
      .meta()
      .then((m) => {
        setMeta(m)
        setConn('ok')
      })
      .catch(() => setConn('down'))
  }, [])

  useEffect(() => {
    refreshMeta()
  }, [refreshMeta])

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 lg:flex">
      <aside className="border-b border-slate-200 bg-white lg:sticky lg:top-0 lg:flex lg:h-screen lg:w-72 lg:shrink-0 lg:flex-col lg:border-b-0 lg:border-r">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-5 px-6 py-5 lg:h-full lg:max-w-none lg:px-5 lg:py-6">
          <div>
            <h1 className="text-xl font-semibold">English Coach</h1>
            <p className="text-sm text-slate-500">理解式英语学习 Agent</p>
          </div>

          <nav className="-mx-1 flex gap-1 overflow-x-auto pb-1 lg:mx-0 lg:flex-col lg:overflow-visible lg:pb-0">
            {TABS.map((t) => {
              const active = tab === t.key
              return (
                <button
                  key={t.key}
                  onClick={() => setTab(t.key)}
                  aria-current={active ? 'page' : undefined}
                  className={`flex min-w-max items-center rounded-md border px-3 py-2 text-left text-sm font-medium transition lg:min-w-0 lg:w-full ${
                    active
                      ? 'border-slate-900 bg-slate-900 text-white shadow-sm'
                      : 'border-transparent text-slate-600 hover:bg-slate-100 hover:text-slate-900'
                  }`}
                >
                  {t.title}
                </button>
              )
            })}
          </nav>

          <div className="flex flex-wrap items-center gap-2 lg:mt-auto lg:flex-col lg:items-stretch">
            <VoiceBadge meta={meta} />
            <ConnBadge conn={conn} version={meta?.version} />
          </div>
        </div>
      </aside>

      <main className="mx-auto w-full max-w-5xl px-6 py-8 lg:px-8">
        <p className="mb-5 text-sm text-slate-600">{activeTab.desc}</p>
        {conn === 'down' ? (
          <p className="rounded-md bg-rose-50 px-4 py-3 text-sm text-rose-700">
            后端未连接。请先启动后端：<code className="rounded bg-rose-100 px-1">uvicorn app.main:app --reload</code>
          </p>
        ) : (
          <>
            {meta?.setup.needs_wizard && tab !== 'settings' && (
              <WizardBanner meta={meta} onGoto={() => setTab('settings')} />
            )}
            {tab === 'today' && <TodayPanel onGoto={setTab} />}
            {tab === 'vocab' && <VocabPanel />}
            {tab === 'practice' && <PracticePanel />}
            {tab === 'review' && <ReviewPanel />}
            {tab === 'settings' && <SettingsPanel onSaved={refreshMeta} />}
          </>
        )}
      </main>
    </div>
  )
}

function WizardBanner({ meta, onGoto }: { meta: MetaResponse; onGoto: () => void }) {
  // 首次引导提示：缺模型或缺基线时督促去「设置」走完配置向导（07 / ADR-009）。
  const needs: string[] = []
  if (!meta.setup.has_llm_provider) needs.push('配置模型 provider')
  if (!meta.setup.has_baseline) needs.push('测一次水平基线')
  return (
    <div className="mb-5 flex items-center justify-between rounded-md border border-amber-200 bg-amber-50 px-4 py-3">
      <p className="text-sm text-amber-800">
        首次使用还需：{needs.join(' · ')}。完成后各功能才能正常工作。
      </p>
      <button
        onClick={onGoto}
        className="rounded-md bg-amber-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-500"
      >
        去配置
      </button>
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
