import { useEffect, useRef, useState } from 'react'
import {
  api,
  type BaselineResult,
  type ProvidersResponse,
  type Settings,
} from '../api'
import { Button, Card, ErrorNote, Estimated, Spinner } from '../ui'

// L5 配置与首次向导：
//  - 向导（needs_wizard 时高亮）：选 LLM provider/任务 → 测连通 → 水平基线测试 → 保存。
//  - 设置：改 model_config / 打分标准 / 目标分；数据导入/导出（JSON 全量 + Anki CSV）。
// 密钥不在前端管（在 .env，ADR-006）：向导只选 provider 名 + model，连接凭证后端按名查。

const TASKS: { key: 'scoring' | 'reasoning' | 'tokenize' | 'conversation'; label: string }[] = [
  { key: 'scoring', label: '评分 (scoring)' },
  { key: 'reasoning', label: '引导/复盘 (reasoning)' },
  { key: 'conversation', label: '对话 (conversation)' },
  { key: 'tokenize', label: '切词判断 (tokenize)' },
]

export default function SettingsPanel({ onSaved }: { onSaved?: () => void }) {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [providers, setProviders] = useState<ProvidersResponse | null>(null)
  const [busy, setBusy] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    Promise.all([api.getSettings(), api.providers()])
      .then(([s, p]) => {
        setSettings(s)
        setProviders(p)
      })
      .catch((e) => setErr((e as Error).message))
      .finally(() => setBusy(false))
  }, [])

  async function save() {
    if (!settings) return
    setBusy(true)
    setErr(null)
    setSaved(false)
    try {
      const s = await api.putSettings(settings)
      setSettings(s)
      setSaved(true)
      onSaved?.()
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (busy && !settings) return <Spinner label="加载配置…" />
  if (!settings || !providers) return <ErrorNote message={err} />

  const noProviders = providers.llm.length === 0

  return (
    <div className="space-y-4">
      {noProviders && (
        <Card className="border-amber-200 bg-amber-50">
          <p className="text-sm text-amber-800">
            还没有配置任何 LLM provider。请在后端 <code className="rounded bg-amber-100 px-1">backend/.env</code>{' '}
            按 <code className="rounded bg-amber-100 px-1">ENGLISH_COACH_LLM_PROVIDERS__&lt;名字&gt;__...</code>{' '}
            填入模型连接信息后重启后端（密钥不入库，ADR-006）。
          </p>
        </Card>
      )}

      <ModelConfigCard
        settings={settings}
        providers={providers}
        onChange={setSettings}
      />

      <BaselineCard
        baseline={settings.level_baseline}
        onAssessed={(b) => setSettings({ ...settings, level_baseline: b })}
      />

      <Card>
        <h2 className="mb-2 font-medium">打分标准</h2>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <label className="flex items-center gap-1.5">
            标准
            <select
              value={settings.scoring_standard}
              onChange={(e) => setSettings({ ...settings, scoring_standard: e.target.value })}
              className="rounded-md border border-slate-300 px-2 py-1"
            >
              <option value="IELTS">IELTS</option>
              <option value="TOEFL">TOEFL</option>
            </select>
          </label>
          <label className="flex items-center gap-1.5">
            目标分
            <input
              type="number"
              step="0.5"
              value={settings.target_band ?? ''}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  target_band: e.target.value === '' ? null : Number(e.target.value),
                })
              }
              className="w-20 rounded-md border border-slate-300 px-2 py-1"
            />
          </label>
        </div>
      </Card>

      <div className="flex items-center gap-3">
        <Button onClick={save} disabled={busy}>
          保存配置
        </Button>
        {busy && <Spinner />}
        {saved && <span className="text-sm text-emerald-600">已保存。</span>}
      </div>
      <ErrorNote message={err} />

      <DataCard />
    </div>
  )
}

function ModelConfigCard({
  settings,
  providers,
  onChange,
}: {
  settings: Settings
  providers: ProvidersResponse
  onChange: (s: Settings) => void
}) {
  const [test, setTest] = useState<Record<string, string>>({})
  // 本地草稿：每个任务的 provider/model 输入态。与 settings.model_config 分开，
  // 让用户「选了 provider、还没填 model」时 model 输入框可编辑（否则若直接以 model_config
  // 驱动、而空 model 又被规整成 null，输入框会被 disabled 锁死，永远填不进 model）。
  // 初值从已存配置回填。
  const [draft, setDraft] = useState<Record<string, { provider: string; model: string }>>(() => {
    const init: Record<string, { provider: string; model: string }> = {}
    for (const t of TASKS) {
      const a = settings.model_config[t.key]
      init[t.key] = { provider: a?.provider ?? '', model: a?.model ?? '' }
    }
    return init
  })

  function commit(task: (typeof TASKS)[number]['key'], provider: string, model: string) {
    setDraft((d) => ({ ...d, [task]: { provider, model } }))
    const mc = { ...settings.model_config }
    // 只有 provider 与 model **都非空**才算一条显式分配；否则置 null 回落到后端默认模型。
    // 不能存 { provider, model: '' }——后端 resolve_task_llm 会把它当显式分配、用空 model 名
    // 去调 provider（与「留空回落默认」的 UI 文案矛盾，且必然失败）。
    const p = provider.trim()
    const m = model.trim()
    mc[task] = p && m ? { provider: p, model: m } : null
    onChange({ ...settings, model_config: mc })
  }

  async function runTest(task: string, provider: string, model: string) {
    if (!provider || !model) {
      setTest((t) => ({ ...t, [task]: '请先选 provider 并填 model。' }))
      return
    }
    setTest((t) => ({ ...t, [task]: '测试中…' }))
    try {
      const r = await api.testLlm(provider, model)
      setTest((t) => ({ ...t, [task]: r.detail }))
    } catch (e) {
      setTest((t) => ({ ...t, [task]: (e as Error).message }))
    }
  }

  return (
    <Card>
      <h2 className="mb-1 font-medium">模型按任务分配 (ADR-006)</h2>
      <p className="mb-3 text-xs text-slate-500">
        每个任务选一个已配置的 provider 并填模型名；可点「测连通」验证。provider 或 model 留空则回落到后端默认模型。
      </p>
      <div className="space-y-3">
        {TASKS.map((t) => {
          const d = draft[t.key]
          return (
            <div key={t.key} className="rounded-md border border-slate-100 p-3">
              <div className="mb-2 flex items-center gap-2">
                <span className="text-sm font-medium">{t.label}</span>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <select
                  value={d.provider}
                  onChange={(e) => commit(t.key, e.target.value, d.model)}
                  className="rounded-md border border-slate-300 px-2 py-1 text-sm"
                >
                  <option value="">（默认）</option>
                  {providers.llm.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
                <input
                  value={d.model}
                  onChange={(e) => commit(t.key, d.provider, e.target.value)}
                  placeholder="模型名，如 deepseek-chat"
                  disabled={!d.provider}
                  className="flex-1 rounded-md border border-slate-300 px-2 py-1 text-sm disabled:bg-slate-50"
                />
                <Button variant="ghost" onClick={() => runTest(t.key, d.provider, d.model)}>
                  测连通
                </Button>
              </div>
              {test[t.key] && <p className="mt-1.5 text-xs text-slate-500">{test[t.key]}</p>}
            </div>
          )
        })}
      </div>
    </Card>
  )
}

function BaselineCard({
  baseline,
  onAssessed,
}: {
  baseline: string | null
  onAssessed: (b: string) => void
}) {
  const [prompt, setPrompt] = useState('')
  const [sample, setSample] = useState('')
  const [result, setResult] = useState<BaselineResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    api.baselinePrompt().then((p) => setPrompt(p.prompt)).catch(() => {})
  }, [])

  async function assess() {
    setBusy(true)
    setErr(null)
    try {
      const r = await api.baselineAssess(sample, prompt)
      setResult(r)
      onAssessed(r.baseline)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <div className="mb-1 flex items-center gap-2">
        <h2 className="font-medium">水平基线测试</h2>
        {baseline ? (
          <span className="rounded bg-emerald-100 px-2 py-0.5 text-xs text-emerald-700">当前 {baseline}</span>
        ) : (
          <span className="rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-700">未测</span>
        )}
      </div>
      <p className="mb-2 text-xs text-slate-500">
        写一小段英文，AI 估算你的 CEFR 等级。基线影响生词过滤与打分（07 红线）。
      </p>
      {prompt && <p className="mb-2 rounded-md bg-slate-50 p-2.5 text-sm text-slate-700">{prompt}</p>}
      <textarea
        value={sample}
        onChange={(e) => setSample(e.target.value)}
        rows={4}
        placeholder="Write about 80–120 words in English…"
        className="w-full rounded-md border border-slate-300 p-3 text-sm focus:border-slate-500 focus:outline-none"
      />
      <div className="mt-2 flex items-center gap-3">
        <Button onClick={assess} disabled={busy || sample.trim().length < 10}>
          估算我的水平
        </Button>
        {busy && <Spinner />}
      </div>
      {result && (
        <div className="mt-3 space-y-1 text-sm">
          <div className="flex items-center gap-2">
            <span className="text-lg font-semibold">{result.baseline}</span>
            {result.estimated_band != null && (
              <span className="text-slate-500">约雅思 {result.estimated_band}</span>
            )}
            <Estimated />
          </div>
          {result.rationale && <p className="text-slate-600">{result.rationale}</p>}
        </div>
      )}
      <ErrorNote message={err} />
    </Card>
  )
}

function DataCard() {
  const fileRef = useRef<HTMLInputElement>(null)
  const [replace, setReplace] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function onImport(file: File) {
    setBusy(true)
    setErr(null)
    setMsg(null)
    try {
      const bundle = JSON.parse(await file.text())
      const r = await api.importJson(bundle, replace)
      setMsg(
        `导入完成：生词 ${r.vocab_imported}` +
          `${r.vocab_merged ? `（另合并 ${r.vocab_merged} 个同词）` : ''}` +
          `、错题 ${r.errors_imported}、会话 ${r.sessions_imported}` +
          `${r.settings_imported ? '、配置已恢复' : ''}${r.skipped ? `（跳过 ${r.skipped} 条已存在）` : ''}。`,
      )
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  async function download(kind: 'json' | 'anki') {
    setBusy(true)
    setErr(null)
    setMsg(null)
    try {
      const blob = kind === 'json' ? await api.exportJson() : await api.exportAnki()
      const filename = kind === 'json' ? 'english-coach-backup.json' : 'english-coach-vocab.csv'
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <h2 className="mb-2 font-medium">数据导入 / 导出</h2>
      <p className="mb-3 text-xs text-slate-500">
        JSON 全量备份可原样导回本应用；Anki CSV 把生词本（卡背=来源句+你的理解，不存释义）对接 Anki 工作流。
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="ghost" onClick={() => download('json')} disabled={busy}>
          导出 JSON 全量备份
        </Button>
        <Button variant="ghost" onClick={() => download('anki')} disabled={busy}>
          导出生词本到 Anki (CSV)
        </Button>
      </div>
      <div className="mt-4 border-t border-slate-100 pt-3">
        <label className="mb-2 flex items-center gap-2 text-sm text-slate-600">
          <input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} />
          覆盖现有数据（先清空再导入；否则合并，id 冲突跳过）
        </label>
        <input
          ref={fileRef}
          type="file"
          accept="application/json,.json"
          onChange={(e) => e.target.files?.[0] && onImport(e.target.files[0])}
          className="block text-sm text-slate-600 file:mr-3 file:rounded-md file:border-0 file:bg-slate-900 file:px-3 file:py-1.5 file:text-sm file:text-white hover:file:bg-slate-700"
        />
        {busy && <div className="mt-2"><Spinner label="导入中…" /></div>}
        {msg && <p className="mt-2 text-sm text-emerald-600">{msg}</p>}
        <ErrorNote message={err} />
      </div>
    </Card>
  )
}
