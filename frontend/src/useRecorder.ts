import { useCallback, useRef, useState } from 'react'

// MediaRecorder 录音 hook（docs/02 前端语音层）：start 开始采集，stop 返回整段音频 Blob。
// 浏览器普遍支持 audio/webm（Opus）；后端 STT 适配器交给 ffmpeg/服务端解码任意容器。

export type RecorderState = 'idle' | 'recording' | 'unsupported'

export function useRecorder() {
  const [state, setState] = useState<RecorderState>(
    typeof MediaRecorder === 'undefined' ? 'unsupported' : 'idle',
  )
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const streamRef = useRef<MediaStream | null>(null)

  const start = useCallback(async () => {
    if (state === 'unsupported') return
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    streamRef.current = stream
    const rec = new MediaRecorder(stream)
    chunksRef.current = []
    rec.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data)
    }
    rec.start()
    recorderRef.current = rec
    setState('recording')
  }, [state])

  const stop = useCallback(async (): Promise<Blob> => {
    return new Promise((resolve) => {
      const rec = recorderRef.current
      if (!rec) {
        resolve(new Blob())
        return
      }
      rec.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: rec.mimeType || 'audio/webm' })
        streamRef.current?.getTracks().forEach((t) => t.stop())
        streamRef.current = null
        recorderRef.current = null
        setState('idle')
        resolve(blob)
      }
      rec.stop()
    })
  }, [])

  return { state, start, stop }
}
