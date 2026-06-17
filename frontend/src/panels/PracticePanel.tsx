import { useState } from 'react'
import { api, type ScoreResponse, type TutorResponse } from '../api'
import { Button, Card, ErrorNote, Spinner } from '../ui'
import PracticeTopicInput from './PracticeTopicInput'
import ScoreResult from './ScoreResult'
import VoiceDialogue from './VoiceDialogue'

// 话题练习四模式：
//  - guided_write (2a) / guided_speak (2b)：练习模式，即时纠错 + 脚手架（TutorAgent）
//  - free_write (2c)：考试模式，延迟纠错 + 打分（ExaminerAgent）
//  - dialogue (2d)：考试模式，语音对话 + 打分（WebSocket + STT/TTS）

type Mode = 'guided_write' | 'free_write' | 'dialogue'

const MODES: { key: Mode; label: string; desc: string }[] = [
  { key: 'free_write', label: '自由写作打分 (2c)', desc: '考试模式：写完一次性打分 + 错题复盘' },
  { key: 'guided_write', label: '引导写作 (2a)', desc: '练习模式：即时纠错 + 脚手架引导' },
  { key: 'dialogue', label: '对话打分 (2d)', desc: '考试模式：语音对话，交卷后打分' },
]

export default function PracticePanel() {
  const [mode, setMode] = useState<Mode>('free_write')
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {MODES.map((m) => (
          <Button key={m.key} variant={mode === m.key ? 'primary' : 'ghost'} onClick={() => setMode(m.key)}>
            {m.label}
          </Button>
        ))}
      </div>
      <p className="text-sm text-slate-500">{MODES.find((m) => m.key === mode)!.desc}</p>
      {mode === 'free_write' && <FreeWrite />}
      {mode === 'guided_write' && <GuidedWrite />}
      {mode === 'dialogue' && <VoiceDialogue />}
    </div>
  )
}

function FreeWrite() {
  const [topic, setTopic] = useState('')
  const [text, setText] = useState('')
  const [result, setResult] = useState<ScoreResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function submit(endedEarly: boolean) {
    setBusy(true)
    setErr(null)
    try {
      const r = await api.practiceScore(text, 'free_write', topic || undefined, endedEarly)
      setResult(r)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <PracticeTopicInput
          mode="free_write"
          value={topic}
          onChange={setTopic}
          placeholder="话题（可选）"
          className="mb-2"
        />
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={8}
          placeholder="开始写作。考试模式不打断、不提示——写完点提交一次性打分。"
          className="w-full rounded-md border border-slate-300 p-3 text-sm focus:border-slate-500 focus:outline-none"
        />
        <div className="mt-3 flex items-center gap-3">
          <Button onClick={() => submit(false)} disabled={busy || !text.trim()}>
            提交打分
          </Button>
          <Button onClick={() => submit(true)} disabled={busy || !text.trim()} variant="ghost">
            提前交卷
          </Button>
          {busy && <Spinner label="打分中…" />}
        </div>
        <ErrorNote message={err} />
      </Card>
      {result && <ScoreResult result={result} />}
    </div>
  )
}

function GuidedWrite() {
  const [topic, setTopic] = useState('')
  const [text, setText] = useState('')
  const [turn, setTurn] = useState<TutorResponse | null>(null)
  const [history, setHistory] = useState<{ role: string; content: string }[]>([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function send() {
    setBusy(true)
    setErr(null)
    try {
      const r = await api.practiceTutor(text, 'guided_write', topic || undefined, history)
      setTurn(r)
      setHistory((h) => [
        ...h,
        { role: 'user', content: text },
        { role: 'assistant', content: r.follow_up },
      ])
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
        <PracticeTopicInput
          mode="guided_write"
          value={topic}
          onChange={setTopic}
          placeholder="话题（可选）"
          className="mb-2"
        />
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={4}
          placeholder="写一两句，教练会当场纠错并引导你继续。"
          className="w-full rounded-md border border-slate-300 p-3 text-sm focus:border-slate-500 focus:outline-none"
        />
        <div className="mt-3 flex items-center gap-3">
          <Button onClick={send} disabled={busy || !text.trim()}>
            提交，请教练引导
          </Button>
          {busy && <Spinner />}
        </div>
        <ErrorNote message={err} />
      </Card>

      {turn && (
        <Card>
          {turn.corrections.length > 0 ? (
            <>
              <h3 className="mb-2 font-medium">即时纠错</h3>
              <ul className="space-y-2">
                {turn.corrections.map((c, i) => (
                  <li key={i} className="text-sm">
                    <span className="text-rose-600 line-through">{c.original}</span>
                    <span className="mx-1">→</span>
                    <span className="text-emerald-700">{c.correction}</span>
                    {c.explanation && <p className="text-xs text-slate-500">{c.explanation}</p>}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="text-sm text-emerald-600">这一轮没有发现错误，做得好！</p>
          )}
          {turn.encouragement && (
            <p className="mt-3 text-sm text-slate-600">💪 {turn.encouragement}</p>
          )}
          {turn.scaffold && (
            <p className="mt-2 rounded-md bg-sky-50 p-3 text-sm text-sky-800">🪜 {turn.scaffold}</p>
          )}
          {turn.follow_up && (
            <p className="mt-2 text-sm italic text-slate-700">“{turn.follow_up}”</p>
          )}
        </Card>
      )}
    </div>
  )
}
