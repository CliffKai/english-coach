import type { ScoreResponse } from '../api'
import { Card, Estimated } from '../ui'

// 考试模式结算展示：维度分 + 综合分 + 错题清单 + 复盘。F2c/F2d 共用。
// 发音/流利度维度可能空缺（score=null，未接发音评估，ADR-013）。

export default function ScoreResult({ result }: { result: ScoreResponse }) {
  return (
    <div className="space-y-4">
      <Card>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-medium">
            {result.standard} 评分
            {result.overall !== null && (
              <span className="ml-2 text-2xl font-bold text-slate-900">{result.overall}</span>
            )}
          </h2>
          {result.estimated && <Estimated />}
        </div>
        <ul className="space-y-2">
          {result.dimensions.map((d) => (
            <li key={d.key} className="flex items-start justify-between gap-3">
              <div>
                <span className="text-sm font-medium text-slate-700">{d.label}</span>
                {d.comment && <p className="text-xs text-slate-500">{d.comment}</p>}
              </div>
              <span className="shrink-0 text-sm font-semibold">
                {d.score === null ? (
                  <span className="text-slate-400">未评</span>
                ) : (
                  d.score
                )}
              </span>
            </li>
          ))}
        </ul>
      </Card>

      {result.report.summary && (
        <Card>
          <h3 className="mb-1 font-medium">复盘</h3>
          <p className="text-sm text-slate-600">{result.report.summary}</p>
          {result.report.patterns.length > 0 && (
            <ul className="mt-2 list-inside list-disc text-sm text-slate-500">
              {result.report.patterns.map((p, i) => (
                <li key={i}>{p}</li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {result.errors.length > 0 && (
        <Card>
          <h3 className="mb-2 font-medium">错题清单（已存入错题本）</h3>
          <ul className="space-y-2">
            {result.errors.map((e) => (
              <li key={e.id} className="rounded-md border border-slate-100 px-3 py-2 text-sm">
                <span className="mr-2 rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500">
                  {e.type}
                </span>
                <span className="text-rose-600 line-through">{e.original}</span>
                <span className="mx-1">→</span>
                <span className="text-emerald-700">{e.correction}</span>
                {e.explanation && <p className="mt-1 text-xs text-slate-500">{e.explanation}</p>}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}
