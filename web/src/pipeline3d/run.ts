import { fmtBytes, type Stage, type Status } from '../api'
import { libraryName, splitAnswer, type Turn } from '../turn'

/** Everything the 3D pipeline view shows, taken from one real question's stream. Nothing here is made up. */
export type SimLibrary = {
  name: string; passages: number; sent: string; fetched: number; found: number | null; words: number
  scoreUp: number; scoreDown: number; fetchUp: number; fetchDown: number
}
export type SimRun = {
  question: string
  stages: Partial<Record<Stage, number>>
  libraries: SimLibrary[]
  words: string[]
  answer: string
  citation: string
  sources: number
  fetchMode: 'pir' | 'download'
  recording: boolean
  chance?: string
  plain?: { bytes: string; found: number; words: number; log?: { time: string; from: string; asked: string; sent: string } }
}

const short = (n: string) => n.replace(/ \(.*\)$/, '').replace(/^Federal /, '')

export function toRun(turn: Turn, status: Status | null): SimRun {
  const servers = turn.trace?.servers ?? []
  const routes = turn.proof?.routes ?? []
  const blind = routes.filter((r) => r.route !== 'plain')
  const plain = routes.find((r) => r.route === 'plain')
  const libraries = servers.map((x, i) => {
    const name = short(status?.servers.find((s) => s.url === x.server)?.name ?? x.server)
    const r = blind.find((b) => libraryName(b.route) === name) ?? blind[i]
    const score = x.requests.filter((q) => q.endpoint === '/v1/score')
    const fetch = x.requests.filter((q) => q.endpoint.startsWith('/v1/fetch'))
    const sum = (list: typeof x.requests, k: 'request_bytes' | 'response_bytes') => list.reduce((n, q) => n + q[k], 0)
    return {
      name, passages: x.num_chunks, fetched: x.fetched,
      sent: fmtBytes(sum(score, 'request_bytes')),
      scoreUp: sum(score, 'request_bytes'), scoreDown: sum(score, 'response_bytes'),
      fetchUp: sum(fetch, 'request_bytes'), fetchDown: sum(fetch, 'response_bytes'),
      found: r ? r.found.length : null, words: r?.words ?? turn.proof?.words.length ?? 0,
    }
  })
  const res = turn.result
  const e = turn.plain?.entry
  return {
    question: turn.question,
    stages: turn.stages,
    libraries,
    words: turn.proof?.words ?? [],
    answer: res ? splitAnswer(res).body.replace(/\s*\[\d+\]/g, '').trim() : '',
    citation: res?.citations[0]?.title.replace(/\.+$/, '') ?? '',
    sources: res?.citations.length ?? 0,
    fetchMode: turn.trace?.mode?.fetch === 'download' ? 'download' : 'pir',
    recording: Boolean(turn.proof?.recording),
    chance: blind.length ? Math.max(...blind.map((r) => r.chance_by_luck)).toExponential(0) : undefined,
    plain: turn.compare && (plain || e) ? {
      bytes: plain ? fmtBytes(plain.bytes) : '', found: plain?.found.length ?? 0, words: plain?.words ?? 0,
      log: e ? {
        time: Number.isNaN(Date.parse(e.time)) ? e.time : new Date(e.time).toLocaleTimeString(),
        from: e.client, asked: e.question, sent: [...new Set(e.returned.map((x) => x.title))].join('; '),
      } : undefined,
    } : undefined,
  }
}
