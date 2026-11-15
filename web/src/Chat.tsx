import { motion } from 'motion/react'
import { Fragment, useRef, useState } from 'react'
import type { Citation, Plain, Status } from './api'
import { Burrow } from './Burrow'
import { Beats, SearchDemo } from './Story'
import { STAGES, splitAnswer, type Turn } from './turn'

export const short = (name: string) => name.replace(/ \(.*\)$/, '').replace(/^Federal /, '')
export const slipNo = (n: number) => `No. ${String(n).padStart(4, '0')}`

/** The call slip: where a question is written and handed in. */
export function Composer({ onAsk, busy, compare, setCompare, status, number, compact, autoFocus, disabled }: {
  onAsk: (q: string) => void; busy: boolean; compare: boolean; setCompare: (v: boolean) => void
  status: Status | null; number: number; compact?: boolean; autoFocus?: boolean; disabled?: Set<string>
}) {
  const [q, setQ] = useState('')
  const box = useRef<HTMLTextAreaElement>(null)
  const submit = () => {
    const t = q.trim()
    if (!t) { box.current?.focus(); return }
    if (!busy) { onAsk(t); setQ('') }
  }
  const libs = status?.servers ?? []
  return (
    <form onSubmit={(e) => { e.preventDefault(); submit() }} className={`slip px-5 sm:px-6 ${compact ? 'pt-4 pb-4' : 'pt-6 pb-5'}`}>
      <div className="flex items-baseline justify-between font-display text-[15px] font-black text-ink">
        <span>Call slip</span><span className="typed text-[15px] font-normal text-graphite">{slipNo(number)}</span>
      </div>
      <label htmlFor="q" className="typed mt-2 block text-[14px] leading-6 text-graphite">Your question</label>
      <textarea id="q" ref={box} rows={compact ? 1 : 3} value={q} autoFocus={autoFocus}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }}
        placeholder="Write it the way you'd say it"
        className="typed block w-full resize-none bg-[repeating-linear-gradient(transparent_0_27px,var(--color-rule)_27px_28px)] text-[17px] text-ink placeholder:text-graphite/70 focus:outline-none" />
      {!compact && libs.length > 0 && (
        <div className="mt-4 border-t border-dashed border-graphite/40 pt-3">
          <p className="typed text-[14px] leading-6 text-graphite">Send sealed to</p>
          <ul className="mt-1 grid gap-x-6 text-[15px] leading-7 sm:grid-cols-2">
            {libs.map((s) => (
              <li key={s.url} className={`flex items-baseline gap-2 ${s.ok && !disabled?.has(s.url) ? 'text-ink' : 'text-graphite line-through'}`}>
                <span aria-hidden className="typed">{s.ok && !disabled?.has(s.url) ? '[x]' : '[ ]'}</span>
                <span>{short(s.name)}</span>
                {s.num_chunks != null && <span className="typed text-[13px] text-graphite">{s.num_chunks.toLocaleString()}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className={`flex flex-wrap items-end justify-between gap-x-6 gap-y-3 ${compact ? 'mt-3' : 'mt-4'}`}>
        <label className="flex max-w-[44ch] cursor-pointer items-start gap-2.5 text-[14px] leading-5 text-graphite select-none">
          <input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} className="mt-0.5 size-4 accent-[#1E1C1A]" />
          Also send an unsealed copy to a normal AI service, to compare what each one keeps
        </label>
        <button type="submit" aria-disabled={busy || undefined}
          className={`press h-11 shrink-0 rounded-[2px] px-5 font-display text-[15px] font-bold text-white ${busy ? 'cursor-wait bg-graphite' : 'bg-badger hover:bg-stamp'}`}>
          {busy ? 'Searching' : 'Hand it in'}
        </button>
      </div>
    </form>
  )
}

export function Landing({ status, examples, onAsk, children }: { status: Status | null; examples: string[]; onAsk: (q: string) => void; children: React.ReactNode }) {
  const libs = (status?.servers ?? []).filter((s) => s.ok).map((s) => short(s.name))
  const total = (status?.servers ?? []).filter((s) => s.ok).reduce((n, s) => n + (s.num_chunks ?? 0), 0)
  const skip = () => {
    document.getElementById('ask')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    setTimeout(() => document.getElementById('q')?.focus({ preventScroll: true }), 500)
  }
  return (
    <>
      <Beats onSkip={skip} />
      <main id="ask" className="relative z-[1] mx-auto grid min-h-[calc(100dvh-64px)] max-w-[1120px] scroll-mt-4 content-center gap-y-8 px-5 pt-6 pb-16 md:grid-cols-[1fr_540px] md:gap-x-16">
        <div className="md:self-end">
          <h2 className="max-w-[16ch] font-display text-[40px] leading-[1.05] font-black tracking-[-0.02em] text-ink sm:text-[52px]">
            Blindspot can't leak your question. It never sees it.
          </h2>
          <p className="mt-5 max-w-[48ch] text-[17px] leading-7 text-graphite">
            Your question is sealed on this laptop before it goes anywhere.
            {libs.length > 0 && <> {libs.length > 1 ? `${libs.slice(0, -1).join(', ')} and ${libs[libs.length - 1]}` : libs[0]} search all {total.toLocaleString()} of their passages for it without being able to read it.</>}
            {' '}The answer is written here, from what they send back.
          </p>
          <div className="mt-8"><SearchDemo mode="sealed" /></div>
        </div>
        <div className="relative md:col-start-2 md:row-span-2 md:row-start-1 md:self-center">
          <div className="md:rotate-[-1.2deg]">{children}</div>
          <div className="absolute -top-[84px] right-6 hidden md:block"><Burrow size={92} mood="idle" /></div>
        </div>
        <div className="md:self-start">
          {examples.length > 0 && <p className="text-[14px] text-graphite">Or try one of these</p>}
          <ul className="mt-2 space-y-1.5">
            {examples.map((s) => (
              <li key={s}>
                <button onClick={() => onAsk(s)} className="text-left text-[16px] leading-6 text-ink underline decoration-graphite/50 underline-offset-4 hover:decoration-badger">{s}</button>
              </li>
            ))}
          </ul>
        </div>
      </main>
    </>
  )
}

function FiledSlip({ turn, number }: { turn: Turn; number: number }) {
  const next = STAGES.findIndex((s) => turn.stages[s.key] === undefined)
  const working = turn.phase === 'working'
  return (
    <div className="flex items-start gap-4">
      <div className="slip relative max-w-[520px] flex-1 px-5 pt-5 pb-4 sm:rotate-[-0.6deg]">
        <div className="flex items-baseline justify-between text-[14px]">
          <span className="font-display font-black text-ink">Call slip</span>
          <span className="typed text-graphite">{slipNo(number)}</span>
        </div>
        <p className="typed mt-2 text-[17px] leading-7 text-ink">{turn.question}</p>
        <ol className="mt-3 border-t border-dashed border-graphite/40 pt-2 text-[14px] leading-6" aria-live="polite">
          {STAGES.map((s, i) => {
            const secs = turn.stages[s.key]
            const done = secs !== undefined
            const now = working && i === next
            if (!working && !done) return null
            return (
              <li key={s.key} className={`typed flex gap-2 ${done ? 'text-ink' : now ? 'text-ink' : 'text-graphite/70'}`}>
                <span aria-hidden>{done ? '[x]' : now ? '[.]' : '[ ]'}</span>
                <span className="flex-1">{s.label}</span>
                {done && <span className="text-graphite">{secs!.toFixed(2)}s</span>}
              </li>
            )
          })}
        </ol>
        {turn.result && (
          <span className="stamp absolute top-1.5 right-[104px] text-[12px] text-stamp" style={{ ['--r' as string]: '-7deg' }}>Answered</span>
        )}
      </div>
      {working && <Burrow size={64} mood="dig" className="hidden shrink-0 sm:inline-block" />}
    </div>
  )
}

function AnswerText({ body, open, setOpen }: { body: string; open: number | null; setOpen: (n: number | null) => void }) {
  return (
    <p className="typed text-[17px] whitespace-pre-line text-ink">
      {body.split(/(\[\d+\])/g).map((p, i) => {
        const m = p.match(/^\[(\d+)\]$/)
        if (!m) return <Fragment key={i}>{p}</Fragment>
        const n = Number(m[1])
        return (
          <button key={i} onClick={() => setOpen(open === n ? null : n)} aria-label={`Source ${n}`} aria-pressed={open === n}
            className={`mx-px px-0.5 align-super text-[12px] leading-none font-bold underline underline-offset-2 ${open === n ? 'bg-highlighter text-ink' : 'text-badger'}`}>
            {n}
          </button>
        )
      })}
    </p>
  )
}

function Source({ c, n, open, library }: { c: Citation; n: number; open: boolean; library?: string }) {
  const host = (() => { try { return new URL(c.url).hostname.replace(/^www\./, '') } catch { return c.url } })()
  const lib = c.source_name ? short(c.source_name) : library && short(library)
  return (
    <li className={`typed grid grid-cols-[2.2em_1fr] text-[15px] ${open ? 'bg-highlighter/45' : ''}`}>
      <span className="text-graphite">[{n}]</span>
      <span className="min-w-0">
        <a href={c.url} target="_blank" rel="noreferrer" className="font-bold text-ink underline decoration-graphite/40 underline-offset-4 hover:decoration-badger">{c.title.replace(/\.+$/, '')}</a>
        <span className="text-graphite">. {lib ? `${lib}, ` : ''}{host}</span>
        {open && c.excerpt && <span className="block text-graphite">“{c.excerpt}”</span>}
      </span>
    </li>
  )
}

/** The unsealed copy sent to a normal AI service, and the line that service wrote about you in its own log. */
function CarbonCopy({ plain, onXray, libraries }: { plain?: Plain; onXray: () => void; libraries: number }) {
  const e = plain?.entry
  const when = e && !Number.isNaN(Date.parse(e.time)) ? new Date(e.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : e?.time
  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25, ease: 'easeOut' }}
      className="relative mt-6 max-w-[580px] bg-[#F6DDE1] px-5 pt-4 pb-5 shadow-paper sm:ml-20 sm:rotate-[0.7deg] sm:px-7">
      <div className="flex items-baseline justify-between gap-4">
        <span className="font-display text-[15px] font-black text-ink">Carbon copy</span>
        <span className="typed text-[14px] text-[#2B3A8C]">unsealed</span>
      </div>
      {!plain && <p className="typed mt-2 text-[15px] leading-6 text-[#2B3A8C]">Sending the same question, unsealed, to a normal AI service to compare…</p>}
      {plain?.error && (
        <p className="mt-2 text-[15px] leading-6 text-ink">The normal AI service couldn't be reached, so there is nothing to compare this time. <span className="typed text-[13px] text-graphite">{plain.error}</span></p>
      )}
      {e && (
        <>
          <p className="mt-2 text-[15px] leading-6 text-ink">
            The same question also went, unsealed, to a normal AI service. This is the line it wrote about you in its own log:
          </p>
          <div className="relative">
          <span className="stamp absolute top-1 right-0 text-[15px] text-stamp" style={{ ['--r' as string]: '-8deg', ['--d' as string]: '.6s' }}>Kept on file</span>
          <dl className="typed mt-3 grid grid-cols-[4.5em_1fr] gap-y-1 text-[15px] leading-6 text-[#2B3A8C]">
            <dt className="text-graphite">time</dt><dd>{when}</dd>
            <dt className="text-graphite">from</dt><dd>{e.client}</dd>
            <dt className="text-graphite">asked</dt><dd className="font-bold text-ink">“<mark className="mark bg-transparent" style={{ ['--d' as string]: '.35s' }}>{e.question}</mark>”</dd>
            {e.returned?.length > 0 && <><dt className="text-graphite">sent</dt><dd>{[...new Set(e.returned.map((x) => x.title))].join('; ')}</dd></>}
          </dl>
          </div>
          <p className="mt-4 border-t border-dashed border-graphite/40 pt-3 text-[15px] leading-6 text-ink">
            {libraries > 1 ? `All ${libraries} libraries` : 'The library'} got sealed bytes instead and kept nothing they can read.{' '}
            <button onClick={onXray} className="typed font-bold text-badger underline underline-offset-4 hover:text-stamp">Compare them on the receipt</button>
          </p>
        </>
      )}
    </motion.div>
  )
}

export function TurnView({ turn, number, onXray, onRetry, nameOf }: { turn: Turn; number: number; onXray: () => void; onRetry?: () => void; nameOf: (url?: string) => string | undefined }) {
  const [open, setOpen] = useState<number | null>(null)
  const r = turn.result
  const { body, disclaimer } = r ? splitAnswer(r) : { body: '', disclaimer: '' }
  return (
    <article className="py-10">
      <FiledSlip turn={turn} number={number} />
      {turn.error && (
        <div role="alert" className="slip mt-6 max-w-[560px] px-5 py-4 text-[15px] leading-6">
          <p className="font-bold text-stamp">This question stopped at “{turn.error.stage}”</p>
          <p className="mt-1 text-ink">{turn.error.message}</p>
          {turn.error.fix && <p className="mt-1.5 text-graphite">To fix it: <span className="typed text-ink">{turn.error.fix}</span></p>}
          <p className="mt-1.5 text-graphite">Nothing was retried in a less private mode.</p>
          {onRetry && (
            <button onClick={onRetry} className="press mt-3 h-10 rounded-[2px] bg-badger px-4 font-display text-sm font-bold text-white hover:bg-stamp">
              Try this question again
            </button>
          )}
        </div>
      )}
      {r && (
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25, ease: 'easeOut' }}
          className="catalog mt-8 px-6 pt-[52px] pb-14 sm:ml-10 sm:px-10">
          <div className="absolute inset-x-6 top-3 flex items-baseline justify-between gap-4 sm:inset-x-10">
            <span className="typed truncate text-[15px] font-bold text-ink">{r.citations[0]?.title ?? 'Answer'}</span>
            <span className="typed shrink-0 text-[14px] text-graphite">{r.citations.length} source{r.citations.length === 1 ? '' : 's'}</span>
          </div>
          {r.urgent && (
            <p role="alert" className="typed mb-7 border-2 border-stamp px-3 text-[16px] font-bold text-stamp">{r.urgent.message}</p>
          )}
          {r.status === 'answered'
            ? <AnswerText body={body} open={open} setOpen={setOpen} />
            : <p className="typed text-[17px] text-ink">No reliable source for this in the connected libraries. These were the closest passages, so you can judge for yourself.</p>}
          <ol className="mt-7">
            {r.citations.map((c, i) => <Source key={`${c.source ?? ''}${c.id}-${i}`} c={c} n={i + 1} open={open === i + 1} library={nameOf(c.server)} />)}
          </ol>
          {(r.checks?.removed_sentences ?? 0) > 0 && (
            <p className="typed mt-7 text-[14px] text-graphite">
              {r.checks!.removed_sentences} sentence{r.checks!.removed_sentences === 1 ? '' : 's'} the model wrote without a source {r.checks!.removed_sentences === 1 ? 'was' : 'were'} taken out before you saw this.
            </p>
          )}
          <div className="mt-7 flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
            <p className="typed text-[13px] text-graphite">{disclaimer || 'General information from the connected libraries, not professional advice.'}</p>
            <button onClick={onXray} className="press typed text-[15px] font-bold text-badger underline underline-offset-4 hover:text-stamp">
              {turn.proof ? 'Print the receipt: what left this laptop' : 'Checking what left this laptop…'}
            </button>
          </div>
        </motion.div>
      )}
      {r && turn.compare && <CarbonCopy plain={turn.plain} onXray={onXray} libraries={turn.trace?.servers?.length ?? 1} />}
    </article>
  )
}
