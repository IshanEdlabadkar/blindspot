import { useMemo, useState } from 'react'
import type { Turn } from './turn'

const DECOYS = [
  'Can I take FMLA leave for a pregnancy complication?',
  'What are the symptoms of depression?',
  'How is chlamydia treated and can I get it again?',
  'What is LDL and why is it called the bad kind?',
  'How much salt should I eat in a day?',
  'What is MRSA and how do people catch it?',
  'Is Huntington disease passed down from my parents?',
]

/** Small seeded shuffle so the five choices (and where the real one sits) stay put for a given question. */
function seeded(text: string) {
  let h = 2166136261
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619)
  return () => {
    h = (h + 0x6d2b79f5) | 0
    let t = Math.imul(h ^ (h >>> 15), 1 | h)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

export function options(question: string, extra: string[] = []): string[] {
  const rnd = seeded(question)
  const pool = [...new Set([...extra, ...DECOYS])].filter((d) => d !== question)
  for (let i = pool.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [pool[i], pool[j]] = [pool[j], pool[i]] }
  const five = [...pool.slice(0, 4), question]
  for (let i = five.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [five[i], five[j]] = [five[j], five[i]] }
  return five
}

/** The attacker holds everything the library kept. Can they tell which of five questions was asked? */
export function Attacker({ turn, pool }: { turn: Turn; pool?: string[] }) {
  const opts = useMemo(() => options(turn.question, pool), [turn.question, pool])
  const [pick, setPick] = useState<string | null>(null)
  const [checked, setChecked] = useState(false)
  const right = pick === turn.question
  return (
    <div className="slip typed px-6 pt-6 pb-5 text-[15px] leading-6 text-ink">
      <p className="font-display font-black text-ink">Play the attacker</p>
      <p className="mt-1 text-graphite">
        You hold everything the libraries kept: sealed bytes, sizes and times. Which of these five questions was asked?
      </p>
      <fieldset className="mt-3 space-y-1.5">
        <legend className="sr-only">Pick the question you think was asked</legend>
        {opts.map((o) => (
          <label key={o} className="flex cursor-pointer items-start gap-2.5">
            <input type="radio" name={`guess-${turn.id}`} checked={pick === o} disabled={checked}
              onChange={() => setPick(o)} className="mt-1.5 size-4 accent-[#1E1C1A]" />
            <span className={checked && o === turn.question ? 'bg-highlighter/60 font-bold' : ''}>{o}</span>
          </label>
        ))}
      </fieldset>
      <div className="mt-4 flex flex-wrap items-center gap-4">
        <button type="button" disabled={!pick || checked} onClick={() => setChecked(true)}
          className="press h-10 rounded-[2px] bg-ink px-4 font-display text-sm font-bold text-card disabled:opacity-40">
          Check guess
        </button>
        {checked && (
          <button type="button" onClick={() => { setPick(null); setChecked(false) }}
            className="text-[14px] text-ink underline decoration-graphite/50 underline-offset-4 hover:decoration-badger">Guess again</button>
        )}
      </div>
      {checked && (
        <p role="status" className={`mt-3 ${right ? 'text-ink' : 'text-stamp'}`}>
          {right
            ? 'Correct, by luck: a 1 in 5 guess. Nothing the libraries kept pointed to it.'
            : 'Wrong. Nothing the libraries kept tells these five questions apart.'}
          <span className="block text-graphite">The question was: {turn.question}</span>
        </p>
      )}
    </div>
  )
}
