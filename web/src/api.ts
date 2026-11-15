// Typed client for api/app.py. /api/ask streams Server-Sent Events over a POST, read here with fetch.

export type Server = { url: string; ok: boolean; name: string; num_chunks: number | null; corpus_version: string | null; examples?: string[] }
export type Status = { servers: Server[]; helper: boolean; model: boolean; recording: boolean }

export type Citation = {
  id: number | string; title: string; url: string; updated: string; text: string; score: number
  excerpt?: string; source?: string; source_name?: string; server?: string
}
export type Result = {
  status: 'answered' | 'declined'; answer: string; citations: Citation[]
  urgent: { kind: 'crisis' | 'emergency'; message: string } | null
  checks?: { removed_sentences: number }
}
export type Request = { endpoint: string; request_bytes: number; response_bytes: number }
export type ServerTrace = {
  server: string; corpus_version: string; num_chunks: number; requests: Request[]
  timings: Record<string, number>; fetched: number; used: number; ciphertext_sample?: string
}
export type Trace = {
  multi?: boolean; total_seconds: number; upload_bytes: number; download_bytes: number
  timings?: Record<string, number>; servers?: ServerTrace[]; ciphertext_sample?: string
  requests?: Request[]; num_chunks?: number; server?: string; mode?: Record<string, string>
}
export type Route = {
  route: string; upstream: string; requests: number; bytes: number; words: number; found: string[]
  matches: { word: string; path: string; context: string }[]; sample_hex: string; chance_by_luck: number
}
export type Proof = { words: string[]; routes: Route[]; since: string; recording: boolean }
export type Plain = { entry?: { question: string; returned: { title: string; url: string }[]; time: string; client: string }; error?: string }
export type Stage = 'embedding' | 'encrypting' | 'scoring' | 'fetching' | 'answering'
export type ApiError = { stage: string; message: string; fix: string }

export type Event =
  | { type: 'start'; data: { question: string; since: string; servers: string[] } }
  | { type: 'stage'; data: { name: Stage; seconds: number } }
  | { type: 'answer'; data: { result: Result; trace: Trace } }
  | { type: 'plain'; data: Plain }
  | { type: 'proof'; data: Proof }
  | { type: 'done'; data: Record<string, never> }
  | { type: 'error'; data: ApiError }

export async function getStatus(): Promise<Status> {
  const r = await fetch('/api/status')
  if (!r.ok) throw new Error(`status ${r.status}`)
  return r.json()
}

export async function ask(question: string, compare: boolean, servers: string[], onEvent: (e: Event) => void, signal?: AbortSignal) {
  const r = await fetch('/api/ask', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question, compare, servers }), signal,
  })
  if (!r.ok || !r.body) throw new Error((await r.text()) || `ask failed (${r.status})`)
  const reader = r.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let i: number
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, i)
      buf = buf.slice(i + 2)
      let type = ''
      let data = ''
      for (const line of block.split('\n')) {
        if (line.startsWith('event: ')) type = line.slice(7)
        else if (line.startsWith('data: ')) data += line.slice(6)
      }
      if (type) onEvent({ type, data: JSON.parse(data || '{}') } as Event)
    }
  }
}

export async function searchWire(word: string, since?: string): Promise<{ words: string[]; routes: Route[] }> {
  const q = new URLSearchParams({ word, ...(since ? { since } : {}) })
  const r = await fetch(`/api/wire?${q}`)
  return r.json()
}

export const fmtBytes = (n: number) =>
  n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)} MB` : n >= 1000 ? `${(n / 1000).toFixed(1)} KB` : `${n} B`

async function failure(r: Response): Promise<string> {
  try { const j = await r.json(); return typeof j.detail === 'string' ? j.detail : `Request failed (${r.status})` } catch { return `Request failed (${r.status})` }
}

export async function addServer(url: string): Promise<Server> {
  const r = await fetch('/api/servers', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url }) })
  if (!r.ok) throw new Error(await failure(r))
  return r.json()
}

export async function removeServer(url: string): Promise<void> {
  const r = await fetch(`/api/servers?${new URLSearchParams({ url })}`, { method: 'DELETE' })
  if (!r.ok) throw new Error(await failure(r))
}
