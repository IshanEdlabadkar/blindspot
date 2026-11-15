import type { ApiError, Plain, Proof, Result, Stage, Trace } from './api'

export type Turn = {
  id: number
  question: string
  since?: string
  stages: Partial<Record<Stage, number>>
  result?: Result
  trace?: Trace
  plain?: Plain
  proof?: Proof
  error?: ApiError
  phase: 'working' | 'answered' | 'done' | 'error'
}

export const STAGES: { key: Stage; label: string }[] = [
  { key: 'embedding', label: 'Reading your question on this laptop' },
  { key: 'encrypting', label: 'Locking it before it leaves' },
  { key: 'scoring', label: 'Libraries searching without reading it' },
  { key: 'fetching', label: 'Fetching passages without saying which' },
  { key: 'answering', label: 'Writing the answer on this laptop' },
]

// Wiretap route ids and server sources -> names people recognise.
export const LIBRARY: Record<string, string> = {
  medlineplus: 'MedlinePlus',
  fmla: 'FMLA regulations',
  genetics: 'MedlinePlus Genetics',
  myhealthfinder: 'MyHealthfinder',
  plain: 'A normal AI service',
}

export const libraryName = (id: string, fallback?: string) => LIBRARY[id] ?? fallback ?? id

/** answer() puts the urgent notice first and the disclaimer last; split them out for display. */
export function splitAnswer(r: Result): { body: string; disclaimer: string } {
  let text = r.answer.trim()
  if (r.urgent && text.startsWith(r.urgent.message)) text = text.slice(r.urgent.message.length).trim()
  const parts = text.split(/\n\n+/)
  const last = parts[parts.length - 1] ?? ''
  if (parts.length > 1 && /not (medical|legal)|medical or legal advice/i.test(last)) {
    return { body: parts.slice(0, -1).join('\n\n'), disclaimer: last }
  }
  return { body: text, disclaimer: '' }
}
