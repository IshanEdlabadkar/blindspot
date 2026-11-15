import { useEffect, useRef, useState } from 'react'
import { addServer, removeServer, type Status } from './api'
import { short } from './Chat'

/** The libraries (document servers) Blindspot can search: choose which ones a question goes to, add one by its address, or remove one. */
export function Libraries({ status, disabled, setDisabled, refresh }: {
  status: Status | null; disabled: Set<string>; setDisabled: (s: Set<string>) => void; refresh: () => void
}) {
  const [open, setOpen] = useState(false)
  const [url, setUrl] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const servers = status?.servers ?? []
  const on = servers.filter((s) => !disabled.has(s.url)).length

  useEffect(() => {
    if (!open) return
    const click = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false) }
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', click); document.addEventListener('keydown', key)
    return () => { document.removeEventListener('mousedown', click); document.removeEventListener('keydown', key) }
  }, [open])

  const toggle = (u: string) => {
    const next = new Set(disabled)
    if (next.has(u)) next.delete(u)
    else if (servers.filter((s) => !next.has(s.url)).length > 1) next.add(u)
    setDisabled(next)
  }
  const add = async () => {
    const v = url.trim()
    if (!v || busy) return
    setBusy(true); setErr('')
    try { await addServer(v); setUrl(''); refresh() } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  const remove = async (u: string) => {
    setErr('')
    try { await removeServer(u); refresh() } catch (e) { setErr((e as Error).message) }
  }

  return (
    <div className="relative" ref={box}>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-haspopup="dialog"
        className="text-sm text-ink underline decoration-graphite/50 underline-offset-4 hover:decoration-badger">
        Libraries{status ? ` (${on} of ${servers.length})` : ''}
      </button>
      {open && (
        <div role="dialog" aria-label="Libraries" className="slip typed absolute top-9 right-0 z-30 w-[min(440px,calc(100vw-2.5rem))] px-5 pt-6 pb-5 text-[15px] leading-6 text-ink">
          <p className="font-display font-black">Libraries</p>
          <p className="text-graphite">Pick which ones your question goes to. Each searches its own documents without reading your question.</p>
          <ul className="mt-3 space-y-2">
            {servers.map((s) => (
              <li key={s.url} className="flex items-start gap-2.5">
                <input id={`lib-${s.url}`} type="checkbox" checked={!disabled.has(s.url)} onChange={() => toggle(s.url)} className="mt-1.5 size-4 accent-[#1E1C1A]" />
                <label htmlFor={`lib-${s.url}`} className="min-w-0 flex-1 cursor-pointer">
                  <span className={s.ok ? '' : 'text-graphite line-through'}>{short(s.name)}</span>
                  <span className="block truncate text-[13px] leading-5 text-graphite">
                    {s.ok ? `${(s.num_chunks ?? 0).toLocaleString()} passages` : 'offline'} · {s.url.replace(/^https?:\/\//, '')}
                  </span>
                </label>
                <button type="button" onClick={() => void remove(s.url)} disabled={servers.length < 2} aria-label={`Remove ${short(s.name)}`}
                  className="text-[13px] text-stamp underline underline-offset-4 disabled:opacity-40">Remove</button>
              </li>
            ))}
          </ul>
          <form className="mt-4 border-t border-dashed border-graphite/40 pt-3" onSubmit={(e) => { e.preventDefault(); void add() }}>
            <label htmlFor="new-lib" className="font-bold">Add a library</label>
            <div className="mt-1 flex gap-2">
              <input id="new-lib" value={url} onChange={(e) => { setUrl(e.target.value); setErr('') }} placeholder="https://your-server.example.com"
                className="typed h-10 min-w-0 flex-1 border-b-2 border-ink bg-transparent px-1 text-[15px] placeholder:text-graphite/70 focus:outline-none" />
              <button disabled={!url.trim() || busy} className="press h-10 rounded-[2px] bg-ink px-4 font-display text-sm font-bold text-card disabled:opacity-50">
                {busy ? 'Checking' : 'Add'}
              </button>
            </div>
            <p className="text-[13px] leading-5 text-graphite">Any Blindspot document server: medical, legal, company wiki, anything you can index.</p>
            {err && <p role="alert" className="mt-1 text-[14px] leading-5 text-stamp">{err}</p>}
          </form>
          <p className="mt-3 text-[13px] leading-5 text-graphite">
            Searching fewer libraries tells anyone watching the network which ones you care about. Keep them all ticked to hide that.
          </p>
        </div>
      )}
    </div>
  )
}
