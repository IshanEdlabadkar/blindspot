import { motion, useInView, useReducedMotion } from 'motion/react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { hex, rng } from './sim'

const QUERY = 'chest pain when breathing'
const RECIPIENTS = ['Google', 'Microsoft', 'X']

/** A search box that types a query, then either sends readable copies to three companies or sends nothing readable. */
export function SearchDemo({ mode }: { mode: 'leak' | 'sealed' }) {
  const ref = useRef<HTMLDivElement>(null)
  const seen = useInView(ref, { once: true, amount: 0.6 })
  const reduce = useReducedMotion()
  const [typed, setTyped] = useState(reduce ? QUERY.length : 0)
  const [sent, setSent] = useState(Boolean(reduce))
  const cipher = useMemo(() => hex(rng(7), 22), [])

  useEffect(() => {
    if (!seen || reduce) return
    let i = 0
    const t = setInterval(() => {
      i += 1
      setTyped(i)
      if (i >= QUERY.length) { clearInterval(t); setTimeout(() => setSent(true), 500) }
    }, 70)
    return () => clearInterval(t)
  }, [seen, reduce])

  const leaving = mode === 'leak' ? QUERY : cipher
  return (
    <div ref={ref} className="mx-auto w-full max-w-[640px]" role="img"
      aria-label={mode === 'leak'
        ? `A search for "${QUERY}" is copied to Google, Microsoft and X.`
        : `The same search leaves only as scrambled text. Google, Microsoft and X receive nothing.`}>
      <div className="slip px-5 pt-6 pb-4">
        <p className="typed text-[13px] leading-5 text-graphite">Health encyclopedia search</p>
        <p className="typed mt-1 min-h-[34px] border-b-2 border-ink text-[19px] leading-[34px] text-ink">
          {QUERY.slice(0, typed)}<span aria-hidden className={`ml-px inline-block w-[2px] bg-ink align-middle ${typed < QUERY.length ? 'h-5' : 'h-5 opacity-30'}`} />
        </p>
        <p className="typed mt-2 text-[12.5px] leading-5 text-graphite">
          {mode === 'leak' ? 'What leaves this page' : 'What leaves this laptop'}:{' '}
          <span className={mode === 'leak' ? 'text-badger' : 'text-sealed'}>{sent || typed >= QUERY.length ? (mode === 'leak' ? `"${QUERY}"` : cipher) : '...'}</span>
        </p>
      </div>

      <div className="relative mt-3 h-[96px]">
        {sent && !reduce && [0, 1, 2].map((i) => (
          <motion.span key={i} aria-hidden
            className={`typed absolute top-0 -translate-x-1/2 whitespace-nowrap text-[12px] ${mode === 'leak' ? 'text-badger' : 'text-sealed'}`}
            initial={{ left: '50%', top: 0, opacity: 0 }}
            animate={mode === 'leak'
              ? { left: `${16.7 + i * 33.3}%`, top: 56, opacity: [0, 1, 1] }
              : { left: `${50 + (i - 1) * 8}%`, top: [0, 30], opacity: [0, 1, 0] }}
            transition={{ duration: 0.9, delay: i * 0.18, ease: 'easeOut' }}>
            {leaving.length > 18 ? `${leaving.slice(0, 16)}…` : leaving}
          </motion.span>
        ))}
        <div className="absolute inset-x-0 bottom-0 grid grid-cols-3 gap-3">
          {RECIPIENTS.map((r, i) => (
            <motion.div key={r} className="typed bg-card px-3 py-2 text-center shadow-paper"
              animate={{ y: sent && mode === 'leak' ? 0 : 0 }}
              style={{ boxShadow: sent && mode === 'leak' ? 'inset 0 0 0 2px var(--color-badger), var(--shadow-paper)' : undefined }}>
              <p className="font-bold text-ink">{r}</p>
              <p className={`text-[12.5px] leading-5 ${mode === 'leak' ? 'text-badger' : 'text-sealed'}`}>
                {sent ? (mode === 'leak' ? 'may have received it' : 'received nothing') : ' '}
              </p>
              <span className="sr-only">{i}</span>
            </motion.div>
          ))}
        </div>
      </div>
    </div>
  )
}

function Beat({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <section className={`relative z-[1] mx-auto flex min-h-[78dvh] max-w-[860px] flex-col justify-center px-5 py-16 ${className}`}>{children}</section>
}

const Reveal = ({ children, delay = 0 }: { children: React.ReactNode; delay?: number }) => (
  <motion.div initial={{ opacity: 0, y: 14 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, amount: 0.6 }}
    transition={{ duration: 0.45, delay, ease: 'easeOut' }}>{children}</motion.div>
)

const SENT = ['Your name', 'Your IP address', 'The pages you visited', 'Whether you were signed in', 'What you searched']

/** Beats 1 to 4 of the landing page: the problem, told with the Kaiser Permanente case. */
export function Beats({ onSkip }: { onSkip: () => void }) {
  return (
    <>
      <Beat>
        <div className="absolute top-2 right-5">
          <button onClick={onSkip} className="text-[14px] text-ink underline decoration-graphite/50 underline-offset-4 hover:decoration-badger">Skip to the app</button>
        </div>
        <h1 className="max-w-[18ch] text-[40px] leading-[1.05] font-black tracking-[-0.02em] text-ink sm:text-[64px]">
          You looked up a symptom on your health plan's website.
        </h1>
        <div className="mt-[34dvh]"><Reveal>
          <p className="max-w-[20ch] text-[28px] leading-9 font-bold text-badger sm:text-[40px] sm:leading-[46px]">Google, Microsoft and X may have seen it.</p>
        </Reveal></div>
      </Beat>

      <Beat>
        <SearchDemo mode="leak" />
        <Reveal delay={0.1}>
          <p className="mx-auto mt-10 max-w-[56ch] text-center text-[19px] leading-7 text-ink">
            In 2024, Kaiser Permanente notified 13.4 million members and patients that this may have happened to them.
          </p>
          <p className="mx-auto mt-2 text-center text-[13px] text-graphite">The search above is an illustrative example, not a real member's search.</p>
        </Reveal>
      </Beat>

      <Beat>
        <p className="font-display text-[15px] font-bold text-graphite">What may have been sent</p>
        <ul className="mt-3 space-y-1">
          {SENT.map((s, i) => (
            <Reveal key={s} delay={i * 0.12}>
              <li className="border-b border-dashed border-graphite/40 pb-1 font-display text-[28px] leading-10 font-black text-ink sm:text-[40px] sm:leading-[52px]">{s}</li>
            </Reveal>
          ))}
        </ul>
        <Reveal delay={0.7}>
          <p className="mt-8 max-w-[44ch] text-[22px] leading-8 text-ink">Nobody hacked anything. Tracking code on the site sent it.</p>
        </Reveal>
      </Beat>

      <Beat>
        <Reveal>
          <p className="max-w-[24ch] text-[30px] leading-9 font-black text-ink sm:text-[44px] sm:leading-[50px]">
            Kaiser removed the code and agreed to pay <span className="text-badger">$46 million</span> to settle the lawsuits.
          </p>
          <p className="mt-4 max-w-[60ch] text-[14px] leading-5 text-graphite">
            Kaiser denies wrongdoing and says it knows of no misuse of the data. Sources:{' '}
            <a className="underline underline-offset-4" href="https://therecord.media/kaiser-permanente-potential-third-party-data-exposure" target="_blank" rel="noreferrer">The Record</a>,{' '}
            <a className="underline underline-offset-4" href="https://www.hipaajournal.com/kaiser-permanente-website-tracker-breach-affects-13-4-million-individuals/" target="_blank" rel="noreferrer">HIPAA Journal</a>.
          </p>
        </Reveal>
      </Beat>
    </>
  )
}
