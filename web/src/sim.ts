// A hundred made-up patrons asking sensitive questions, for the "100 people" tab.
// Everything here is synthetic: names, questions, addresses, sealed requests. Ad labels come from a plain
// word-matching rule, a stand-in for real ad tech, not a claim about how any real company profiles people.

export type Cat = { id: string; label: string; segment: string; guess: string; ads: string[]; kw: string[]; queries: string[] }
export type Query = { text: string; cat: number; ident: boolean } // cat -1 = no sensitive topic matched
export type Person = { id: number; tag: string; name: string; age: number | null; ip: string; cookie: string; queries: Query[]; you?: boolean }
export type SimEvent = { n: number; t: number; pid: number; q: Query; k: number }

export const CATS: Cat[] = [
  { id: 'repro', label: 'Pregnancy and reproductive health', segment: 'Expecting or fertility concern', guess: 'possible pregnancy or complication',
    ads: ['Prenatal vitamins, 20% off', 'Fertility clinic: free consult', 'Baby registry bonus'],
    kw: ['miscarriage', 'pregnan', 'prenatal', 'spotting', 'fertility', 'fmla'],
    queries: ['What are early signs of a miscarriage?', 'Can I take FMLA leave for a pregnancy complication?', 'Is spotting at 8 weeks normal?', "Options if I can't afford prenatal care"] },
  { id: 'mental', label: 'Mental health', segment: 'Mental health concern', guess: 'possible depression or anxiety',
    ads: ['Online therapy, first week free', 'Anxiety relief supplements', 'Meditation app trial'],
    kw: ['depress', 'anxiety', 'panic', 'counsel', 'therapy', 'suicid'],
    queries: ['How do I know if I have depression?', 'Signs of a panic attack vs a heart attack', 'Free counseling for students near campus', 'Can anxiety medication affect my job?'] },
  { id: 'immig', label: 'Immigration', segment: 'Immigration status concern', guess: 'visa or status uncertainty',
    ads: ['Immigration attorney near you', 'Visa fee loan', 'Cheap international transfers'],
    kw: ['immigra', 'visa', 'green card', 'deport', 'citizen'],
    queries: ['Can immigration authorities access campus counseling records?', "What happens if my visa expires while I'm in the U.S.?", 'Do I need a lawyer for a green card interview?'] },
  { id: 'tenant', label: 'Housing and tenant law', segment: 'Eviction risk', guess: 'housing instability',
    ads: ['Tenant rights lawyer', 'Mold remediation quote', 'Same-day movers'],
    kw: ['evict', 'landlord', 'lease', 'mold', 'tenant'],
    queries: ['Can my landlord evict me for reporting mold?', 'How long does an eviction take?', 'Can I break my lease if the unit is unsafe?'] },
  { id: 'sti', label: 'Sexual health', segment: 'Sexual health concern', guess: 'possible STI exposure',
    ads: ['At-home STD test kit', 'Telehealth PrEP clinic', 'Discreet delivery pharmacy'],
    kw: ['hiv', 'chlamydia', 'std', 'sti ', 'tested'],
    queries: ['Where to get tested for HIV confidentially', 'Symptoms of chlamydia in men', 'Does insurance bill show STI tests?'] },
  { id: 'subst', label: 'Substance use', segment: 'Substance use concern', guess: 'possible dependence',
    ads: ['Rehab center admissions', 'Sober coaching app', 'Recovery meetup finder'],
    kw: ['alcohol', 'opioid', 'withdrawal', 'addict', 'taper', 'rehab'],
    queries: ['How to taper off alcohol safely', 'Signs of opioid withdrawal', 'Confidential addiction treatment options'] },
  { id: 'chron', label: 'Chronic illness', segment: 'Chronic condition patient', guess: 'possible diabetes or autoimmune disease',
    ads: ['Glucose monitor trial', 'Specialty pharmacy transfer', 'Health insurance quotes'],
    kw: ['diabet', 'lupus', 'chest', 'flare', 'insulin'],
    queries: ['Early signs of type 2 diabetes', 'Managing lupus flare-ups', 'Is chest tightness after exercise serious?'] },
  { id: 'cancer', label: 'Cancer', segment: 'Cancer concern', guess: 'possible cancer scare or diagnosis',
    ads: ['Oncology second opinion', 'Cancer insurance plan', 'Wigs and support products'],
    kw: ['cancer', 'lump', 'colonoscopy', 'tumor', 'stage 2', 'biopsy'],
    queries: ['Lump in breast, what should I do?', 'Colonoscopy prep: what to expect', 'Survival rates after a stage 2 diagnosis'] },
  { id: 'harass', label: 'Harassment and work', segment: 'Workplace conflict risk', guess: 'possible harassment, may change jobs',
    ads: ['Employment law attorney', 'Job board: new roles near you', 'Evidence documentation app'],
    kw: ['harass', 'title ix', 'retaliat', 'boss'],
    queries: ['How do I report harassment confidentially?', 'Does a Title IX report notify my professor?', 'Can my boss retaliate for reporting?'] },
  { id: 'debt', label: 'Money and debt', segment: 'Financial distress', guess: 'financial hardship',
    ads: ['Debt consolidation loan', 'Payday advance app', 'Credit repair service'],
    kw: ['debt', 'payday', 'loan', 'miss rent', 'medical bill', 'forgive'],
    queries: ['Can I get medical debt forgiven?', 'What happens if I miss rent and a car payment?', 'Payday loan alternatives'] },
]
export const GENERAL = { label: 'No sensitive topic', segment: 'General browser', guess: 'nothing sensitive', ads: ['Coupon aggregator', 'Streaming trial', 'Generic display ads'] }
export const catOf = (q: Query) => (q.cat < 0 ? GENERAL : CATS[q.cat])

const IDENT = [" (I'm a nurse at St. Mary's)", ' (I live on Willow St)', ' (my manager is Dave at Ironwood Logistics)', ' (my name is on the lease: J. Patel)']
const IDENT_RE = /\bI live\b|\bmy name\b|\bI work at\b|\bI'm an? \w+ at\b|\bmy (boss|manager|landlord) is\b|\d+\s+\w+\s+(st|street|ave|avenue|rd)\b|\bon the lease\b|\bmy employer\b/i
const NAMES = ['Ava', 'Ben', 'Chloe', 'Dev', 'Elena', 'Femi', 'Grace', 'Hiro', 'Ines', 'Jamal', 'Kira', 'Luis', 'Maya', 'Noah', 'Omar', 'Priya', 'Quinn', 'Rosa', 'Sam', 'Tara', 'Uma', 'Vik', 'Wen', 'Xavier', 'Yara', 'Zane']

export function rng(seed: number) {
  let a = seed | 0
  return () => {
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}
export const hex = (r: () => number, n: number) => Array.from({ length: n }, () => '0123456789abcdef'[Math.floor(r() * 16)]).join('')

export function makePeople(seed = 2026): Person[] {
  const r = rng(seed)
  const pick = <T,>(a: T[]) => a[Math.floor(r() * a.length)]
  return Array.from({ length: 100 }, (_, i) => {
    const nq = r() < 0.55 ? 1 : r() < 0.62 ? 2 : 3
    const first = Math.floor(r() * CATS.length)
    const queries: Query[] = []
    for (let k = 0; k < nq; k++) {
      const cat = k === 0 ? first : r() < 0.6 ? first : Math.floor(r() * CATS.length)
      let text = pick(CATS[cat].queries)
      let ident = false
      if (k === 0 && r() < 0.1) { text += pick(IDENT); ident = true }
      queries.push({ text, cat, ident })
    }
    return { id: i, tag: `P${String(i + 1).padStart(3, '0')}`, name: pick(NAMES), age: 18 + Math.floor(r() * 52),
      ip: `${['192.0.2', '198.51.100', '203.0.113'][i % 3]}.${10 + (Math.floor(i / 3) % 240)}`, cookie: `c${hex(r, 7)}`, queries }
  })
}

/** When each question is handed in, in milliseconds from the start. People arrive about 130 ms apart; a person's later questions follow seconds after. */
export function makeEvents(people: Person[], seed = 2027): SimEvent[] {
  const r = rng(seed)
  const out: Omit<SimEvent, 'n'>[] = []
  people.forEach((p, i) => {
    let t = i * 130 + Math.floor(r() * 100)
    p.queries.forEach((q, k) => { if (k > 0) t += 1500 + Math.floor(r() * 2500); out.push({ t, pid: p.id, q, k }) })
  })
  return out.sort((a, b) => a.t - b.t).map((e, n) => ({ ...e, n }))
}

export function classify(text: string): Query {
  const t = text.toLowerCase()
  let best = -1, score = 0
  CATS.forEach((c, i) => { const s = c.kw.filter((k) => t.includes(k)).length; if (s > score) { score = s; best = i } })
  return { text, cat: best, ident: IDENT_RE.test(text) }
}

export function clock(t: number) {
  const s = Math.floor(t / 1000)
  return `14:${String(Math.floor(s / 60) % 60).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}

export type Tally = { questions: number; profiled: Set<number>; ident: Set<number>; bySeg: Map<number, Set<number>>; labels: number; requests: number }
export function tally(events: SimEvent[]): Tally {
  const profiled = new Set<number>(), ident = new Set<number>(), bySeg = new Map<number, Set<number>>()
  for (const e of events) {
    profiled.add(e.pid)
    if (e.q.ident) ident.add(e.pid)
    if (e.q.cat >= 0) bySeg.set(e.q.cat, (bySeg.get(e.q.cat) ?? new Set()).add(e.pid))
  }
  let labels = 0
  bySeg.forEach((s) => { labels += s.size })
  return { questions: events.length, profiled, ident, bySeg, labels, requests: events.length * 2 }
}
