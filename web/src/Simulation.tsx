import { useEffect, useMemo, useRef, useState } from 'react'
import type { Trace } from './api'
import { Attacker } from './Attacker'
import { Burrow } from './Burrow'
import { CATS, catOf, classify, clock, hex, makeEvents, makePeople, rng, tally, type Person, type SimEvent } from './sim'
import type { Turn } from './turn'
import { Reveal } from './Reveal'

function Tally({ label, value, strong }: { label: string; value: number | string; strong?: boolean }) {
  return (
    <p className={`flex items-baseline gap-2 ${strong ? 'font-bold text-ink' : ''}`}>
      <span>{label}</span>
      <span aria-hidden className="min-w-4 flex-1 -translate-y-[3px] border-b border-dotted border-graphite/60" />
      <span className="tabular-nums">{value}</span>
    </p>
  )
}
const Cut = () => <p aria-hidden className="my-3 overflow-hidden whitespace-nowrap text-graphite/60">{'- '.repeat(40)}</p>

function Stamp({ read }: { read: boolean }) {
  return (
    <span className={`stamp shrink-0 text-[13px] ${read ? 'text-stamp' : 'text-sealed'}`} style={{ ['--r' as string]: read ? '-5deg' : '4deg', ['--d' as string]: '.2s' }}>
      {read ? 'Read' : 'Not read'}
    </span>
  )
}

function Grid({ people, side, tl, selected, last, onPick }: {
  people: Person[]; side: 'typical' | 'blind'; tl: ReturnType<typeof tally>; selected: number | null; last: number | null; onPick: (id: number) => void
}) {
  return (
    <div className="grid max-w-[340px] grid-cols-10 gap-1" role="group" aria-label={side === 'typical' ? 'Patrons the typical library has a file on' : 'Patrons who connected to the Blindspot library'}>
      {people.map((p) => {
        const seen = tl.profiled.has(p.id), named = tl.ident.has(p.id)
        const look = side === 'typical'
          ? named ? 'border-badger bg-highlighter' : seen ? 'border-badger bg-badger' : 'border-graphite/40'
          : seen ? 'border-sealed bg-sealed/20' : 'border-graphite/40'
        return (
          <button key={p.id} type="button" onClick={() => onPick(p.id)} title={`${p.tag}${p.you ? ' (You)' : ''}`}
            aria-label={`${p.tag}${p.you ? ' (You)' : ''}${seen ? ', has asked' : ', has not asked yet'}`}
            className={`aspect-square border-2 transition-transform duration-150 ${look} ${selected === p.id ? 'outline-2 outline-offset-2 outline-ink' : ''} ${last === p.id ? 'scale-125' : ''} ${p.you ? 'border-dashed' : ''}`} />
        )
      })}
    </div>
  )
}

export function Simulation({ lastQuestion, examples }: { lastQuestion?: string; examples?: string[]; trace?: Trace }) {
  const base = useMemo(() => makePeople(), [])
  const scheduled = useMemo(() => makeEvents(base), [base])
  const [yours, setYours] = useState<{ person: Person; event: SimEvent }[]>([])
  const [done, setDone] = useState(0)
  const [running, setRunning] = useState(false)
  const [speed, setSpeed] = useState(2)
  const [selected, setSelected] = useState<number | null>(null)
  const [dump, setDump] = useState(false)
  const [draft, setDraft] = useState('Can I take FMLA leave for a pregnancy complication?')
  const t = useRef(0)
  const idx = useRef(0)

  useEffect(() => {
    if (!running) return
    const timer = setInterval(() => {
      t.current += 50 * speed
      const before = idx.current
      while (idx.current < scheduled.length && scheduled[idx.current].t <= t.current) idx.current++
      if (idx.current !== before) setDone(idx.current)
      if (idx.current >= scheduled.length) setRunning(false)
    }, 50)
    return () => clearInterval(timer)
  }, [running, speed, scheduled])

  const people = useMemo(() => [...base, ...yours.map((y) => y.person)], [base, yours])
  const events = useMemo(() => [...scheduled.slice(0, done), ...yours.map((y) => y.event)].sort((a, b) => a.t - b.t || a.n - b.n), [scheduled, done, yours])
  const tl = useMemo(() => tally(events), [events])
  const lastPid = events.length ? events[events.length - 1].pid : null
  const finished = done >= scheduled.length

  // Sealed bytes for each request line: fixed per event so they don't flicker between renders.
  const sealed = (e: SimEvent, which: 0 | 1) => hex(rng(e.n * 2 + which + 7), 26)

  const run = () => {
    if (finished) reset()
    setRunning((r) => !r)
  }
  const reset = () => {
    t.current = 0; idx.current = 0
    setDone(0); setYours([]); setSelected(null); setRunning(false); setDump(false)
  }
  const addYou = () => {
    const text = draft.trim()
    if (!text) return
    const n = yours.length
    const id = 100 + n
    const person: Person = { id, tag: n ? `YOU ${n + 1}` : 'YOU', name: 'You', age: null, ip: '203.0.113.250', cookie: `c${hex(rng(900 + n), 7)}`, queries: [classify(text)], you: true }
    const event: SimEvent = { n: 1000 + n, t: t.current, pid: id, q: person.queries[0], k: 0 }
    setYours((y) => [...y, { person, event }])
    setSelected(id)
  }

  const sel = selected === null ? null : people.find((p) => p.id === selected) ?? null
  const selEvents = sel ? events.filter((e) => e.pid === sel.id) : []
  const segs = [...tl.bySeg.entries()].map(([c, s]) => [CATS[c].segment, s.size] as const).sort((a, b) => b[1] - a[1])
  const typicalLog = events.slice(-12)
  const blindLog = events.slice(-6)
  const youQuestion = yours.length ? yours[yours.length - 1].person.queries[0].text : ''
  const attackerTurn: Turn = { id: 9000 + yours.length, question: youQuestion, stages: {}, phase: 'done' }

  return (
    <main className="relative z-[1] mx-auto max-w-[1120px] px-5 pt-6 pb-24">
      <div className="grid gap-y-8 md:grid-cols-[1fr_480px] md:gap-x-14">
        <div className="md:self-end">
          <h1 className="max-w-[14ch] text-[40px] leading-[1.05] font-black tracking-[-0.02em] text-ink sm:text-[52px]">A hundred call slips.</h1>
          <p className="mt-5 max-w-[50ch] text-[17px] leading-7 text-graphite">
            The same hundred people hand in the same sensitive questions to two libraries. The one on the left copies every slip into its ledger.
            The one on the right only ever receives sealed envelopes. Press the button and compare the ledgers.
          </p>
          <div className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-3">
            <button type="button" onClick={run}
              className="press h-11 rounded-[2px] bg-badger px-5 font-display text-[15px] font-bold text-white hover:bg-stamp">
              {running ? 'Pause' : finished ? 'Run it again' : done > 0 ? 'Keep going' : 'Hand in all 100 slips'}
            </button>
            <button type="button" onClick={reset} className="text-[15px] text-ink underline decoration-graphite/50 underline-offset-4 hover:decoration-badger">Start over</button>
            <span className="flex items-center gap-3 text-[15px] text-graphite" role="group" aria-label="Speed">
              Speed
              {[1, 2, 4].map((s) => (
                <button key={s} type="button" onClick={() => setSpeed(s)} aria-pressed={speed === s}
                  className={`typed px-0.5 text-[15px] ${speed === s ? 'font-bold text-ink underline decoration-badger decoration-2 underline-offset-4' : 'text-graphite hover:text-ink'}`}>{s}x</button>
              ))}
            </span>
          </div>
        </div>

        <div className="relative md:self-center">
          <form onSubmit={(e) => { e.preventDefault(); addYou() }} className="slip px-5 pt-6 pb-5 sm:px-6 md:rotate-[1deg]">
            <div className="flex items-baseline justify-between font-display text-[15px] font-black text-ink">
              <span>Add your own slip</span><span className="typed text-[15px] font-normal text-graphite">patron {yours.length ? `YOU ${yours.length + 1}` : 'YOU'}</span>
            </div>
            <label htmlFor="own" className="typed mt-2 block text-[14px] leading-6 text-graphite">Your question, joining the hundred</label>
            <textarea id="own" rows={3} value={draft} onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); addYou() } }}
              className="typed block w-full resize-none bg-[repeating-linear-gradient(transparent_0_27px,var(--color-rule)_27px_28px)] text-[17px] text-ink placeholder:text-graphite/70 focus:outline-none"
              placeholder="Write it the way you'd say it" />
            <div className="mt-3 flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
              {lastQuestion
                ? <button type="button" onClick={() => setDraft(lastQuestion)} className="text-left text-[14px] text-ink underline decoration-graphite/50 underline-offset-4 hover:decoration-badger">Use my last real question</button>
                : <span />}
              <button type="submit" className="press h-10 shrink-0 rounded-[2px] bg-ink px-4 font-display text-sm font-bold text-card">Hand it in as You</button>
            </div>
          </form>
          <div className="absolute -bottom-[60px] -right-2 hidden md:block"><Burrow size={72} mood="idle" /></div>
        </div>
      </div>

      <div className="mt-12 grid items-start gap-8 md:grid-cols-2">
        <Reveal as="section" className="receipt typed min-w-0 px-6 pt-6 pb-10 text-[14px] leading-6 text-ink" label="Typical library ledger">
          <div className="flex items-start justify-between gap-3">
            <div><h2 className="text-[19px] leading-6 font-black">A typical library</h2><p className="text-graphite">Ledger of what it wrote down</p></div>
            <Stamp read />
          </div>
          <Cut />
          <Tally label="Questions written down" value={tl.questions} strong />
          <Tally label="Patrons with a file" value={tl.profiled.size} />
          <Tally label="Sensitive labels filed" value={tl.labels} />
          <Tally label="Named by their own words" value={tl.ident.size} />
          <Cut />
          <Grid people={people} side="typical" tl={tl} selected={selected} last={running ? lastPid : null} onPick={setSelected} />
          <p className="mt-2 text-[13px] text-graphite">
            <span aria-hidden className="mr-1 inline-block size-2.5 border border-badger bg-badger align-middle" /> has a file
            <span aria-hidden className="mr-1 ml-4 inline-block size-2.5 border border-badger bg-highlighter align-middle" /> named from the question alone
          </p>
          <Cut />
          <p className="font-bold">Labels filed</p>
          {segs.length === 0 && <p className="text-graphite">None yet.</p>}
          {segs.slice(0, 7).map(([name, n]) => <Tally key={name} label={name} value={n} />)}
          {segs.length > 7 && <p className="text-graphite">and {segs.length - 7} more</p>}
          <Cut />
          <p className="font-bold">Latest lines in the ledger</p>
          <div className="mt-1 h-[288px] overflow-hidden" aria-live="off">
            {typicalLog.length === 0 && <p className="text-graphite">Empty.</p>}
            {typicalLog.map((e) => {
              const p = people.find((x) => x.id === e.pid)!
              return (
                <p key={e.n} className="h-6 truncate">
                  <span className="text-graphite">{clock(e.t)} {p.ip} </span>
                  <mark className="mark bg-transparent">“{e.q.text}”</mark>
                </p>
              )
            })}
          </div>
        </Reveal>

        <Reveal as="section" className="receipt typed min-w-0 px-6 pt-6 pb-10 text-[14px] leading-6 text-ink" label="Blindspot library ledger" delay={0.12}>
          <div className="flex items-start justify-between gap-3">
            <div><h2 className="text-[19px] leading-6 font-black">The Blindspot library</h2><p className="text-graphite">Ledger of what it wrote down</p></div>
            <Stamp read={false} />
          </div>
          <Cut />
          <Tally label="Questions written down" value={0} strong />
          <Tally label="Patrons with a file" value={0} />
          <Tally label="Sensitive labels filed" value={0} />
          <Tally label="Requests logged (time, address)" value={tl.requests} />
          <Cut />
          <Grid people={people} side="blind" tl={tl} selected={selected} last={running ? lastPid : null} onPick={setSelected} />
          <p className="mt-2 text-[13px] text-graphite">
            <span aria-hidden className="mr-1 inline-block size-2.5 border border-sealed bg-sealed/20 align-middle" /> connected, and nothing else is known
          </p>
          <Cut />
          <p className="font-bold">Labels filed</p>
          <p className="text-graphite">None can be made. It never saw a question.</p>
          <Cut />
          <p className="font-bold">Latest lines in the ledger</p>
          <div className="mt-1 h-[288px] overflow-hidden" aria-live="off">
            {blindLog.length === 0 && <p className="text-graphite">Empty.</p>}
            {blindLog.map((e) => {
              const p = people.find((x) => x.id === e.pid)!
              return (
                <div key={e.n} className="h-12">
                  <p className="truncate"><span className="text-graphite">{clock(e.t)} {p.ip} </span>score</p>
                  <p className="hex truncate text-sealed">{sealed(e, 0)}{sealed(e, 1)}</p>
                </div>
              )
            })}
          </div>
        </Reveal>
      </div>

      <Reveal as="section" className="mt-14" label="One patron's card">
        <h2 className="text-[26px] leading-8 font-black tracking-[-0.01em] text-ink">Open one patron's card</h2>
        <p className="mt-1 max-w-[60ch] text-[16px] leading-6 text-graphite">Click any square above to see what each library holds about that person, and which ads would follow them.</p>
        {!sel || selEvents.length === 0 ? (
          <div className="slip mt-6 max-w-[520px] px-6 pt-6 pb-5 text-[16px] leading-6 text-graphite">
            {sel ? `${sel.tag} hasn't handed in a slip yet. Press the button, or pick someone who has.` : 'No card open yet.'}
          </div>
        ) : (
          <div className="mt-8 grid items-start gap-8 md:grid-cols-2">
            {(() => {
              const cats = [...new Set(selEvents.map((e) => catOf(e.q)))]
              const sensitive = cats.filter((c) => c.segment !== 'General browser')
              const ads = [...new Set(cats.flatMap((c) => c.ads))]
              const named = selEvents.some((e) => e.q.ident)
              const who = `${sel.tag}${sel.age ? `, ${sel.name}, ${sel.age}` : ''}`
              return (
                <>
                  <article className="catalog typed px-6 pt-[52px] pb-14 text-[15px] sm:px-8">
                    <div className="absolute inset-x-6 top-3 flex items-baseline justify-between gap-4 sm:inset-x-8">
                      <span className="truncate text-[15px] font-bold text-ink">{who}</span>
                      <span className="shrink-0 text-[14px] text-graphite">typical library</span>
                    </div>
                    <p><span className="text-graphite">asked </span>{selEvents.map((e) => <span key={e.n} className="block font-bold">“{e.q.text}”</span>)}</p>
                    <p><span className="text-graphite">tracking id </span>{sel.cookie}, on every visit</p>
                    <p><span className="text-graphite">filed under </span>{cats.map((c) => c.segment).join('; ')}</p>
                    <p><span className="text-graphite">guessed </span>{cats.map((c) => c.guess).join('; ')}</p>
                    <p><span className="text-graphite">ads next </span><span className="text-badger">{ads.join('; ')}</span></p>
                    <p><span className="text-graphite">named? </span>{named ? <mark className="mark bg-transparent font-bold">yes, from the question alone</mark> : 'linkable by address and tracking id'}</p>
                    <p><span className="text-graphite">could be </span>sold, breached or subpoenaed</p>
                    <span className="stamp absolute right-6 bottom-9 text-[14px] text-stamp" style={{ ['--r' as string]: '-7deg', ['--d' as string]: '.3s' }}>Kept on file</span>
                  </article>
                  <article className="catalog typed px-6 pt-[52px] pb-14 text-[15px] sm:px-8">
                    <div className="absolute inset-x-6 top-3 flex items-baseline justify-between gap-4 sm:inset-x-8">
                      <span className="truncate text-[15px] font-bold text-ink">{who}</span>
                      <span className="shrink-0 text-[14px] text-graphite">Blindspot library</span>
                    </div>
                    <p><span className="text-graphite">asked </span>nothing it can read</p>
                    <p><span className="text-graphite">tracking id </span>none, each request stands alone</p>
                    <p><span className="text-graphite">filed under </span>no label can be made{sensitive.length ? `, where the other file has ${sensitive.length}` : ''}</p>
                    <p><span className="text-graphite">guessed </span>nothing</p>
                    <p><span className="text-graphite">ads next </span>nothing aimed from this library's data</p>
                    <p><span className="text-graphite">still on file </span>{selEvents.length * 2} request lines: time and address {sel.ip}</p>
                    <p><span className="text-graphite">could be </span>breached or subpoenaed, and hands over only that</p>
                    <span className="stamp absolute right-6 bottom-9 text-[14px] text-sealed" style={{ ['--r' as string]: '5deg', ['--d' as string]: '.3s' }}>Not read</span>
                  </article>
                </>
              )
            })()}
          </div>
        )}
      </Reveal>

      <Reveal as="section" className="mt-14" label="Hand over the ledgers">
        <h2 className="text-[26px] leading-8 font-black tracking-[-0.01em] text-ink">Now hand over the ledgers</h2>
        <p className="mt-1 max-w-[60ch] text-[16px] leading-6 text-graphite">A breach, a rogue employee or a court order gets someone the same files. Here is what each pile gives them.</p>
        <button type="button" onClick={() => setDump((d) => !d)} aria-expanded={dump}
          className="press mt-4 h-11 rounded-[2px] bg-ink px-5 font-display text-[15px] font-bold text-card">
          {dump ? 'Put the ledgers back' : 'Subpoena both ledgers'}
        </button>
        {dump && (
          <div className="mt-6 grid items-start gap-8 md:grid-cols-2">
            <div className="bg-card shadow-paper">
              <p className="flex items-center justify-between gap-3 border-b-2 border-badger px-5 py-3 font-display text-[15px] font-black">Typical library <Stamp read /></p>
              <div className="typed max-h-[340px] overflow-auto px-5 py-3 text-[13px] leading-5">
                {events.length === 0 && <p className="text-graphite">Nothing yet. Run the simulation first.</p>}
                {events.map((e) => {
                  const p = people.find((x) => x.id === e.pid)!
                  return <p key={e.n} className="whitespace-nowrap"><span className="text-graphite">{clock(e.t)} {p.tag} {p.ip} {p.cookie} </span><mark className="bg-highlighter/70">“{e.q.text}”</mark><span className="text-graphite"> [{catOf(e.q).segment}]</span></p>
                })}
              </div>
              <p className="typed border-t border-dashed border-graphite/40 px-5 py-3 text-[14px] leading-5 font-bold text-stamp">
                {events.length} readable questions, {tl.profiled.size} patrons, {tl.labels} sensitive labels, {tl.ident.size} named from their words alone.
              </p>
            </div>
            <div className="bg-card shadow-paper">
              <p className="flex items-center justify-between gap-3 border-b-2 border-sealed px-5 py-3 font-display text-[15px] font-black">Blindspot library <Stamp read={false} /></p>
              <div className="typed max-h-[340px] overflow-auto px-5 py-3 text-[13px] leading-5">
                {events.length === 0 && <p className="text-graphite">Nothing yet. Run the simulation first.</p>}
                {events.map((e) => {
                  const p = people.find((x) => x.id === e.pid)!
                  return <p key={e.n} className="whitespace-nowrap"><span className="text-graphite">{clock(e.t)} {p.ip} score </span><span className="hex text-sealed">{sealed(e, 0)}{sealed(e, 1).slice(0, 12)}</span></p>
                })}
              </div>
              <p className="typed border-t border-dashed border-graphite/40 px-5 py-3 text-[14px] leading-5 font-bold text-sealed">
                0 readable questions. {tl.requests} request lines. Which of five candidate questions was asked? No way to tell.
              </p>
            </div>
          </div>
        )}
        {dump && yours.length > 0 && (
          <div className="mt-8 max-w-[560px]"><Attacker turn={attackerTurn} pool={examples} /></div>
        )}
      </Reveal>

      <p className="mt-14 max-w-[70ch] text-[13px] leading-5 text-graphite">
        The hundred patrons, their questions, addresses and sealed requests are made up. Labels and ads come from a simple word-matching rule, a stand-in for real ad tech.
        The Blindspot library still sees that a request happened, when, from which address. It cannot see what was asked, how passages scored or which were fetched.
      </p>
    </main>
  )
}
