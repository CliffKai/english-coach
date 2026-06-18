import { useEffect, useState } from 'react'
import { api, type TodayResponse } from '../api'
import { Button, Card, ErrorNote, Spinner } from '../ui'

// L5「今日学习」聚合首页：把日常复习/练习任务串成「今天该干什么」——
// 待复习生词(FSRS) + 待巩固错题(resolved=False) + 推荐一个话题。
// 只读聚合（后端 /api/today 不调 LLM）；上游空则各区显示「无待办」而非报错。

export default function TodayPanel({ onGoto }: { onGoto: (tab: 'vocab' | 'practice' | 'review') => void }) {
  const [data, setData] = useState<TodayResponse | null>(null)
  const [busy, setBusy] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    api
      .today()
      .then((d) => setData(d))
      .catch((e) => setErr((e as Error).message))
      .finally(() => setBusy(false))
  }, [])

  if (busy) return <Spinner label="加载今日学习…" />
  if (err) return <ErrorNote message={err} />
  if (!data) return null

  const empty =
    data.due_count === 0 && data.unresolved_error_count === 0

  return (
    <div className="space-y-4">
      {empty && (
        <Card>
          <p className="text-sm text-slate-600">
            今天没有到期的生词，也没有待巩固的错题。去攒点生词或做一次练习吧 👇
          </p>
        </Card>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        {/* 待复习生词 */}
        <Card>
          <div className="flex items-baseline justify-between">
            <h2 className="font-medium">待复习生词</h2>
            <span className="text-2xl font-semibold text-slate-900">{data.due_count}</span>
          </div>
          <p className="mt-1 text-xs text-slate-500">FSRS 调度的到期词，复习它们最划算。</p>
          {data.due_preview.length > 0 ? (
            <ul className="mt-3 flex flex-wrap gap-1.5">
              {data.due_preview.map((w) => (
                <li key={w.entry_id} className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-700">
                  {w.word}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-sm text-slate-400">暂无到期生词。</p>
          )}
          <div className="mt-3">
            <Button onClick={() => onGoto('review')} disabled={data.due_count === 0}>
              去背词
            </Button>
          </div>
        </Card>

        {/* 待巩固错题 */}
        <Card>
          <div className="flex items-baseline justify-between">
            <h2 className="font-medium">待巩固错题</h2>
            <span className="text-2xl font-semibold text-slate-900">{data.unresolved_error_count}</span>
          </div>
          <p className="mt-1 text-xs text-slate-500">上次练习里还没解决的错误，盯着改。</p>
          {data.error_preview.length > 0 ? (
            <ul className="mt-3 space-y-1.5">
              {data.error_preview.map((e) => (
                <li key={e.id} className="rounded-md border border-slate-100 px-2.5 py-1.5 text-xs">
                  <span className="rounded bg-rose-100 px-1.5 py-0.5 text-rose-700">{e.type}</span>
                  <span className="ml-2 text-slate-500 line-through">{e.original}</span>
                  <span className="ml-1 text-emerald-700">{e.correction}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-sm text-slate-400">暂无待巩固错题。</p>
          )}
        </Card>
      </div>

      {/* 推荐话题 */}
      <Card>
        <h2 className="font-medium">推荐话题练习</h2>
        <p className="mt-1 text-xs text-slate-500">
          {data.recommended_topic.reason === 'weak_area'
            ? '针对你近期常错的话题，练一练。'
            : '今日话题，换换思路。'}
        </p>
        <p className="mt-3 rounded-md bg-slate-50 p-3 text-sm text-slate-800">
          {data.recommended_topic.topic}
        </p>
        <div className="mt-3">
          <Button onClick={() => onGoto('practice')}>去练习</Button>
        </div>
      </Card>
    </div>
  )
}
