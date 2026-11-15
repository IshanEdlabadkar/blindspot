import { useCallback, useEffect, useRef, useState } from 'react'
import { ask, getStatus, type Status } from './api'
import { Burrow } from './Burrow'
import { Composer, Landing, TurnView } from './Chat'
import { Libraries } from './Libraries'
import { DeskObjects } from './DeskObjects'
import { Simulation } from './Simulation'
import type { Turn } from './turn'
import { XRay } from './XRay'

function Health({ status }: { status: Status | null }) {
  if (!status) return <span className="text-sm text-graphite">Connecting</span>
  const up = status.servers.filter((s) => s.ok).length
  const ok = up === status.servers.length && status.helper && status.model
  const issues = [
    up < status.servers.length && `${status.servers.length - up} offline`,
    !status.helper && 'key helper off', !status.model && 'local model off',
  ].filter(Boolean).join(', ')
  return (
    <span className={`text-sm ${ok ? 'text-graphite' : 'font-medium text-stamp'}`} title={issues || 'All systems ready'}>
      <span className="hidden sm:inline">{up} of {status.servers.length} libraries open{issues ? `, ${issues}` : ''}</span>
      <span className="sm:hidden">{issues ? `${up}/${status.servers.length} open, check` : ''}</span>
    </span>
  )
}

export default function App() {
  const [status, setStatus] = useState<Status | null>(null)
  const [turns, setTurns] = useState<Turn[]>([])
  const [compare, setCompare] = useState(true)
  const [xray, setXray] = useState<number | null>(null)
  const [view, setView] = useState<'ask' | 'sim'>('ask')
  const [disabled, setDisabledRaw] = useState<Set<string>>(() => {
    try { return new Set<string>(JSON.parse(localStorage.getItem('blindspot.disabled') ?? '[]')) } catch { return new Set<string>() }
  })
  const setDisabled = (s: Set<string>) => {
    setDisabledRaw(s)
    try { localStorage.setItem('blindspot.disabled', JSON.stringify([...s])) } catch { /* private mode */ }
  }
  const refresh = useCallback(() => { void getStatus().then(setStatus).catch(() => setStatus(null)) }, [])
  const nextId = useRef(1)
  const bottom = useRef<HTMLDivElement>(null)
  const busy = turns.some((t) => t.phase === 'working' || t.phase === 'answered')

  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 5000)
    return () => clearInterval(t)
  }, [refresh])

  useEffect(() => { window.scrollTo({ top: 0 }) }, [xray, view])
  // The libraries a question goes to: the ticked ones that are reachable (all of the ticked ones if none are, so the error says why).
  const ticked = (status?.servers ?? []).filter((s) => !disabled.has(s.url))
  const searched = (ticked.some((s) => s.ok) ? ticked.filter((s) => s.ok) : ticked).map((s) => s.url)
  const examples = ticked.flatMap((s) => (s.examples ?? []).slice(0, 1)).slice(0, 3)
  const nameOf = (url?: string) => status?.servers.find((s) => s.url === url)?.name.replace(/ \(.*\)$/, '')

  const update = (id: number, f: (t: Turn) => Turn) => setTurns((ts) => ts.map((t) => (t.id === id ? f(t) : t)))

  const onAsk = useCallback(async (question: string) => {
    const id = nextId.current++
    setXray(null)
    setTurns((ts) => [...ts, { id, question, compare, stages: {}, phase: 'working' }])
    setTimeout(() => bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }), 50)
    try {
      await ask(question, compare, searched, (e) => {
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
  }, [compare, searched.join(',')])

  const xrayTurn = turns.find((t) => t.id === xray)
  const lastTrace = [...turns].reverse().find((t) => t.trace)?.trace
  const composer = (compact: boolean) => (
    <Composer onAsk={onAsk} busy={busy} compare={compare} setCompare={setCompare} status={status}
      number={nextId.current} compact={compact} autoFocus={false} disabled={disabled} />
  )

  return (
    <div className="desk relative min-h-dvh">
      <DeskObjects viewKey={view === 'sim' ? 'sim' : xrayTurn ? `xray-${xrayTurn.id}` : turns.length ? 'chat' : 'landing'}
        version={turns.map((t) => `${t.phase}${t.proof ? 'p' : ''}`).join(',')} />
      <header className="relative z-[1] mx-auto flex h-16 max-w-[1120px] items-center justify-between gap-3 px-4 whitespace-nowrap sm:px-5">
        <button onClick={() => { setXray(null); setView('ask') }} className="flex items-center gap-2 font-display text-[20px] font-black tracking-[-0.02em] text-ink">
          <Burrow size={32} mood="peek" /> <span className="hidden sm:inline">Blindspot</span>
        </button>
        <nav aria-label="Views" className="flex items-center gap-4 sm:gap-7">
          {([['ask', 'Ask'], ['sim', '100 people']] as const).map(([k, label]) => (
            <button key={k} onClick={() => setView(k)} aria-current={view === k ? 'page' : undefined}
              className={`font-display text-[15px] font-bold underline-offset-[10px] ${view === k ? 'text-ink underline decoration-badger decoration-[3px]' : 'text-graphite hover:text-ink'}`}>
              {label}
            </button>
          ))}
        </nav>
        <div className="flex items-center gap-3 sm:gap-5">
          <Libraries status={status} disabled={disabled} setDisabled={setDisabled} refresh={refresh} />
          <a href="http://localhost:8501" target="_blank" rel="noreferrer" title="Measured results, who sees what, and more"
            className="hidden text-sm text-ink underline decoration-graphite/50 underline-offset-4 hover:decoration-badger sm:inline">
            More evidence
          </a>
          <Health status={status} />
        </div>
      </header>

      <div className={view === 'sim' ? 'hidden' : ''}>
        {xrayTurn ? (
          <XRay turn={xrayTurn} number={xrayTurn.id} status={status} onBack={() => setXray(null)} />
        ) : turns.length === 0 ? (
          <Landing status={status} examples={examples} onAsk={onAsk}>{composer(false)}</Landing>
        ) : (
          <>
            <main className="relative z-[1] mx-auto max-w-[760px] px-5 pb-64">
              {turns.map((t) => <TurnView key={t.id} turn={t} number={t.id} nameOf={nameOf} onXray={() => setXray(t.id)} onRetry={t.phase === 'error' && !busy ? () => void onAsk(t.question) : undefined} />)}
              <div ref={bottom} />
            </main>
            <div data-fixed className="fixed inset-x-0 bottom-0 z-10 bg-gradient-to-t from-blotter via-blotter/95 to-transparent pt-8 pb-4">
              <div className="mx-auto max-w-[760px] px-5">{composer(true)}</div>
            </div>
          </>
        )}
      </div>
      <div className={view === 'sim' ? '' : 'hidden'}>
        <Simulation examples={status?.servers.flatMap((s) => s.examples ?? [])} lastQuestion={turns.length ? turns[turns.length - 1].question : undefined} trace={lastTrace} />
      </div>
    </div>
  )
}
