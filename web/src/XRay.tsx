import { useReducedMotion } from 'motion/react'
import { Fragment, useEffect, useMemo, useState } from 'react'
import { fmtBytes, searchWire, type Route, type ServerTrace, type Status } from './api'
import { Burrow } from './Burrow'
import { short, slipNo } from './Chat'
import { libraryName, type Turn } from './turn'

const HEX = '0123456789abcdef'

/** The question's own letters turn into the real ciphertext that was sent. */
function Scramble({ from, to, run }: { from: string; to: string; run: boolean }) {
  const reduce = useReducedMotion()
  const target = useMemo(() => {
    const t = to || '00'
    return Array.from({ length: from.length }, (_, i) => (from[i] === ' ' ? ' ' : t[i % t.length])).join('')
  }, [from, to])
  const [p, setP] = useState(reduce ? 1 : 0)
  useEffect(() => {
    if (!run || reduce) { setP(run ? 1 : 0); return }
    const start = performance.now()
    let raf = 0
    const tick = (now: number) => {
      const x = Math.min(1, (now - start) / 1600)
      setP(x)
      if (x < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [run, reduce])
  const out = Array.from(from, (ch, i) => {
    if (ch === ' ') return ' '
    const edge = i / from.length
    if (edge < p - 0.12) return target[i]
    if (edge < p) return HEX[Math.floor(Math.random() * 16)]
    return ch
  }).join('')
  return <span aria-label="Your question, as it was sent">{out}</span>
}

const Cut = () => <p aria-hidden className="my-4 overflow-hidden whitespace-nowrap text-graphite/60">{'- '.repeat(40)}</p>

function Line({ left, right, strong }: { left: React.ReactNode; right?: React.ReactNode; strong?: boolean }) {
  return (
    <p className={`flex justify-between gap-4 ${strong ? 'font-bold text-ink' : ''}`}>
      <span className="min-w-0">{left}</span>{right !== undefined && <span className="shrink-0 text-right">{right}</span>}
    </p>
  )
}

function Highlight({ text, words }: { text: string; words: string[] }) {
  if (!words.length) return <>{text}</>
  const re = new RegExp(`(${words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'gi')
  let k = 0
  return <>{text.split(re).map((part, i) => i % 2
    ? <mark key={i} className="mark bg-transparent" style={{ ['--d' as string]: `${0.5 + 0.2 * k++}s` }}>{part}</mark>
    : <Fragment key={i}>{part}</Fragment>)}</>
}

function Stamp({ read, i }: { read: boolean; i: number }) {
  return (
    <span className={`stamp shrink-0 text-[13px] ${read ? 'text-stamp' : 'text-sealed'}`}
      style={{ ['--r' as string]: `${i % 2 ? 4 : -5}deg`, ['--d' as string]: `${0.3 + i * 0.15}s` }}>
      {read ? 'Read' : 'Not read'}
    </span>
  )
}

/** One receipt section: a heading and its rows, ending in a tear line. Both receipts use the same seven, so they line up. */
function Sec({ title, children, last }: { title?: string; children: React.ReactNode; last?: boolean }) {
  return (
    <section className="min-w-0">
      {title && <p className="font-bold">{title}</p>}
      {children}
      {!last && <Cut />}
    </section>
  )
}

function SecretWord({ since }: { since?: string }) {
  const [word, setWord] = useState('')
  const [res, setRes] = useState<{ words: string[]; routes: Route[] } | null>(null)
  const go = async () => { if (word.trim()) setRes(await searchWire(word.trim(), since)) }
  return (
    <div>
      <label htmlFor="secret" className="font-bold text-ink">Search this traffic for any word</label>
      <p className="text-graphite">A name, or something from your question. Four letters or more.</p>
      <form className="mt-2 flex gap-2" onSubmit={(e) => { e.preventDefault(); void go() }}>
        <input id="secret" value={word} onChange={(e) => { setWord(e.target.value); setRes(null) }}
          className="typed h-10 min-w-0 flex-1 border-b-2 border-ink bg-transparent px-1 text-ink placeholder:text-graphite/70 focus:outline-none"
          placeholder="type a word" />
        <button className="press h-10 rounded-[2px] bg-ink px-4 font-display text-sm font-bold text-card disabled:opacity-50" disabled={!word.trim()}>Search</button>
      </form>
      {res && (
        <div className="mt-3">
          {!res.words.length && <p className="text-graphite">Use a word of four letters or more.</p>}
          {res.words.length > 0 && res.routes.map((r) => (
            <Line key={r.route} left={libraryName(r.route)} right={<span className={r.found.length ? 'font-bold text-stamp' : 'text-sealed'}>{r.found.length ? 'FOUND' : 'not found'}</span>} />
          ))}
        </div>
      )}
    </div>
  )
}

export function XRay({ turn, number, status, onBack }: { turn: Turn; number: number; status: Status | null; onBack: () => void }) {
  const tr = turn.trace
  const servers: ServerTrace[] = tr?.servers ?? (tr ? [{ server: tr.server ?? '', corpus_version: '', num_chunks: tr.num_chunks ?? 0,
    requests: tr.requests ?? [], timings: tr.timings ?? {}, fetched: 10, used: turn.result?.citations.length ?? 0,
    ciphertext_sample: tr.ciphertext_sample }] : [])
  const nameOf = (url: string) => short(status?.servers.find((s) => s.url === url)?.name ?? url)
  const cipher = servers.find((s) => s.ciphertext_sample)?.ciphertext_sample ?? tr?.ciphertext_sample ?? turn.proof?.routes.find((r) => r.sample_hex)?.sample_hex ?? ''
  const s = turn.stages
  const words = turn.proof?.words ?? []
  const routes = [...(turn.proof?.routes ?? [])].sort((a, b) => Number(a.route === 'plain') - Number(b.route === 'plain'))
  const blind = routes.filter((r) => r.route !== 'plain')
  const upOf = (x: ServerTrace) => x.requests.reduce((n, r) => n + r.request_bytes, 0)
  const when = turn.since && !Number.isNaN(Date.parse(turn.since)) ? new Date(turn.since) : new Date()
  const t = (v?: number, d = 2) => (v === undefined ? '...' : `${v.toFixed(d)} s`)

  const plainRoute = routes.find((r) => r.route === 'plain')
  const entry = turn.plain?.entry
  const compared = Boolean(turn.compare || entry || plainRoute)
  const stamp = (d: Date) => `${d.toLocaleDateString()} ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
  const sealedTotal = blind.reduce((n, r) => n + r.bytes, 0) || servers.reduce((n, x) => n + upOf(x), 0)
  const waiting = <p className="text-graphite">Searching the recording...</p>
  const off = <p>Recording is off. Start the demo with <span className="font-bold">./web/demo.sh</span> to print this part.</p>
  const proofPart = (body: React.ReactNode) => !turn.proof ? waiting : !turn.proof.recording ? off : body
  const paper = 'receipt typed w-full px-6 pt-7 pb-12 text-[15px] leading-6 text-ink sm:px-8 md:row-span-7 md:grid md:grid-rows-subgrid'

  return (
    <main className="relative z-[1] mx-auto max-w-[1120px] px-5 pt-6 pb-24">
      <div className="flex items-end justify-between gap-6">
        <div>
          <button onClick={onBack} className="text-[15px] text-ink underline decoration-graphite/50 underline-offset-4 hover:decoration-badger">
            Back to the conversation
          </button>
          <h2 className="mt-6 text-[36px] leading-[1.05] font-black tracking-[-0.02em] text-ink sm:text-[48px]">What left this laptop</h2>
          <p className="mt-4 max-w-[62ch] text-[17px] leading-7 text-graphite">
            A recorder sat between this app and everything it talks to, and kept each byte that went out.
            {compared ? ' The same question went two ways. Read the receipts across: each row is the same step.' : ' This receipt is what it saw.'}
          </p>
        </div>
        <div className="hidden shrink-0 md:block"><Burrow size={88} mood="idle" /></div>
      </div>

      <div className="mt-10 flex flex-col gap-8 md:grid md:grid-cols-2 md:grid-rows-[repeat(7,auto)] md:gap-x-10 md:gap-y-0 lg:gap-x-14">
        <div className={paper}>
          <Sec>
            <p className="text-center font-display text-[20px] font-black">Blind RAG</p>
            <p className="text-center text-graphite">Sealed, receipt {slipNo(number)}</p>
            <p className="text-center text-graphite">{stamp(when)}</p>
          </Sec>
          <Sec title="Your question">
            <p>{turn.question}</p>
            <p className="mt-1 text-graphite">Read only on this laptop.</p>
          </Sec>
          <Sec title="As it was sent">
            <p className="hex text-[14px] text-sealed"><Scramble from={turn.question} to={cipher} run={Boolean(cipher)} /></p>
          </Sec>
          <Sec title={`Sent to ${servers.length} ${servers.length === 1 ? 'library' : 'libraries'}`}>
            {servers.map((x) => (
              <div key={x.server}>
                <Line left={nameOf(x.server)} right={`${fmtBytes(upOf(x))} sealed`} />
                <p className="text-graphite">{`  scored ${x.num_chunks.toLocaleString()}, sent back ${x.fetched}`}</p>
              </div>
            ))}
          </Sec>
          <Sec title="What they wrote down">
            <p>Nothing they can read. Each library saw sealed bytes, scored every passage without knowing which mattered, and sent back the same number every time.</p>
          </Sec>
          <Sec title="Your words found">
            {proofPart(<>
              <p className="text-graphite">{words.join(', ')}</p>
              <div className="mt-2 space-y-3">
                {blind.map((r, i) => (
                  <div key={r.route} className="flex items-center justify-between gap-3">
                    <span className="min-w-0">{libraryName(r.route)}</span>
                    <span className="flex items-center gap-3"><Stamp read={r.found.length > 0} i={i} /><span className="font-bold">{r.found.length} of {r.words}</span></span>
                  </div>
                ))}
              </div>
              {blind.length > 0 && blind.every((r) => r.found.length === 0) && (
                <p className="mt-2 text-graphite">Odds of one appearing by luck in that much random data: about {Math.max(...blind.map((r) => r.chance_by_luck)).toExponential(0)}.</p>
              )}
            </>)}
          </Sec>
          <Sec last>
            <Line strong left="Total sent" right={`${fmtBytes(sealedTotal)} sealed`} />
            <Line left="Read on this laptop" right={t(s.embedding)} />
            <Line left="Sealed" right={t(s.encrypting)} />
            <Line left="Searched without reading" right={t(s.scoring)} />
            <Line left="Answer written here" right={t(s.answering, 1)} />
            <p className="mt-4 text-center text-graphite">Thank you for asking privately.</p>
          </Sec>
        </div>

        {compared ? (
          <div className={paper}>
            <Sec>
              <p className="text-center font-display text-[20px] font-black">A normal AI service</p>
              <p className="text-center text-graphite">Unsealed copy, receipt {slipNo(number)}</p>
              <p className="text-center text-graphite">{entry && !Number.isNaN(Date.parse(entry.time)) ? stamp(new Date(entry.time)) : stamp(when)}</p>
            </Sec>
            <Sec title="Your question">
              <p>{turn.question}</p>
              <p className="mt-1 text-stamp">Read in full by the service.</p>
            </Sec>
            <Sec title="As it was sent">
              <p className="text-[14px]"><Highlight text={turn.question} words={words} /></p>
            </Sec>
            <Sec title="Sent to 1 service">
              <Line left="A normal AI service" right={plainRoute ? `${fmtBytes(plainRoute.bytes)} plain` : '...'} />
              <p className="text-graphite">  as readable text</p>
            </Sec>
            <Sec title="What it wrote down">
              {turn.plain?.error && <p>It couldn't be reached this time: <span className="text-graphite">{turn.plain.error}</span></p>}
              {!turn.plain && <p className="text-graphite">Waiting for its log...</p>}
              {entry && (
                <dl className="grid grid-cols-[4.5em_1fr] text-[14px]">
                  <dt className="text-graphite">time</dt><dd>{!Number.isNaN(Date.parse(entry.time)) ? new Date(entry.time).toLocaleTimeString() : entry.time}</dd>
                  <dt className="text-graphite">from</dt><dd>{entry.client}</dd>
                  <dt className="text-graphite">asked</dt><dd className="font-bold">“<Highlight text={entry.question} words={words} />”</dd>
                  {entry.returned?.length > 0 && <><dt className="text-graphite">sent</dt><dd>{[...new Set(entry.returned.map((x) => x.title))].join('; ')}</dd></>}
                </dl>
              )}
            </Sec>
            <Sec title="Your words found">
              {proofPart(plainRoute ? <>
                <p className="text-graphite">{words.join(', ')}</p>
                <div className="mt-2 flex items-center justify-between gap-3">
                  <span className="min-w-0">A normal AI service</span>
                  <span className="flex items-center gap-3"><Stamp read={plainRoute.found.length > 0} i={1} /><span className="font-bold">{plainRoute.found.length} of {plainRoute.words}</span></span>
                </div>
                {plainRoute.found.length > 0 && <p className="mt-2 text-graphite">Every one of them, in the clear.</p>}
              </> : <p className="text-graphite">Its traffic wasn't recorded.</p>)}
            </Sec>
            <Sec last>
              <Line strong left="Total sent" right={plainRoute ? `${fmtBytes(plainRoute.bytes)} plain` : '...'} />
              <p className="mt-1 text-graphite">Smaller, because nothing was sealed. It is also the only one that can read it, and it kept it.</p>
            </Sec>
          </div>
        ) : (
          <div className="slip self-start px-6 pt-6 pb-5 text-[15px] leading-6 md:row-span-7">
            <p className="font-display font-black text-ink">No second receipt for this question</p>
            <p className="mt-2 text-ink">To print one, tick “Also send an unsealed copy to a normal AI service” on the call slip before you hand it in.
              The same question then goes to a normal service too, and its receipt prints here, row for row.</p>
          </div>
        )}
      </div>

      <div className="mt-10 grid gap-8 md:grid-cols-2 md:gap-x-10 lg:gap-x-14">
        {turn.proof?.recording && <div className="slip typed self-start px-6 pt-6 pb-5 text-[15px] leading-6 text-ink"><SecretWord since={turn.since} /></div>}
        <p className="max-w-[52ch] self-center text-[15px] leading-6 text-graphite">
          What the libraries can still tell: that a question was asked, when, from which address, and how many bytes.
          Sealing hides the words, not the fact that you asked.
        </p>
      </div>
    </main>
  )
}
