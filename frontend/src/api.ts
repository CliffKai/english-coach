// 后端 API 客户端。dev 下 /api 经 Vite 代理到后端（见 vite.config.ts）。

export interface HealthResponse {
  status: string
  version: string
}

export interface MetaResponse {
  version: string
  storage_backend: string
  voice_enabled: boolean
  features: {
    vocab_collection: boolean
    topic_practice: boolean
    comprehension_review: boolean
  }
}

async function getJson<T>(path: string): Promise<T> {
  const resp = await fetch(path)
  if (!resp.ok) throw new Error(`${path} → ${resp.status}`)
  return resp.json() as Promise<T>
}

export const api = {
  health: () => getJson<HealthResponse>('/api/health'),
  meta: () => getJson<MetaResponse>('/api/meta'),
}
