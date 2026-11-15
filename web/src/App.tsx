import { useCallback, useEffect, useState } from 'react'
import { getStatus, type Status } from './api'
import { Burrow } from './Burrow'
import { Libraries } from './Libraries'
import { Workspace } from './Workspace'
function Health({ status }: { status: Status | null }) {
  if (!status) return <span className="text-sm text-graphite">Connecting</span>
  const up = status.servers.filter((s) => s.ok).length
  const ok = up === status.servers.length && status.helper && status.model
  const issues = [
    up < status.servers.length && `${status.servers.length - up} offline`,
    !status.helper && 'key helper off', !status.model && 'local model off',
  ].filter(Boolean).join(', ')
  return (
    <span className={`text-sm ${ok ? 'text-graphite' : 'font-medium text-stamp'}`} title={issues || 'All systems ready'}>
      <span className="hidden sm:inline">{up} of {status.servers.length} libraries open{issues ? `, ${issues}` : ''}</span>
      <span className="sm:hidden">{issues ? `${up}/${status.servers.length} open, check` : ''}</span>
    </span>
  )
}

type Mode = 'chat' | 'demo'

export default function App() {
  const [status, setStatus] = useState<Status | null>(null)
  const [mode, setModeRaw] = useState<Mode>(() => (location.hash === '#demo' ? 'demo' : 'chat'))
  const [homeTick, setHomeTick] = useState(0)
  const [disabled, setDisabledRaw] = useState<Set<string>>(() => {
    try { return new Set<string>(JSON.parse(localStorage.getItem('blindspot.disabled') ?? '[]')) } catch { return new Set<string>() }
  })
  const setDisabled = (s: Set<string>) => {
    setDisabledRaw(s)
    try { localStorage.setItem('blindspot.disabled', JSON.stringify([...s])) } catch { /* private mode */ }
  }
  const toggle = (u: string) => {
    const servers = status?.servers ?? []
    const next = new Set(disabled)
    if (next.has(u)) next.delete(u)
    else if (servers.filter((s) => !next.has(s.url)).length > 1) next.add(u)   // always keep one library on
    setDisabled(next)
  }
  const setMode = (m: Mode) => { setModeRaw(m); history.replaceState(null, '', m === 'demo' ? '#demo' : location.pathname); window.scrollTo({ top: 0 }) }
  const refresh = useCallback(() => { void getStatus().then(setStatus).catch(() => setStatus(null)) }, [])
  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 5000)
    return () => clearInterval(t)
  }, [refresh])

  return (
    <div className="desk relative min-h-dvh">
      <header className="relative z-30 mx-auto flex h-16 max-w-[1120px] items-center justify-between gap-3 px-4 whitespace-nowrap sm:px-5">
        <button aria-label="Blindspot, back to the start" onClick={() => setHomeTick((n) => n + 1)} className="flex items-center gap-2 font-display text-[20px] font-black tracking-[-0.02em] text-ink">
          <Burrow size={32} mood="peek" /> <span className="hidden sm:inline">Blindspot</span>
        </button>
        <div role="tablist" aria-label="Mode" className="inline-flex overflow-hidden rounded-[2px] border-2 border-ink font-display text-[14px] font-bold">
          {([['chat', 'Chat'], ['demo', 'Live demo']] as const).map(([k, label]) => (
            <button key={k} role="tab" aria-selected={mode === k} onClick={() => setMode(k)}
              className={`h-9 px-4 sm:px-5 ${mode === k ? 'bg-ink text-card' : 'text-ink hover:bg-ink/10'}`}>{label}</button>
          ))}
        </div>
        <div className="flex items-center gap-3 sm:gap-5">
          <Libraries status={status} disabled={disabled} setDisabled={setDisabled} refresh={refresh} />
          <Health status={status} />
        </div>
      </header>
      <div className={mode === 'chat' ? '' : 'hidden'}><Workspace mode="chat" status={status} disabled={disabled} toggle={toggle} homeTick={homeTick} /></div>
      <div className={mode === 'demo' ? '' : 'hidden'}><Workspace mode="demo" status={status} disabled={disabled} toggle={toggle} homeTick={homeTick} /></div>
    </div>
  )
}
