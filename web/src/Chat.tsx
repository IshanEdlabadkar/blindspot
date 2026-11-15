import { AnimatePresence, motion } from 'motion/react'
import { Fragment, useState } from 'react'
import type { Citation, Status } from './api'
import { STAGES, splitAnswer, type Turn } from './turn'

const SUGGESTIONS = [
  'How is chlamydia treated, and can I get it again?',
  'Can I take FMLA leave for a pregnancy complication?',
  'Is Huntington disease passed down from my parents?',
]

export function Composer({ onAsk, busy, compare, setCompare, autoFocus }: {
  onAsk: (q: string) => void; busy: boolean; compare: boolean; setCompare: (v: boolean) => void; autoFocus?: boolean
}) {
  const [q, setQ] = useState('')
  // A textarea can't truncate its placeholder, so phones get a shorter one.
  const narrow = typeof window !== 'undefined' && window.matchMedia('(max-width: 480px)').matches
  const submit = () => { const t = q.trim(); if (t && !busy) { onAsk(t); setQ('') } }
  return (
    <div>
      <form onSubmit={(e) => { e.preventDefault(); submit() }}
        className="flex items-end gap-2 rounded-2xl border border-seam bg-slate p-2 shadow-[0_0_0_1px_rgba(127,209,196,0)] transition-shadow focus-within:shadow-[0_0_0_1px_rgba(127,209,196,0.45)]">
        <label htmlFor="q" className="sr-only">Your question</label>
        <textarea id="q" rows={1} value={q} autoFocus={autoFocus} disabled={busy}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }}
          placeholder={narrow ? 'Ask anything private' : 'Ask anything you’d keep private'}
          className="max-h-40 min-h-11 flex-1 resize-none bg-transparent px-3 py-2.5 text-[17px] leading-6 text-paper placeholder:text-dim focus:outline-none disabled:opacity-60" />
        <button type="submit" disabled={busy || !q.trim()}
          className="h-11 shrink-0 rounded-xl bg-seal px-5 text-[15px] font-medium text-night transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-35">
          {busy ? 'Working' : <><span className="sm:hidden">Ask</span><span className="hidden sm:inline">Ask privately</span></>}
        </button>
      </form>
      <label className="mt-3 flex cursor-pointer items-center gap-2.5 text-sm text-fog select-none">
        <input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)}
          className="size-4 accent-[#7FD1C4]" />
        Also send it to a normal AI service, unencrypted, so you can compare what each one keeps
      </label>
    </div>
  )
}

export function EmptyState({ status, onAsk, children }: { status: Status | null; onAsk: (q: string) => void; children: React.ReactNode }) {
  const libs = status?.servers ?? []
  const total = libs.reduce((n, s) => n + (s.num_chunks ?? 0), 0)
  return (
    <div className="mx-auto max-w-[720px] px-5 pt-[14vh] pb-20">
      <h1 className="max-w-[16ch] text-[44px] leading-[1.06] font-semibold tracking-[-0.02em] text-paper sm:text-[56px]">
        Ask the question you wouldn’t type into a search bar.
      </h1>
      <p className="mt-5 max-w-[56ch] text-[17px] leading-7 text-fog">
        Your question is locked on this laptop before it goes anywhere. {libs.length || 'The'} public libraries search
        it without being able to read it, and the answer is written here, with its sources.
      </p>
      <div className="mt-9">{children}</div>
      <div className="mt-7 flex flex-wrap gap-2">
        {SUGGESTIONS.map((s) => (
          <button key={s} onClick={() => onAsk(s)}
            className="rounded-2xl border border-seam px-3.5 py-1.5 text-left text-sm text-fog transition-colors hover:border-seal/60 hover:text-paper">
            {s}
          </button>
        ))}
      </div>
      {libs.length > 0 && (
        <p className="mt-14 text-sm leading-6 text-dim">
          Searching {libs.map((s, i) => (
            <Fragment key={s.url}>
              {i > 0 && (i === libs.length - 1 ? ' and ' : ', ')}
              <span className={s.ok ? 'text-fog' : 'text-leak'}>{s.name.replace(/ \(.*\)$/, '')}{s.ok ? '' : ' (offline)'}</span>
            </Fragment>
          ))}{total ? `: ${total.toLocaleString()} passages in all.` : '.'}
        </p>
      )}
    </div>
  )
}

function Progress({ turn }: { turn: Turn }) {
  const next = STAGES.findIndex((s) => turn.stages[s.key] === undefined)
  return (
    <ol className="space-y-2 text-[15px]" aria-live="polite">
      {STAGES.map((s, i) => {
        const secs = turn.stages[s.key]
        const state = secs !== undefined ? 'done' : i === next ? 'now' : 'later'
        return (
          <li key={s.key} className={`flex items-baseline gap-3 ${state === 'later' ? 'text-dim' : state === 'now' ? 'text-paper' : 'text-fog'}`}>
            <span aria-hidden className={`inline-block size-1.5 translate-y-[-2px] rounded-full ${state === 'done' ? 'bg-seal' : state === 'now' ? 'animate-pulse bg-paper' : 'bg-seam'}`} />
            <span className="flex-1">{s.label}</span>
            {secs !== undefined && <span className="hex text-xs text-dim">{secs.toFixed(2)} s</span>}
          </li>
        )
      })}
    </ol>
  )
}

function AnswerText({ body, open, setOpen }: { body: string; open: number | null; setOpen: (n: number | null) => void }) {
  const parts = body.split(/(\[\d+\])/g)
  return (
    <p className="text-[17px] leading-[1.7] whitespace-pre-line text-paper">
      {parts.map((p, i) => {
        const m = p.match(/^\[(\d+)\]$/)
        if (!m) return <Fragment key={i}>{p}</Fragment>
        const n = Number(m[1])
        return (
          <button key={i} onClick={() => setOpen(open === n ? null : n)} aria-label={`Source ${n}`}
            className={`mx-0.5 inline-flex h-5 min-w-5 -translate-y-0.5 items-center justify-center rounded-md px-1 align-middle text-[11px] font-medium transition-colors ${open === n ? 'bg-seal text-night' : 'bg-lift text-seal hover:bg-seal-deep'}`}>
            {n}
          </button>
        )
      })}
    </p>
  )
}

function Source({ c, n, highlight, library }: { c: Citation; n: number; highlight: boolean; library?: string }) {
  const host = (() => { try { return new URL(c.url).hostname.replace(/^www\./, '') } catch { return c.url } })()
  const lib = c.source_name?.replace(/ \(.*\)$/, '') ?? library
  return (
    <li className={`rounded-xl border p-4 transition-colors ${highlight ? 'border-seal/60 bg-lift' : 'border-seam'}`}>
      <div className="flex items-baseline gap-2.5">
        <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-md bg-lift px-1 text-[11px] font-medium text-seal">{n}</span>
        <a href={c.url} target="_blank" rel="noreferrer" className="font-medium text-paper underline-offset-4 hover:underline">{c.title}</a>
      </div>
      {c.excerpt && <blockquote className="mt-2.5 border-l-2 border-seal-deep pl-3 text-[15px] leading-6 text-fog">{c.excerpt}</blockquote>}
      <p className="mt-2.5 text-[13px] text-dim">{lib ? <><span className="text-fog">{lib}</span>, </> : ''}{host}</p>
    </li>
  )
}

export function TurnView({ turn, onXray, nameOf }: { turn: Turn; onXray: () => void; nameOf: (url?: string) => string | undefined }) {
  const [open, setOpen] = useState<number | null>(null)
  const r = turn.result
  const { body, disclaimer } = r ? splitAnswer(r) : { body: '', disclaimer: '' }
  return (
    <article className="border-t border-seam py-10 first:border-t-0">
      <p className="mb-6 max-w-[60ch] text-[19px] leading-7 font-medium text-paper">{turn.question}</p>
      {turn.phase === 'working' && <Progress turn={turn} />}
      {turn.error && (
        <div role="alert" className="rounded-xl border border-seam bg-slate p-4 text-[15px] leading-6">
          <p className="text-paper">This question stopped at “{turn.error.stage}”: {turn.error.message}</p>
          {turn.error.fix && <p className="mt-1.5 text-fog">To fix it: <span className="hex text-[13px] text-paper">{turn.error.fix}</span></p>}
          <p className="mt-1.5 text-fog">Nothing was retried in a less private mode.</p>
        </div>
      )}
      {r && (
        <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, ease: 'easeOut' }}>
          {r.urgent && (
            <div role="alert" className="mb-5 rounded-xl border border-amber/40 bg-amber/10 px-4 py-3 text-[15px] leading-6 text-amber">
              {r.urgent.message}
            </div>
          )}
          {r.status === 'answered'
            ? <AnswerText body={body} open={open} setOpen={setOpen} />
            : <p className="text-[17px] leading-7 text-paper">No reliable source for this in the connected libraries. These were the closest passages, so you can judge for yourself.</p>}
          <AnimatePresence initial={false}>
            <motion.ol layout className="mt-6 space-y-2.5">
              {r.citations.map((c, i) => (
                <Source key={`${c.source ?? ''}${c.id}-${i}`} c={c} n={i + 1} highlight={open === i + 1} library={nameOf(c.server)} />
              ))}
            </motion.ol>
          </AnimatePresence>
          <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
            <p className="text-[13px] text-dim">{disclaimer || 'General information, not medical or legal advice.'}</p>
            <button onClick={onXray}
              className="rounded-xl border border-seal/50 px-4 py-2 text-sm font-medium text-seal transition-colors hover:bg-seal hover:text-night">
              {turn.proof ? 'See what left this laptop' : 'Checking what left this laptop…'}
            </button>
          </div>
        </motion.div>
      )}
    </article>
  )
}
