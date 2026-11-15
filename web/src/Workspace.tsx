import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ask, type Status } from './api'
import { Composer, Landing, TurnView } from './Chat'
import { DeskObjects } from './DeskObjects'
import { Reveal } from './Reveal'
import { Simulation } from './Simulation'
import { toRun } from './pipeline3d/run'
import type { Turn } from './turn'
import { XRay } from './XRay'

const Sim = lazy(() => import('./pipeline3d/Sim'))

export function Workspace({ mode, status, disabled, toggle, homeTick }: { mode: 'chat' | 'demo'; status: Status | null; disabled: Set<string>; toggle: (url: string) => void; homeTick: number }) {
  const demo = mode === 'demo'
  const [turns, setTurns] = useState<Turn[]>([])
  const [compare, setCompare] = useState(demo)
  const [xray, setXray] = useState<number | null>(null)
  const [view, setView] = useState<'ask' | 'sim'>('ask')
  const [home, setHome] = useState(false)
  const nextId = useRef(1)
  const bottom = useRef<HTMLDivElement>(null)
  const busy = turns.some((t) => t.phase === 'working' || t.phase === 'answered')

  useEffect(() => { if (homeTick > 0) { setXray(null); setView('ask'); setHome(true) } }, [homeTick])

  useEffect(() => { window.scrollTo({ top: 0 }) }, [xray, view, home])
  // The libraries a question goes to: the ticked ones that are reachable (all of the ticked ones if none are, so the error says why).
  const ticked = (status?.servers ?? []).filter((s) => !disabled.has(s.url))
  const searched = (ticked.some((s) => s.ok) ? ticked.filter((s) => s.ok) : ticked).map((s) => s.url)
  const examples = ticked.flatMap((s) => (s.examples ?? []).slice(0, 1)).slice(0, 3)
  const nameOf = (url?: string) => status?.servers.find((s) => s.url === url)?.name.replace(/ \(.*\)$/, '')

  const update = (id: number, f: (t: Turn) => Turn) => setTurns((ts) => ts.map((t) => (t.id === id ? f(t) : t)))

  const onAsk = useCallback(async (question: string) => {
    const id = nextId.current++
    setXray(null)
    setHome(false)
    setTurns((ts) => [...ts, { id, question, compare: demo && compare, stages: {}, phase: 'working' }])
    setTimeout(() => bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }), 50)
    try {
      await ask(question, demo && compare, searched, (e) => {
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
  }, [compare, demo, searched.join(',')])

  // The 3D walkthrough at the bottom of the demo chat: always the latest answered question.
  const simTurn = demo ? [...turns].reverse().find((t) => t.result && t.proof) : undefined
  const simKey = simTurn ? `${simTurn.id}` : ''
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const simRun = useMemo(() => (simTurn ? toRun(simTurn, status) : null), [simKey])
  const simBox = useRef<HTMLElement>(null)
  const [simNear, setSimNear] = useState(false)   // mount WebGL only when the section is close to the screen
  const [simIn, setSimIn] = useState(false)       // the composer steps aside while the walkthrough fills the screen
  useEffect(() => {
    const el = simBox.current
    if (!el) { setSimNear(false); setSimIn(false); return }
    const a = new IntersectionObserver(([e]) => { if (e.isIntersecting) setSimNear(true) }, { rootMargin: '900px 0px' })
    const b = new IntersectionObserver(([e]) => setSimIn(e.isIntersecting), { rootMargin: '-45% 0px -45% 0px' })
    a.observe(el); b.observe(el)
    return () => { a.disconnect(); b.disconnect() }
  }, [simKey])
  const xrayTurn = turns.find((t) => t.id === xray)
  const lastTrace = [...turns].reverse().find((t) => t.trace)?.trace
  const composer = (compact: boolean) => (
    <Composer onAsk={onAsk} busy={busy} compare={compare} setCompare={setCompare} status={status}
      number={nextId.current} compact={compact} autoFocus={false} disabled={disabled} onToggle={toggle} plain={!demo} />
  )

  return (
    <div className="relative min-h-[calc(100dvh-64px)]">
      <DeskObjects calm={view === 'sim' || xray !== null || !demo} viewKey={view === 'sim' ? 'sim' : xrayTurn ? `xray-${xrayTurn.id}` : turns.length && !home ? 'chat' : 'landing'}
        version={turns.map((t) => `${t.phase}${t.proof ? 'p' : ''}`).join(',')} />
      {demo && (
        <nav aria-label="Demo views" className="relative z-20 mx-auto flex max-w-[1120px] items-center gap-6 px-5 pb-1">
          <span className="typed text-[13px] text-graphite">Live demo, for presenters</span>
          {([['ask', 'Ask and receipts'], ['sim', 'Population scenario']] as const).map(([k, label]) => (
            <button key={k} onClick={() => { setView(k); if (k === 'ask') setHome(false) }} aria-current={view === k ? 'page' : undefined}
              className={`font-display text-[14px] font-bold underline-offset-[8px] ${view === k ? 'text-ink underline decoration-badger decoration-[3px]' : 'text-graphite hover:text-ink'}`}>
              {label}
            </button>
          ))}
        </nav>
      )}

      <div className={view === 'sim' ? 'hidden' : ''}>
        {xrayTurn ? (
          <XRay turn={xrayTurn} number={xrayTurn.id} status={status} onBack={() => setXray(null)} />
        ) : turns.length === 0 || home ? (
          <Landing status={status} examples={examples} onAsk={onAsk} product={!demo}>{composer(false)}</Landing>
        ) : (
          <>
            <main className={`relative z-[1] mx-auto max-w-[760px] px-5 ${simRun ? 'pb-16' : 'pb-64'}`}>
              {turns.map((t) => <TurnView key={t.id} turn={t} number={t.id} nameOf={nameOf} plain={!demo} onXray={() => setXray(t.id)} onSim={demo ? () => simBox.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }) : undefined} onRetry={t.phase === 'error' && !busy ? () => void onAsk(t.question) : undefined} />)}
              <div ref={bottom} />
            </main>
            {simRun && (
              <section ref={simBox} id="sim3d" aria-label="Watch it run in 3D" className="relative z-[1] scroll-mt-4 pb-32">
                <Reveal className="mx-auto max-w-[760px] px-5 pb-6">
                  <p className="typed text-[13px] text-graphite">Your last question, step by step</p>
                  <h2 className="mt-1 max-w-[16ch] text-[40px] leading-[1.03] font-black tracking-[-0.02em] text-ink sm:text-[60px]">Now watch it run.</h2>
                  <p className="mt-3 max-w-[50ch] text-[17px] leading-7 text-graphite">A 3D model of that one question, built from what really happened. Keep scrolling.</p>
                </Reveal>
                <div aria-hidden className="h-28 bg-gradient-to-b from-transparent to-[#ECEBE7]" />
                {simNear && (
                  <Suspense fallback={<div className="grid h-[60dvh] place-items-center bg-[#ECEBE7] font-display text-ink">Setting up the desk…</div>}>
                    <Sim run={simRun} inline />
                  </Suspense>
                )}
                <div aria-hidden className="h-28 bg-gradient-to-b from-[#ECEBE7] to-transparent" />
              </section>
            )}
            <div data-fixed className={`fixed inset-x-0 bottom-0 z-10 bg-gradient-to-t from-blotter via-blotter/95 to-transparent pt-8 pb-4 transition-opacity duration-500 ${simIn ? 'pointer-events-none opacity-0' : ''}`}>
              <div className="mx-auto max-w-[760px] px-5">{composer(true)}</div>
            </div>
          </>
        )}
      </div>
      {demo && (
        <div className={view === 'sim' ? '' : 'hidden'}>
          <Simulation examples={status?.servers.flatMap((s) => s.examples ?? [])} lastQuestion={turns.length ? turns[turns.length - 1].question : undefined} trace={lastTrace} />
        </div>
      )}
    </div>
  )
}
