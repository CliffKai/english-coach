import { useState } from 'react'
import { api } from '../api'
import { Button, ErrorNote, Spinner } from '../ui'

type Props = {
  mode: string
  value: string
  onChange: (value: string) => void
  placeholder: string
  className?: string
  disabled?: boolean
}

export default function PracticeTopicInput({
  mode,
  value,
  onChange,
  placeholder,
  className = '',
  disabled = false,
}: Props) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function suggest() {
    setBusy(true)
    setErr(null)
    try {
      const r = await api.practiceTopic(mode)
      onChange(r.topic)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={className}>
      <div className="flex flex-col gap-2 sm:flex-row">
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          disabled={disabled}
          className="min-w-0 flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none disabled:bg-slate-50"
        />
        <Button onClick={suggest} disabled={disabled || busy} variant="ghost">
          随机话题
        </Button>
      </div>
      {busy && (
        <div className="mt-2">
          <Spinner label="生成话题中…" />
        </div>
      )}
      <ErrorNote message={err} />
    </div>
  )
}
