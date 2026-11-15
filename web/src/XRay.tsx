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

function RouteBlock({ r, words, logged, i }: { r: Route; words: string[]; logged?: string; i: number }) {
  const leaked = r.found.length > 0
  const name = libraryName(r.route)
  return (
    <div className="relative py-3">
      <Line strong left={`${name}${leaked ? ' (unsealed)' : ''}`} right={fmtBytes(r.bytes)} />
      <Line left={`  ${r.requests} request${r.requests === 1 ? '' : 's'}`} />
      {leaked
        ? <p className="mt-1 text-ink">It logged: “<Highlight text={logged ?? r.matches[0]?.context ?? ''} words={words} />”</p>
        : <p className="hex mt-1 line-clamp-2 text-[13px] text-graphite">{r.sample_hex.slice(0, 96)}</p>}
      <Line strong left="Your words found" right={`${r.found.length} of ${r.words}`} />
      <span className={`stamp absolute top-10 right-1 text-[15px] ${leaked ? 'text-stamp' : 'text-sealed'}`}
        style={{ ['--r' as string]: `${i % 2 ? 5 : -7}deg`, ['--d' as string]: `${0.25 + i * 0.18}s` }}>
        {leaked ? 'Read' : 'Not read'}
      </span>
    </div>
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

  return (
    <main className="mx-auto grid max-w-[1120px] gap-10 px-5 pt-6 pb-24 md:grid-cols-[1fr_480px] md:gap-16">
      <div className="md:sticky md:top-8 md:self-start">
        <button onClick={onBack} className="text-[15px] text-ink underline decoration-graphite/50 underline-offset-4 hover:decoration-badger">
          Back to the conversation
        </button>
        <h2 className="mt-8 max-w-[14ch] text-[36px] leading-[1.05] font-black tracking-[-0.02em] text-ink sm:text-[48px]">
          What left this laptop
        </h2>
        <p className="mt-4 max-w-[46ch] text-[17px] leading-7 text-graphite">
          A recorder sat between this app and every library and kept each byte that went out. This receipt is what it saw,
          and what it found when it searched those bytes for the words in your question.
        </p>
        <p className="mt-4 max-w-[46ch] text-[15px] leading-6 text-graphite">
          What the libraries can still tell: that a question was asked, when, from which address, and how many bytes.
          Sealing hides the words, not the fact that you asked.
        </p>
        <Burrow size={96} mood="idle" className="mt-10 hidden md:inline-block" />
      </div>

      <div className="receipt typed mx-auto w-full max-w-[480px] px-6 pt-7 pb-12 text-[15px] leading-6 text-ink sm:px-8">
        <p className="text-center font-display text-[20px] font-black">Blind RAG</p>
        <p className="text-center text-graphite">Traffic receipt, {slipNo(number)}</p>
        <p className="text-center text-graphite">{when.toLocaleDateString()} {when.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</p>
        <Cut />
        <p className="font-bold">Your question</p>
        <p>{turn.question}</p>
        <p className="mt-1 text-graphite">Read only on this laptop.</p>
        <p className="mt-3 font-bold">As it was sent</p>
        <p className="hex text-[14px] text-sealed"><Scramble from={turn.question} to={cipher} run={Boolean(cipher)} /></p>
        <Cut />
        <Line left="Read on this laptop" right={t(s.embedding)} />
        <Line left="Sealed" right={t(s.encrypting)} />
        <Line left="Searched without reading" right={t(s.scoring)} />
        <Line left="Passages fetched" right={t(s.fetching)} />
        <Line left="Answer written here" right={t(s.answering, 1)} />
        <Cut />
        {servers.map((x) => (
          <div key={x.server} className="mb-2">
            <Line strong left={nameOf(x.server)} right={`${fmtBytes(upOf(x))} sealed`} />
            <Line left={`  scored ${x.num_chunks.toLocaleString()} passages`} right={`sent ${x.fetched}`} />
          </div>
        ))}
        <Cut />
        {!turn.proof && <p className="text-graphite">Searching the recording...</p>}
        {turn.proof && !turn.proof.recording && (
          <p>Recording is off. Start the demo with <span className="font-bold">./web/demo.sh</span> to print this part.</p>
        )}
        {turn.proof && turn.proof.recording && (
          <>
            <p className="font-bold">Words searched for</p>
            <p>{words.join(', ')}</p>
            <div className="mt-2 divide-y divide-dashed divide-graphite/40">
              {routes.map((r, i) => <RouteBlock key={r.route} r={r} i={i} words={words}
                logged={r.route === 'plain' ? turn.plain?.entry?.question : undefined} />)}
            </div>
            {blind.length > 0 && blind.every((r) => r.found.length === 0) && (
              <>
                <Cut />
                <p className="font-bold">None of your words reached {blind.length === 1 ? 'the library' : `any of the ${blind.length} libraries`}.</p>
                <p className="text-graphite">Odds of one appearing by luck in that much random data: about {Math.max(...blind.map((r) => r.chance_by_luck)).toExponential(0)}.</p>
              </>
            )}
            <Cut />
            <SecretWord since={turn.since} />
          </>
        )}
        <Cut />
        <p className="text-center text-graphite">Thank you for asking privately.</p>
      </div>
    </main>
  )
}
