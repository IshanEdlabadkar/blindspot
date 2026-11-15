import { useCallback, useEffect, useRef, useState } from 'react'
import { ask, getStatus, type Status } from './api'
import { Composer, EmptyState, TurnView } from './Chat'
import type { Turn } from './turn'
import { XRay } from './XRay'

function Lock() {
  return (
    <svg viewBox="0 0 32 32" className="size-7" aria-hidden>
      <rect width="32" height="32" rx="8" fill="#161B22" />
      <path d="M11 14v-3a5 5 0 0 1 10 0v3" fill="none" stroke="#7FD1C4" strokeWidth="2.4" strokeLinecap="round" />
      <rect x="8" y="14" width="16" height="11" rx="3" fill="#7FD1C4" />
    </svg>
  )
}

function Health({ status }: { status: Status | null }) {
  if (!status) return <span className="text-sm text-dim">Connecting</span>
  const up = status.servers.filter((s) => s.ok).length
  const ok = up === status.servers.length && status.helper && status.model
  const issues = [
    up < status.servers.length && `${status.servers.length - up} offline`,
    !status.helper && 'key helper off', !status.model && 'local model off',
  ].filter(Boolean).join(', ')
  return (
    <span className={`flex items-center gap-2 text-sm ${ok ? 'text-fog' : 'text-amber'}`} title={issues || 'All systems ready'}>
      <span className={`size-2 rounded-full ${ok ? 'bg-seal' : 'bg-amber'}`} />
      {up} {up === 1 ? 'library' : 'libraries'} connected{issues ? `, ${issues}` : ''}
    </span>
  )
}

export default function App() {
  const [status, setStatus] = useState<Status | null>(null)
  const [turns, setTurns] = useState<Turn[]>([])
  const [compare, setCompare] = useState(true)
  const [xray, setXray] = useState<number | null>(null)
  const nextId = useRef(1)
  const bottom = useRef<HTMLDivElement>(null)
  const busy = turns.some((t) => t.phase === 'working' || t.phase === 'answered')

  useEffect(() => {
    let alive = true
    const load = () => getStatus().then((s) => alive && setStatus(s)).catch(() => alive && setStatus(null))
    void load()
    const t = setInterval(load, 20000)
    return () => { alive = false; clearInterval(t) }
  }, [])

  useEffect(() => { window.scrollTo({ top: 0 }) }, [xray])
  const nameOf = (url?: string) => status?.servers.find((s) => s.url === url)?.name.replace(/ \(.*\)$/, '')

  const update = (id: number, f: (t: Turn) => Turn) => setTurns((ts) => ts.map((t) => (t.id === id ? f(t) : t)))

  const onAsk = useCallback(async (question: string) => {
    const id = nextId.current++
    setXray(null)
    setTurns((ts) => [...ts, { id, question, stages: {}, phase: 'working' }])
    setTimeout(() => bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }), 50)
    try {
      await ask(question, compare, (e) => {
        if (e.type === 'start') update(id, (t) => ({ ...t, since: e.data.since }))
        else if (e.type === 'stage') update(id, (t) => ({ ...t, stages: { ...t.stages, [e.data.name]: e.data.seconds } }))
        else if (e.type === 'answer') update(id, (t) => ({ ...t, result: e.data.result, trace: e.data.trace, phase: 'answered' }))
        else if (e.type === 'plain') update(id, (t) => ({ ...t, plain: e.data }))
        else if (e.type === 'proof') update(id, (t) => ({ ...t, proof: e.data }))
        else if (e.type === 'done') update(id, (t) => ({ ...t, phase: 'done' }))
        else if (e.type === 'error') update(id, (t) => ({ ...t, error: e.data, phase: 'error' }))
      })
    } catch (err) {
      update(id, (t) => ({ ...t, phase: 'error', error: { stage: 'connection', message: String(err), fix: 'Start the API: ./web/demo.sh' } }))
    }
  }, [compare])

  const xrayTurn = turns.find((t) => t.id === xray)

  return (
    <div className="min-h-dvh">
      <header className="sticky top-0 z-10 border-b border-seam/70 bg-night/85 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[1080px] items-center justify-between px-5">
          <button onClick={() => setXray(null)} className="flex items-center gap-2.5 text-[16px] font-semibold tracking-tight">
            <Lock /> Blind RAG
          </button>
          <Health status={status} />
        </div>
      </header>

      {xrayTurn ? (
        <XRay turn={xrayTurn} status={status} onBack={() => setXray(null)} />
      ) : turns.length === 0 ? (
        <EmptyState status={status} onAsk={onAsk}>
          <Composer onAsk={onAsk} busy={busy} compare={compare} setCompare={setCompare} autoFocus />
        </EmptyState>
      ) : (
        <main className="mx-auto max-w-[720px] px-5 pt-6 pb-48">
          {turns.map((t) => <TurnView key={t.id} turn={t} nameOf={nameOf} onXray={() => setXray(t.id)} />)}
          <div ref={bottom} />
          <div className="fixed inset-x-0 bottom-0 bg-gradient-to-t from-night via-night/95 to-transparent pt-10 pb-5">
            <div className="mx-auto max-w-[720px] px-5">
              <Composer onAsk={onAsk} busy={busy} compare={compare} setCompare={setCompare} />
            </div>
          </div>
        </main>
      )}
    </div>
  )
}
