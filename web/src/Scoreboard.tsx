import { useEffect, useMemo, useState } from 'react'
import type { Proof } from './api'
import { CATS, makeEvents, makePeople, tally } from './sim'

type Card = {
  retrieval_n?: number; top10_float?: number; top10_int8?: number
  answerable?: number; answered?: number; cited?: number; should_decline?: number; declined?: number; wrong?: number
}

const pct = (n: number, d: number) => (d > 0 ? Math.round((100 * n) / d) : 0)

/** One metric, two bars: a normal AI service against Blindspot. */
function Row({ label, normal, blind, note, unit = '%', lowerIsBetter }: {
  label: string; normal: number; blind: number; note?: string; unit?: string; lowerIsBetter?: boolean
}) {
  const max = unit === '%' ? 100 : Math.max(normal, blind, 1)
  const bar = (v: number, color: string, name: string) => (
    <div className="flex items-center gap-3" role="img" aria-label={`${name}: ${v}${unit === '%' ? ' percent' : ''}`}>
      <div className="h-3 flex-1 bg-blotter-dark/40"><div className={`h-full ${color}`} style={{ width: `${(100 * v) / max}%` }} /></div>
      <span className="w-[3.2em] text-right tabular-nums font-bold">{v}{unit === '%' ? '%' : ''}</span>
    </div>
  )
  const better = lowerIsBetter ? blind < normal : blind > normal
  return (
    <div className="grid gap-x-8 gap-y-1 border-t border-dashed border-graphite/40 py-3 md:grid-cols-[1.1fr_1.6fr]">
      <div>
        <p className="font-bold text-ink">{label}</p>
        {note && <p className="text-[13px] leading-5 text-graphite">{note}</p>}
        {better && <p className="mt-0.5 text-[13px] font-bold text-sealed">Blindspot is better</p>}
      </div>
      <div className="space-y-1.5 self-center">
        {bar(normal, 'bg-badger', 'Normal AI service')}
        {bar(blind, 'bg-sealed', 'Blindspot')}
      </div>
    </div>
  )
}

function Legend() {
  return (
    <p className="flex flex-wrap gap-x-6 gap-y-1 text-[13px] text-graphite">
      <span><span aria-hidden className="mr-1.5 inline-block h-2.5 w-5 bg-badger align-middle" />Normal AI service</span>
      <span><span aria-hidden className="mr-1.5 inline-block h-2.5 w-5 bg-sealed align-middle" />Blindspot</span>
    </p>
  )
}

/** One line of the verdict: what a normal service holds against what Blindspot holds, typed on the slip. */
function Verdict({ label, normal, blind, sub }: { label: string; normal: string; blind: string; sub?: string }) {
  return (
    <div className="border-t border-dashed border-graphite/40 py-3">
      <div className="flex items-baseline justify-between gap-4">
        <p className="font-display text-[15px] leading-5 font-bold text-ink">{label}</p>
        <p className="typed shrink-0 text-[20px] leading-6 font-bold tabular-nums">
          <span className="text-badger">{normal}</span><span aria-hidden className="px-2 font-normal text-graphite">/</span><span className="text-sealed">{blind}</span>
        </p>
      </div>
      <p className="typed mt-0.5 flex justify-between gap-4 text-[13.5px] leading-5 text-graphite">
        <span>{sub}</span><span className="shrink-0">normal / Blindspot</span>
      </p>
    </div>
  )
}

/** The numbers behind the receipts, shown above them so a judge sees the verdict first. */
export function Scoreboard({ proof }: { proof?: Proof }) {
  const [card, setCard] = useState<Card | null>(null)
  useEffect(() => {
    let alive = true
    fetch('/api/scorecard').then((r) => (r.ok ? r.json() : null)).then((c) => alive && setCard(c)).catch(() => alive && setCard(null))
    return () => { alive = false }
  }, [])

  // The same hundred made-up patrons as the "Population scenario" tab, after everyone has asked.
  const sim = useMemo(() => {
    const people = makePeople(), tl = tally(makeEvents(people))
    const labelled = new Set<number>()
    const adTargets = new Set<string>()
    people.forEach((p) => p.queries.forEach((q) => {
      if (q.cat >= 0) { labelled.add(p.id); CATS[q.cat].ads.forEach((a) => adTargets.add(`${p.id}|${a}`)) }
    }))
    return { n: people.length, profiled: tl.profiled.size, labelled: labelled.size, named: tl.ident.size, adTargets: adTargets.size, questions: tl.questions }
  }, [])

  const plain = proof?.routes.find((r) => r.route === 'plain')
  const blind = (proof?.routes ?? []).filter((r) => r.route !== 'plain')
  const blindFound = blind.reduce((n, r) => n + r.found.length, 0)
  const blindWords = blind.reduce((n, r) => n + r.words, 0)
  const wire = proof?.recording && plain ? { normal: pct(plain.found.length, plain.words), blind: pct(blindFound, blindWords), n: plain.found.length, w: plain.words, bf: blindFound, bw: blindWords } : null
  const q = card && card.answerable ? card : null
  const top10n = q ? pct(q.top10_float ?? 0, q.retrieval_n ?? 0) : 0
  const top10b = q ? pct(q.top10_int8 ?? 0, q.retrieval_n ?? 0) : 0

  return (
    <section className="mt-10" aria-label="Scoreboard">
      <h3 className="text-[28px] leading-[1.1] font-black tracking-[-0.02em] text-ink sm:text-[34px]">Same answers. Nothing to sell.</h3>
      <p className="mt-2 max-w-[64ch] text-[16px] leading-6 text-graphite">
        Blindspot answered as well as a normal AI service on our test questions. What the library learns about the person asking is where they differ.
      </p>

      <div className="slip typed mt-5 px-6 pt-7 pb-3 sm:px-8" aria-label="The verdict">
        <p className="font-display text-[15px] font-black text-ink">The verdict</p>
        <div className={`grid gap-x-10 ${q ? 'md:grid-cols-2' : ''}`}>
          {q && <Verdict label="Right source in the top 10" normal={`${top10n}%`} blind={`${top10b}%`} sub="Same ranking, rounded to 8-bit numbers" />}
          {q && <Verdict label="Questions answered" normal={`${pct(q.answered ?? 0, q.answerable ?? 0)}%`} blind={`${pct(q.answered ?? 0, q.answerable ?? 0)}%`} sub="Same answer step, on this laptop" />}
          <Verdict label="Patrons a library can profile" normal={`${pct(sim.profiled, sim.n)}%`} blind="0%" sub={`${sim.n} simulated patrons`} />
          <Verdict label="Your words visible on the wire" normal={wire ? `${wire.normal}%` : '...'} blind={wire ? `${wire.blind}%` : '...'}
            sub={wire ? `${wire.n} of ${wire.w} in the clear, ${wire.bf} of ${wire.bw} sealed` : 'Tick the unsealed-copy box and ask to measure this'} />
        </div>
      </div>

      <div className={`mt-5 grid gap-5 ${q ? 'md:grid-cols-2' : ''}`}>
        {q && <div className="receipt typed px-6 pt-5 pb-3 text-[15px] leading-6 text-ink" aria-label="Answer quality">
          <h4 className="font-display text-[18px] font-black">Answer quality</h4>
          <p className="text-[13px] leading-5 text-graphite">{card?.answerable ?? 79} answerable and {card?.should_decline ?? 17} should-decline test questions</p>
          <div className="mt-1"><Legend /></div>
          {(
            <div className="mt-2">
              <Row label="Right source in the top 10" normal={top10n} blind={top10b} />
              <Row label="Answerable questions answered" normal={pct(q.answered ?? 0, q.answerable ?? 0)} blind={pct(q.answered ?? 0, q.answerable ?? 0)} />
              <Row label="Answers citing the expected source" normal={pct(q.cited ?? 0, q.answerable ?? 0)} blind={pct(q.cited ?? 0, q.answerable ?? 0)} />
              <Row label="Out-of-scope questions declined" normal={pct(q.declined ?? 0, q.should_decline ?? 0)} blind={pct(q.declined ?? 0, q.should_decline ?? 0)} />
              <Row label="Wrong answers when it should decline" normal={pct(q.wrong ?? 0, q.should_decline ?? 0)} blind={pct(q.wrong ?? 0, q.should_decline ?? 0)} lowerIsBetter />
            </div>
          )}
          <p className="mt-2 border-t border-dashed border-graphite/40 pt-2 text-[12.5px] leading-[18px] text-graphite">
            Plaintext evaluation. Blindspot's encrypted ranking matched the plaintext int8 ranking on every question checked, so its figures are the int8 ones. A full encrypted run is <span className="font-bold">make bench</span>.
            The questions were written by the team, so one question moves a figure by about 1.3 points.
          </p>
        </div>}

        <div className="receipt typed px-6 pt-5 pb-3 text-[15px] leading-6 text-ink" aria-label="Targeted ads">
          <h4 className="font-display text-[18px] font-black">What a library can sell: targeted ads</h4>
          <p className="text-[13px] leading-5 text-graphite">{sim.n} made-up patrons asked {sim.questions} questions (see the <span className="font-bold">Population scenario</span> tab)</p>
          <div className="mt-1"><Legend /></div>
          <div className="mt-2">
            <Row label="Patrons with a profile on file" normal={pct(sim.profiled, sim.n)} blind={0} />
            <Row label="Patrons with a sensitive label" normal={pct(sim.labelled, sim.n)} blind={0} note="The label ads are aimed from" />
            <Row label="Patrons named from their own words" normal={pct(sim.named, sim.n)} blind={0} note="A name or address typed into a question" />
            <Row label="Ad targets a library could sell" normal={sim.adTargets} blind={0} unit="" note="One per patron and ad" />
          </div>
          <p className="mt-2 border-t border-dashed border-graphite/40 pt-2 text-[12.5px] leading-[18px] text-graphite">
            Simulated: the labels come from a simple keyword rule standing in for real ad tech. Both libraries still log that a request happened, when, and from which address.
          </p>
        </div>
      </div>
    </section>
  )
}
