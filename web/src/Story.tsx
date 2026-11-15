import { motion, useInView, useReducedMotion } from 'motion/react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { hex, rng } from './sim'

const QUERIES = [
  'chest pain when breathing',
  'is my period late because I am pregnant',
  'how to stop drinking alone',
  'HIV test results what now',
  'signs of postpartum depression',
  'can my job fire me for taking leave',
  'lump in my breast what is it',
  'how to talk to my kid about anxiety',
]
const RECIPIENTS = ['Google', 'Microsoft', 'X']

/** A search box that types one query after another, then either sends readable copies to three companies or sends nothing readable. */
export function SearchDemo({ mode }: { mode: 'leak' | 'sealed' }) {
  const ref = useRef<HTMLDivElement>(null)
  const inView = useInView(ref, { amount: 0.6 })
  const reduce = useReducedMotion()
  const [qi, setQi] = useState(0)
  const next = useRef(0)
  const QUERY = QUERIES[qi]
  const [typed, setTyped] = useState(reduce ? QUERIES[0].length : 0)
  const [sent, setSent] = useState(Boolean(reduce))
  const ciphers = useMemo(() => QUERIES.map((_, i) => hex(rng(7 + i), 22)), [])
  const cipher = ciphers[qi]

  useEffect(() => {
    if (!inView || reduce) return
    const timers: number[] = []
    const run = () => {
      const idx = next.current
      const text = QUERIES[idx]
      setQi(idx); setSent(false); setTyped(0)
      let i = 0
      const type = window.setInterval(() => {
        i += 1
        setTyped(i)
        if (i < text.length) return
        clearInterval(type)
        timers.push(window.setTimeout(() => setSent(true), 450))
        timers.push(window.setTimeout(() => {
          let j = text.length
          const erase = window.setInterval(() => {
            j -= 3
            setTyped(Math.max(j, 0))
            if (j > 0) return
            clearInterval(erase)
            setSent(false)
            next.current = (idx + 1) % QUERIES.length
            timers.push(window.setTimeout(run, 250))
          }, 22)
          timers.push(erase)
        }, 3000))
      }, 65)
      timers.push(type)
    }
    run()
    return () => timers.forEach((t) => { clearTimeout(t); clearInterval(t) })
  }, [inView, reduce])

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
        <p className="typed mt-2 truncate text-[12.5px] leading-5 text-graphite">
          {mode === 'leak' ? 'What leaves this page' : 'What leaves this laptop'}:{' '}
          <span className={mode === 'leak' ? 'text-badger' : 'text-sealed'}>{sent || typed >= QUERY.length ? (mode === 'leak' ? `"${QUERY}"` : cipher) : '...'}</span>
        </p>
      </div>

      <div className="relative mt-3 h-[96px]">
        {sent && !reduce && [0, 1, 2].map((i) => (
          <motion.span key={`${qi}-${i}`} aria-hidden
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
            <div key={r} className="typed bg-card px-3 py-2 text-center shadow-paper transition-shadow duration-200"
              style={{ boxShadow: sent && mode === 'leak' ? 'inset 0 0 0 2px var(--color-badger), var(--shadow-paper)' : undefined }}>
              <p className="font-bold text-ink">{r}</p>
              <p className={`text-[12.5px] leading-5 ${mode === 'leak' ? 'text-badger' : 'text-sealed'}`}>
                {sent ? (mode === 'leak' ? 'may have received it' : 'received nothing') : ' '}
              </p>
              <span className="sr-only">{i}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function Beat({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <section className={`relative z-[1] mx-auto flex min-h-[60dvh] max-w-[860px] flex-col justify-center px-5 py-16 ${className}`}>{children}</section>
}

const Reveal = ({ children, delay = 0 }: { children: React.ReactNode; delay?: number }) => (
  <motion.div initial={{ opacity: 0, y: 14 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, amount: 0.6 }}
    transition={{ duration: 0.45, delay, ease: 'easeOut' }}>{children}</motion.div>
)

const SENT = ['Your name', 'Your IP address', 'The pages you visited', 'Whether you were signed in', 'What you searched']

/** The story under the hero: the Kaiser case, told in three beats. */
export function Beats() {
  return (
    <>
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
