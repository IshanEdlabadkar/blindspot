import { useEffect, useMemo, useState } from 'react'
import type { Proof } from './api'
import { CATS, makeEvents, makePeople, tally } from './sim'

type Card = {
  retrieval_n?: number; top10_float?: number; top10_int8?: number
  answerable?: number; answered?: number; cited?: number; should_decline?: number; declined?: number; wrong?: number
}

const pct = (n: number, d: number) => (d > 0 ? Math.round((100 * n) / d) : 0)

/** One metric, two bars: a normal AI service against Blind RAG. */
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
        {better && <p className="mt-0.5 text-[13px] font-bold text-sealed">Blind RAG is better here</p>}
      </div>
      <div className="space-y-1.5 self-center">
        {bar(normal, 'bg-badger', 'Normal AI service')}
        {bar(blind, 'bg-sealed', 'Blind RAG')}
      </div>
    </div>
  )
}

function Legend() {
  return (
    <p className="flex flex-wrap gap-x-6 gap-y-1 text-[13px] text-graphite">
      <span><span aria-hidden className="mr-1.5 inline-block h-2.5 w-5 bg-badger align-middle" />Normal AI service</span>
      <span><span aria-hidden className="mr-1.5 inline-block h-2.5 w-5 bg-sealed align-middle" />Blind RAG</span>
    </p>
  )
}

/** Shown under the two receipts: the numbers behind them. */
export function Scoreboard({ proof }: { proof?: Proof }) {
  const [card, setCard] = useState<Card | null>(null)
  useEffect(() => {
    let alive = true
    fetch('/api/scorecard').then((r) => (r.ok ? r.json() : null)).then((c) => alive && setCard(c)).catch(() => alive && setCard(null))
    return () => { alive = false }
  }, [])

  // The same hundred made-up patrons as the "100 people" tab, after everyone has asked.
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

  return (
    <div className="mx-auto mt-16 max-w-[900px]">
      <h2 className="text-[30px] leading-[1.05] font-black tracking-[-0.02em] text-ink sm:text-[40px]">Same answers. Nothing to sell.</h2>
      <p className="mt-3 max-w-[62ch] text-[17px] leading-7 text-graphite">
        On the questions we tested, Blind RAG answers as well as a normal AI service. What a library can learn about the people asking is a different story.
      </p>

      <section className="receipt typed mt-10 px-6 pt-6 pb-4 text-[15px] leading-6 text-ink sm:px-8" aria-label="Answer quality">
        <h3 className="font-display text-[20px] font-black">Answer quality</h3>
        <p className="text-graphite">
          {card?.answerable ?? 79} answerable and {card?.should_decline ?? 17} questions that should be declined, same library.
          Blind RAG uses the same ranking and the same answer step.
        </p>
        <div className="mt-2"><Legend /></div>
        {card && card.answerable ? (
          <div className="mt-3">
            <Row label="Right source in the top 10" normal={pct(card.top10_float ?? 0, card.retrieval_n ?? 0)} blind={pct(card.top10_int8 ?? 0, card.retrieval_n ?? 0)}
              note="Blind RAG searches rounded 8-bit numbers; the only cost is one question" />
            <Row label="Answerable questions answered" normal={pct(card.answered ?? 0, card.answerable)} blind={pct(card.answered ?? 0, card.answerable)} />
            <Row label="Answers citing the expected source" normal={pct(card.cited ?? 0, card.answerable)} blind={pct(card.cited ?? 0, card.answerable)} />
            <Row label="Off-topic or unsafe questions declined" normal={pct(card.declined ?? 0, card.should_decline ?? 0)} blind={pct(card.declined ?? 0, card.should_decline ?? 0)} />
            <Row label="Wrong answers when it should decline" normal={pct(card.wrong ?? 0, card.should_decline ?? 0)} blind={pct(card.wrong ?? 0, card.should_decline ?? 0)} lowerIsBetter />
          </div>
        ) : <p className="mt-3 text-graphite">Quality figures are not available (eval/results is missing).</p>}
        <p className="mt-3 border-t border-dashed border-graphite/40 pt-3 text-[13px] leading-5 text-graphite">
          Measured on the plaintext evaluation. The encrypted ranking matches the plaintext int8 ranking on every question checked, so Blind RAG's figures are the int8 ones;
          a full encrypted run is <span className="font-bold">make bench</span>. Questions were written by the team, not clinicians, so one question moves a figure by about 1.3 points.
        </p>
      </section>

      <section className="receipt typed mt-10 px-6 pt-6 pb-4 text-[15px] leading-6 text-ink sm:px-8" aria-label="Targeted ads">
        <h3 className="font-display text-[20px] font-black">What a library can sell: targeted ads</h3>
        <p className="text-graphite">
          {sim.n} made-up patrons asked {sim.questions} questions (the <span className="font-bold">100 people</span> tab). A typical library reads them and files
          each patron under a topic; ads follow. Blind RAG never sees a question.
        </p>
        <div className="mt-2"><Legend /></div>
        <div className="mt-3">
          <Row label="Patrons with a profile on file" normal={pct(sim.profiled, sim.n)} blind={0} />
          <Row label="Patrons with a sensitive label (health, legal, money)" normal={pct(sim.labelled, sim.n)} blind={0} note="The label ads are aimed from" />
          <Row label="Patrons named from their own words" normal={pct(sim.named, sim.n)} blind={0} note="A name or address typed into a question" />
          <Row label="Ad targets a library could sell" normal={sim.adTargets} blind={0} unit="" note="One per patron and ad, from the labels above" />
        </div>
        <p className="mt-3 border-t border-dashed border-graphite/40 pt-3 text-[13px] leading-5 text-graphite">
          The patrons, questions and labels are simulated, and the labelling is a simple keyword rule standing in for real ad tech.
          Neither library can stop a request being logged; Blind RAG's log holds time and address, not the question.
        </p>
      </section>

      <section className="receipt typed mt-10 px-6 pt-6 pb-4 text-[15px] leading-6 text-ink sm:px-8" aria-label="On the wire">
        <h3 className="font-display text-[20px] font-black">On the wire: your own last question</h3>
        <p className="text-graphite">The recorder searched everything that left this laptop for the words of your question. This one is measured live.</p>
        {proof?.recording && plain ? (
          <>
            <div className="mt-2"><Legend /></div>
            <div className="mt-3">
              <Row label="Words of your question found in the traffic" normal={pct(plain.found.length, plain.words)} blind={pct(blindFound, blindWords)}
                note={`${plain.found.length} of ${plain.words} words in the clear, against ${blindFound} of ${blindWords} when sealed`} />
            </div>
          </>
        ) : (
          <p className="mt-3 text-graphite">Tick the unsealed-copy box on the call slip and ask again to measure this.</p>
        )}
      </section>
    </div>
  )
}
