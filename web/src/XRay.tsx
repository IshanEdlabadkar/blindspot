import { motion, useReducedMotion } from 'motion/react'
import { Fragment, useEffect, useMemo, useState } from 'react'
import { fmtBytes, searchWire, type Route, type ServerTrace, type Status } from './api'
import { libraryName, type Turn } from './turn'

const HEX = '0123456789abcdef'

/** The signature moment: the question's own letters turn into the real ciphertext as they cross the seam. */
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
      const x = Math.min(1, (now - start) / 1800)
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
  return <span aria-label="Your question, encrypted" className={p >= 1 ? 'hex text-seal' : ''}>{out}</span>
}

function Step({ n, side, title, children, delay }: {
  n: number; side: 'here' | 'there' | 'both'; title: string; children: React.ReactNode; delay: number
}) {
  const reduce = useReducedMotion()
  // Full-width steps sit on the night background above the seam line, so it never crosses their text.
  const col = side === 'here' ? 'md:col-start-1' : side === 'there' ? 'md:col-start-2' : 'z-[1] bg-night md:col-span-2 md:py-3'
  return (
    <motion.section className={`relative ${col}`}
      initial={reduce ? false : { opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
      transition={{ delay: reduce ? 0 : delay, duration: 0.45, ease: [0.2, 0.7, 0.2, 1] }}>
      <h3 className="flex items-baseline gap-3 text-[15px] font-medium text-paper">
        <span className="hex text-sm text-seal">{n}</span>{title}
      </h3>
      <div className="mt-3 pl-7 text-[15px] leading-6 text-fog">{children}</div>
    </motion.section>
  )
}

function Highlight({ text, words }: { text: string; words: string[] }) {
  if (!words.length) return <>{text}</>
  const re = new RegExp(`(${words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'gi')
  return <>{text.split(re).map((part, i) => i % 2 ? <mark key={i} className="rounded bg-leak/25 px-0.5 text-leak">{part}</mark> : <Fragment key={i}>{part}</Fragment>)}</>
}

function ProofRow({ r, words, logged }: { r: Route; words: string[]; logged?: string }) {
  const leaked = r.found.length > 0
  const name = libraryName(r.route)
  const shown = leaked && logged ? `It logged: “${logged}”` : r.matches[0]?.context ?? ''
  return (
    <div className={`grid gap-x-6 gap-y-3 border-t py-5 sm:grid-cols-[1fr_auto] ${leaked ? 'border-leak/40' : 'border-seam'}`}>
      <div className="min-w-0">
        <p className="text-paper">{name}{leaked ? ', unencrypted' : ''}</p>
        <p className="mt-1 text-sm text-dim">{r.requests} request{r.requests === 1 ? '' : 's'}, {fmtBytes(r.bytes)} sent from this laptop</p>
        {leaked
          ? <p className="mt-3 text-[15px] leading-6 text-paper"><Highlight text={shown} words={words} /></p>
          : <p className="hex mt-3 line-clamp-2 text-[13px] leading-5 text-dim">{r.sample_hex.slice(0, 120)}…</p>}
      </div>
      <div className={`text-right ${leaked ? 'text-leak' : 'text-seal'}`}>
        <p className="text-[40px] leading-none font-semibold tracking-tight tabular-nums">
          {r.found.length}<span className="text-[22px] text-dim"> of {r.words}</span>
        </p>
        <p className="mt-1.5 text-sm">{leaked ? 'of your words found' : 'of your words found'}</p>
      </div>
    </div>
  )
}

function SecretWord({ since }: { since?: string }) {
  const [word, setWord] = useState('')
  const [res, setRes] = useState<{ words: string[]; routes: Route[] } | null>(null)
  const go = async () => { if (word.trim()) setRes(await searchWire(word.trim(), since)) }
  return (
    <div className="mt-8 rounded-2xl border border-seam bg-slate p-5">
      <label htmlFor="secret" className="text-paper">Search the same traffic for any word</label>
      <p className="mt-1 text-sm text-fog">Try a name or a word you put in your question. Four letters or more.</p>
      <form className="mt-4 flex gap-2" onSubmit={(e) => { e.preventDefault(); void go() }}>
        <input id="secret" value={word} onChange={(e) => { setWord(e.target.value); setRes(null) }}
          className="h-11 flex-1 rounded-xl border border-seam bg-night px-3 text-paper placeholder:text-dim focus:border-seal/60 focus:outline-none"
          placeholder="e.g. a name" />
        <button className="h-11 rounded-xl bg-seal px-4 text-sm font-medium text-night disabled:opacity-40" disabled={!word.trim()}>Search</button>
      </form>
      {res && (
        <ul className="mt-4 space-y-1.5 text-[15px]">
          {!res.words.length && <li className="text-fog">Use a word of four letters or more.</li>}
          {res.words.length > 0 && res.routes.map((r) => (
            <li key={r.route} className={r.found.length ? 'text-leak' : 'text-seal'}>
              {libraryName(r.route)}: {r.found.length ? 'found' : 'not found'} in {fmtBytes(r.bytes)}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function XRay({ turn, status, onBack }: { turn: Turn; status: Status | null; onBack: () => void }) {
  const tr = turn.trace
  const servers: ServerTrace[] = tr?.servers ?? (tr ? [{ server: tr.server ?? '', corpus_version: '', num_chunks: tr.num_chunks ?? 0,
    requests: tr.requests ?? [], timings: tr.timings ?? {}, fetched: 10, used: turn.result?.citations.length ?? 0,
    ciphertext_sample: tr.ciphertext_sample }] : [])
  const nameOf = (url: string) => status?.servers.find((s) => s.url === url)?.name.replace(/ \(.*\)$/, '') ?? url
  const cipher = servers.find((s) => s.ciphertext_sample)?.ciphertext_sample ?? tr?.ciphertext_sample ?? turn.proof?.routes.find((r) => r.sample_hex)?.sample_hex ?? ''
  const s = turn.stages
  const words = turn.proof?.words ?? []
  const routes = [...(turn.proof?.routes ?? [])].sort((a, b) => Number(a.route === 'plain') - Number(b.route === 'plain'))
  const blind = routes.filter((r) => r.route !== 'plain')
  const totalPassages = servers.reduce((n, x) => n + (x.num_chunks || 0), 0)

  return (
    <div className="mx-auto max-w-[1080px] px-5 pt-10 pb-24">
      <button onClick={onBack} className="text-sm text-fog hover:text-paper">Back to the conversation</button>
      <h2 className="mt-6 max-w-[22ch] text-[34px] leading-[1.1] font-semibold tracking-[-0.015em] sm:text-[40px]">
        What happened to your question
      </h2>
      <p className="mt-3 max-w-[60ch] text-[16px] leading-7 text-fog">
        Every number here was recorded while your question was answered. The left side is this laptop. The right side is everything else.
      </p>

      <div className="relative mt-12 grid gap-x-16 gap-y-12 md:grid-cols-2">
        <div aria-hidden className="absolute top-0 bottom-0 left-1/2 hidden w-px bg-gradient-to-b from-seam via-seal-deep to-seam md:block" />
        <p className="text-sm text-dim md:col-start-1">This laptop</p>
        <p className="text-sm text-dim md:col-start-2 md:row-start-1">Everywhere else</p>

        <Step n={1} side="here" title="Your question is read here, and only here" delay={0.05}>
          <p className="rounded-xl border border-seam bg-slate px-4 py-3 text-[16px] leading-7 text-paper">{turn.question}</p>
          <p className="mt-3">A small model on this laptop turned it into 384 numbers that capture its meaning{s.embedding !== undefined ? `, in ${s.embedding.toFixed(2)} s` : ''}.</p>
        </Step>

        <Step n={2} side="both" title="It is locked before it leaves" delay={0.4}>
          <div className="rounded-xl border border-seam bg-slate px-4 py-3 text-[16px] leading-7">
            <Scramble from={turn.question} to={cipher} run={Boolean(cipher)} />
          </div>
          <p className="mt-3">Sealed with a key that exists only in this laptop’s memory{s.encrypting !== undefined ? `, in ${s.encrypting.toFixed(2)} s` : ''}. What crosses the line is the right-hand version.</p>
        </Step>

        <Step n={3} side="there" title={`${servers.length} ${servers.length === 1 ? 'library searches' : 'libraries search'} without reading it`} delay={1.9}>
          <ul className="space-y-3">
            {servers.map((x) => {
              const up = x.requests.reduce((n, r) => n + r.request_bytes, 0)
              return (
                <li key={x.server} className="rounded-xl border border-seam px-4 py-3">
                  <p className="text-paper">{nameOf(x.server)}</p>
                  <p className="mt-1 text-sm">Received {fmtBytes(up)} of sealed data, scored all {x.num_chunks.toLocaleString()} passages, sent back exactly {x.fetched} without knowing which mattered.</p>
                </li>
              )
            })}
          </ul>
          {s.scoring !== undefined && <p className="mt-3">Scoring {totalPassages.toLocaleString()} passages took {s.scoring.toFixed(2)} s.</p>}
        </Step>

        <Step n={4} side="here" title="The answer is written here" delay={2.3}>
          <p>The passages were unlocked on this laptop, the best ones chosen, and a local model wrote the answer from them
            {s.answering !== undefined ? ` in ${s.answering.toFixed(1)} s` : ''}. {turn.result ? `It cites ${turn.result.citations.length} passage${turn.result.citations.length === 1 ? '' : 's'}.` : ''}</p>
        </Step>

        <Step n={5} side="both" title="Proof: every byte that left, searched for your words" delay={2.7}>
          {!turn.proof && <p>Searching the recorded traffic…</p>}
          {turn.proof && !turn.proof.recording && (
            <p>Traffic recording is off. Start the demo with <span className="hex text-paper">./web/demo.sh</span> to record it.</p>
          )}
          {turn.proof && turn.proof.recording && (
            <>
              <p>A recorder on this laptop, between this app and every library, kept each byte that left. It searched them for the {words.length} words in your question{words.length ? ': ' : '.'}
                {words.map((w, i) => <Fragment key={w}>{i > 0 && ', '}<span className="text-paper">{w}</span></Fragment>)}.</p>
              <div className="mt-5">
                {routes.map((r) => <ProofRow key={r.route} r={r} words={words}
                  logged={r.route === 'plain' ? turn.plain?.entry?.question : undefined} />)}
              </div>
              {blind.length > 0 && blind.every((r) => r.found.length === 0) && (
                <p className="mt-5 text-paper">None of your words reached {blind.length === 1 ? 'the library' : `any of the ${blind.length} libraries`}.
                  {' '}The chance of one appearing by luck in that much random data is about {Math.max(...blind.map((r) => r.chance_by_luck)).toExponential(0)}.</p>
              )}
              <SecretWord since={turn.since} />
            </>
          )}
        </Step>
      </div>

      <p className="mt-16 max-w-[64ch] border-t border-seam pt-6 text-sm leading-6 text-dim">
        What the libraries can still see: that a question was asked, when, from which address, and how many bytes were sent.
        Encryption hides the words, not the fact that you asked.
      </p>
    </div>
  )
}
