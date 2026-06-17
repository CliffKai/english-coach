import { useCallback, useEffect, useRef, useState } from 'react'
import type { ScoreResponse } from '../api'
import { useRecorder } from '../useRecorder'
import { Button, Card, ErrorNote, Spinner } from '../ui'
import PracticeTopicInput from './PracticeTopicInput'
import ScoreResult from './ScoreResult'

// F2d 语音对话打分（WebSocket + MediaRecorder + STT/TTS 流式，docs/02）。
// 一条 WS = 一场对话：录音 → 后端 STT → 考官回话(文本+TTS音频) → 来回 → 交卷打分。
// 考试模式零脚手架（ADR-005）：对话过程不纠错；发音/流利度需发音评估 API 才有真分（ADR-013）。

type Line = { who: 'you' | 'examiner'; text: string }

function wsUrl(): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/ws/practice/dialogue`
}

export default function VoiceDialogue() {
  const [topic, setTopic] = useState('')
  const [connected, setConnected] = useState(false)
  const [lines, setLines] = useState<Line[]>([])
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<ScoreResponse | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const audioChunksRef = useRef<BlobPart[]>([])
  const audioMimeRef = useRef<string>('audio/mpeg') // 由 audio_start 帧带的 content_type 决定
  const { state: recState, start, stop } = useRecorder()

  const cleanup = useCallback(() => {
    wsRef.current?.close()
    wsRef.current = null
    setConnected(false)
  }, [])

  useEffect(() => cleanup, [cleanup])

  function connect() {
    setErr(null)
    setResult(null)
    setLines([])
    const ws = new WebSocket(wsUrl())
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      ws.send(JSON.stringify({ type: 'start', topic: topic || undefined }))
    }
    ws.onclose = () => setConnected(false)
    ws.onerror = () => setErr('WebSocket 连接出错。')
    ws.onmessage = (ev) => {
      if (ev.data instanceof ArrayBuffer) {
        audioChunksRef.current.push(ev.data)
        return
      }
      const msg = JSON.parse(ev.data)
      switch (msg.type) {
        case 'transcript':
          if (msg.text) {
            setLines((l) => [...l, { who: 'you', text: msg.text }])
            setBusy(true) // 有内容 → 等考官回话（reply/audio 帧随后到）
          } else {
            // 空转写（静音/未识别）：后端跳过 reply/audio，不会再有终结帧 → 当场解除忙碌。
            setErr('没有听清，请再说一次。')
            setBusy(false)
          }
          break
        case 'reply':
          setLines((l) => [...l, { who: 'examiner', text: msg.text }])
          break
        case 'audio_start':
          audioChunksRef.current = []
          audioMimeRef.current = msg.content_type || 'audio/mpeg'
          break
        case 'audio_end':
          playAudio(audioChunksRef.current, audioMimeRef.current)
          audioChunksRef.current = []
          setBusy(false)
          break
        case 'result':
          setResult(msg as ScoreResponse)
          setBusy(false)
          cleanup()
          break
        case 'error':
          setErr(msg.detail)
          setBusy(false)
          break
      }
    }
  }

  async function toggleRecord() {
    if (recState === 'recording') {
      const blob = await stop()
      const buf = await blob.arrayBuffer()
      wsRef.current?.send(buf)
      setBusy(true)
    } else {
      setErr(null) // 清掉上一轮「没听清」之类的提示
      await start()
    }
  }

  function submit(endedEarly: boolean) {
    wsRef.current?.send(JSON.stringify({ type: 'submit', ended_early: endedEarly }))
    setBusy(true)
  }

  if (recState === 'unsupported') {
    return (
      <Card>
        <ErrorNote message="当前浏览器不支持 MediaRecorder 录音，无法进行语音对话。" />
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      <Card>
        {!connected && !result ? (
          <>
            <PracticeTopicInput
              mode="dialogue"
              value={topic}
              onChange={setTopic}
              placeholder="对话话题（可选，如 travel / technology）"
              className="mb-3"
            />
            <Button onClick={connect}>开始语音对话</Button>
            <p className="mt-2 text-xs text-slate-400">
              考试模式：对话中不纠错、不提示。发音/流利度评分需配置发音评估 API，否则该两维标「未评」。
            </p>
          </>
        ) : connected ? (
          <>
            <div className="mb-3 flex items-center justify-between">
              <span className="inline-flex items-center gap-2 text-sm text-emerald-600">
                <span className="h-2 w-2 rounded-full bg-emerald-500" /> 对话中
              </span>
              <div className="flex gap-2">
                <Button onClick={() => submit(false)} disabled={busy} variant="ghost">
                  交卷打分
                </Button>
                <Button onClick={() => submit(true)} disabled={busy} variant="ghost">
                  提前交卷
                </Button>
              </div>
            </div>
            <div className="mb-3 max-h-72 space-y-2 overflow-y-auto">
              {lines.map((l, i) => (
                <div
                  key={i}
                  className={`rounded-md px-3 py-2 text-sm ${
                    l.who === 'you'
                      ? 'bg-slate-100 text-slate-800'
                      : 'bg-sky-50 text-sky-900'
                  }`}
                >
                  <span className="mr-2 text-xs font-medium text-slate-400">
                    {l.who === 'you' ? '你' : '考官'}
                  </span>
                  {l.text}
                </div>
              ))}
              {busy && <Spinner label="处理中…" />}
            </div>
            <Button onClick={toggleRecord} variant={recState === 'recording' ? 'danger' : 'primary'}>
              {recState === 'recording' ? '⏹ 停止并发送' : '🎙 按住说（点击开始）'}
            </Button>
          </>
        ) : null}
        <ErrorNote message={err} />
      </Card>
      {result && <ScoreResult result={result} />}
    </div>
  )
}

function playAudio(chunks: BlobPart[], mime: string) {
  if (chunks.length === 0) return
  const blob = new Blob(chunks, { type: mime })
  const url = URL.createObjectURL(blob)
  const audio = new Audio(url)
  audio.onended = () => URL.revokeObjectURL(url)
  void audio.play().catch(() => URL.revokeObjectURL(url))
}
