import { useCallback, useLayoutEffect, useRef, useState } from 'react'

/* Library things lying on the desk, drawn flat in ink from the page palette.
   They are scattered at random on each view, only on empty desk: never over text, a slip, a card or the receipt. */

const INK = '#1E1C1A'
const COVERS = ['#C5050C', '#23408E', '#3E6B4F', '#6B2A20', '#2F2B28']
const BOOKS = [
  ['Field Guide to', 'Badgers', '599.76 BAD'],
  ['Federal', 'Register', '342.06 FED'],
  ['Human', 'Genetics', '576.5 GEN'],
  ['Family', 'Health', '613 FAM'],
  ['Applied', 'Cryptography', '005.82 CRY'],
  ['Wisconsin', 'Lakes', '551.48 WIS'],
]
const pick = <T,>(a: T[]) => a[Math.floor(Math.random() * a.length)]

type Draw = { w: number; h: number; spin: number; max: number; shadow?: boolean; svg: (v: number) => React.ReactNode }

const OBJECTS: Record<string, Draw> = {
  pencil: { w: 150, h: 20, spin: 70, max: 2, svg: () => (
    <svg viewBox="0 0 150 20">
      <rect x="18" y="3" width="118" height="14" fill="#E9B949" stroke={INK} strokeWidth="1.2" />
      <line x1="18" y1="10" x2="136" y2="10" stroke="#C99A2E" strokeWidth=".8" />
      <text x="34" y="9" fontFamily="Courier Prime" fontSize="5.5" fill="#5A3E1B">BLIND RAG LIBRARY  No. 2</text>
      <rect x="136" y="3" width="6" height="14" fill="#A7ADB3" stroke={INK} strokeWidth="1.2" />
      <rect x="142" y="3" width="7" height="14" rx="2" fill="#E58A8A" stroke={INK} strokeWidth="1.2" />
      <path d="M18 3 L2 10 L18 17 Z" fill="#E8C9A0" stroke={INK} strokeWidth="1.2" strokeLinejoin="round" />
      <path d="M7 7.8 L2 10 L7 12.2 Z" fill="#3A3633" />
    </svg>) },
  clip: { w: 22, h: 64, spin: 60, max: 2, svg: () => (
    <svg viewBox="0 0 22 64">
      <path d="M7 20 V50 a4 4 0 0 0 8 0 V12 a7 7 0 0 0 -14 0 V52 a10 10 0 0 0 20 0 V18" fill="none" stroke="#7F868D" strokeWidth="2.2" strokeLinecap="round" />
    </svg>) },
  stamp: { w: 56, h: 76, spin: 25, max: 1, svg: () => (
    <svg viewBox="0 0 56 76">
      <ellipse cx="28" cy="14" rx="14" ry="12" fill="#A0703F" stroke={INK} strokeWidth="1.4" />
      <ellipse cx="24" cy="10" rx="5" ry="3" fill="#C99B68" />
      <rect x="23" y="24" width="10" height="21" fill="#8A5F35" stroke={INK} strokeWidth="1.4" />
      <rect x="6" y="44" width="44" height="20" rx="2" fill="#A0703F" stroke={INK} strokeWidth="1.4" />
      <text x="28" y="57" textAnchor="middle" fontFamily="Courier Prime" fontSize="8" fontWeight="700" fill="#3A2412">DATE</text>
      <rect x="8" y="64" width="40" height="6" fill="#4E3784" stroke={INK} strokeWidth="1.4" />
    </svg>) },
  inkpad: { w: 96, h: 62, spin: 25, max: 1, svg: () => (
    <svg viewBox="0 0 96 62">
      <rect x="2" y="2" width="92" height="58" rx="6" fill="#6E6E73" stroke={INK} strokeWidth="1.4" />
      <rect x="9" y="9" width="78" height="44" rx="3" fill="#4E3784" stroke={INK} strokeWidth="1" />
      <path d="M14 14 h40" stroke="#7A64B0" strokeWidth="3" strokeLinecap="round" opacity=".6" />
    </svg>) },
  book: { w: 108, h: 148, spin: 30, max: 3, svg: (v) => {
    const [a, b, call] = BOOKS[v % BOOKS.length]
    const c = COVERS[(v * 7) % COVERS.length]
    return (
      <svg viewBox="0 0 108 148">
        <rect x="6" y="5" width="100" height="141" rx="2" fill="#EFE6CF" stroke={INK} strokeWidth="1.2" />
        <rect x="2" y="2" width="100" height="140" rx="2" fill={c} stroke={INK} strokeWidth="1.4" />
        <rect x="2" y="2" width="13" height="140" fill="#000" opacity=".22" />
        <rect x="26" y="26" width="64" height="38" fill="#FFFDF8" stroke={INK} strokeWidth="1" />
        <text x="58" y="42" textAnchor="middle" fontFamily="Red Hat Display" fontWeight="700" fontSize="8.5" fill={INK}>{a}</text>
        <text x="58" y="55" textAnchor="middle" fontFamily="Red Hat Display" fontWeight="900" fontSize="10" fill={INK}>{b}</text>
        <rect x="58" y="116" width="38" height="18" fill="#FFFDF8" stroke={INK} strokeWidth="1" />
        <text x="77" y="128" textAnchor="middle" fontFamily="Courier Prime" fontSize="6.5" fill={INK}>{call}</text>
      </svg>)
  } },
  openbook: { w: 196, h: 128, spin: 18, max: 1, svg: (v) => (
    <svg viewBox="0 0 196 128">
      <rect x="2" y="6" width="192" height="120" rx="3" fill={COVERS[v % COVERS.length]} stroke={INK} strokeWidth="1.4" />
      <path d="M98 12 C78 4 34 6 8 12 V120 C34 114 78 112 98 120 Z" fill="#FFFDF8" stroke={INK} strokeWidth="1.2" />
      <path d="M98 12 C118 4 162 6 188 12 V120 C162 114 118 112 98 120 Z" fill="#FBF6E9" stroke={INK} strokeWidth="1.2" />
      <path d="M98 12 V120" stroke={INK} strokeWidth="1.2" />
      <rect x="92" y="12" width="6" height="108" fill="#000" opacity=".08" />
      {Array.from({ length: 9 }, (_, i) => <g key={i} stroke="#B9B2A4" strokeWidth="1.2">
        <path d={`M18 ${28 + i * 10} H${i === 8 ? 58 : 86}`} /><path d={`M110 ${28 + i * 10} H${i === 4 ? 140 : 178}`} />
      </g>)}
    </svg>) },
  glasses: { w: 112, h: 58, spin: 40, max: 1, svg: () => (
    <svg viewBox="0 0 112 58">
      <path d="M8 18 L2 54 M104 18 L110 54" stroke={INK} strokeWidth="2.6" strokeLinecap="round" />
      <circle cx="30" cy="28" r="21" fill="#DCE8F2" fillOpacity=".45" stroke={INK} strokeWidth="3" />
      <circle cx="82" cy="28" r="21" fill="#DCE8F2" fillOpacity=".45" stroke={INK} strokeWidth="3" />
      <path d="M51 25 Q56 19 61 25" fill="none" stroke={INK} strokeWidth="3" strokeLinecap="round" />
      <path d="M20 18 Q26 13 33 15 M72 18 Q78 13 85 15" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" fill="none" />
    </svg>) },
  lens: { w: 70, h: 132, spin: 50, max: 1, svg: () => (
    <svg viewBox="0 0 70 132">
      <rect x="29" y="58" width="12" height="70" rx="5" fill="#6B3A1E" stroke={INK} strokeWidth="1.4" />
      <rect x="27" y="56" width="16" height="10" fill="#A7ADB3" stroke={INK} strokeWidth="1.2" />
      <circle cx="35" cy="32" r="28" fill="#DCE8F2" fillOpacity=".5" stroke="#2B2826" strokeWidth="5" />
      <path d="M20 22 Q26 13 36 12" stroke="#fff" strokeWidth="3" strokeLinecap="round" fill="none" />
    </svg>) },
  band: { w: 64, h: 26, spin: 90, max: 2, shadow: false, svg: () => (
    <svg viewBox="0 0 64 26">
      <path d="M8 13 C8 4 56 2 58 11 C60 21 10 24 8 13 Z" fill="none" stroke="#C98B5A" strokeWidth="2.4" />
    </svg>) },
  ring: { w: 92, h: 92, spin: 180, max: 1, shadow: false, svg: () => (
    <svg viewBox="0 0 92 92">
      <ellipse cx="46" cy="46" rx="37" ry="35" fill="#7A4E25" fillOpacity=".05" />
      <path d="M46 10 C68 10 84 26 83 47 C82 68 66 82 45 82 C25 82 9 67 10 46 C11 26 25 10 46 10 Z" fill="none" stroke="#7A4E25" strokeOpacity=".2" strokeWidth="3.5" />
      <path d="M20 66 C30 79 58 84 74 70" fill="none" stroke="#7A4E25" strokeOpacity=".18" strokeWidth="6" strokeLinecap="round" />
      <path d="M48 14 C66 15 78 28 79 44" fill="none" stroke="#7A4E25" strokeOpacity=".1" strokeWidth="1.5" />
    </svg>) },
  duecard: { w: 112, h: 150, spin: 25, max: 1, svg: () => (
    <svg viewBox="0 0 112 150">
      <rect x="1" y="1" width="110" height="148" fill="#FFFDF8" stroke={INK} strokeWidth="1" />
      <text x="56" y="18" textAnchor="middle" fontFamily="Red Hat Display" fontWeight="900" fontSize="10" fill={INK}>DATE DUE</text>
      <path d="M6 24 H106" stroke="#C5050C" strokeWidth="1.6" />
      {Array.from({ length: 8 }, (_, i) => <path key={i} d={`M6 ${40 + i * 14} H106`} stroke="#A9C0DA" strokeWidth="1" />)}
      <path d="M56 24 V144" stroke="#A9C0DA" strokeWidth="1" />
      {['OCT 02', 'OCT 23', 'NOV 06'].map((d, i) => (
        <text key={d} x={i === 1 ? 82 : 30} y={37 + i * 14} textAnchor="middle" fontFamily="Courier Prime" fontWeight="700" fontSize="9" fill="#4E3784"
          transform={`rotate(${[-4, 3, -2][i]} ${i === 1 ? 82 : 30} ${37 + i * 14})`} opacity=".85">{d}</text>
      ))}
    </svg>) },
  tabs: { w: 140, h: 104, spin: 20, max: 1, svg: () => (
    <svg viewBox="0 0 140 104">
      {['A', 'M', 'Z'].map((l, i) => (
        <g key={l} transform={`translate(${i * 4} ${16 - i * 7})`}>
          <path d={`M2 14 H${14 + i * 36} V2 H${44 + i * 36} V14 H130 V86 H2 Z`} fill={['#F3EEDC', '#FFFDF8', '#F3EEDC'][i]} stroke={INK} strokeWidth="1" />
          <text x={29 + i * 36} y="11.5" textAnchor="middle" fontFamily="Courier Prime" fontWeight="700" fontSize="9" fill={INK}>{l}</text>
        </g>
      ))}
    </svg>) },
}

type Placed = { id: number; kind: string; v: number; x: number; y: number; w: number; h: number; rot: number; box: DOMRect }

const CLEAR = 'header, h1, h2, main p, main ul, main ol, label, button, form, .slip, .catalog, .receipt, img, [data-clear]'

export function DeskObjects({ viewKey, version }: { viewKey: string; version: string }) {
  const layer = useRef<HTMLDivElement>(null)
  const [items, setItems] = useState<Placed[]>([])
  const current = useRef<Placed[]>([])
  const nextId = useRef(0)
  const lastView = useRef('')

  const place = useCallback((reset: boolean) => {
    const el = layer.current
    const root = el?.parentElement
    if (!el || !root) return
    const origin = root.getBoundingClientRect()
    const W = root.clientWidth
    const H = root.scrollHeight
    const narrow = W < 640
    const pad = narrow ? 10 : 18
    const blocked: DOMRect[] = []
    root.querySelectorAll<HTMLElement>(CLEAR).forEach((n) => {
      if (n.closest('[data-fixed]') || el.contains(n)) return
      const r = n.getBoundingClientRect()
      if (r.width && r.height) blocked.push(new DOMRect(r.left - origin.left - pad, r.top - origin.top - pad, r.width + pad * 2, r.height + pad * 2))
    })
    const hits = (a: DOMRect, b: DOMRect) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top
    const inside = (b: DOMRect) => b.top >= 0 && b.bottom <= H && b.left > -b.width * 0.4 && b.right < W + b.width * 0.4

    const keep = reset ? [] : current.current.filter((p) => inside(p.box) && !blocked.some((b) => hits(b, p.box)))
    const target = narrow ? Math.max(2, Math.min(5, Math.round((W * H) / 160000))) : Math.max(4, Math.min(14, Math.round((W * H) / 190000)))
    const used: Record<string, number> = {}
    keep.forEach((p) => { used[p.kind] = (used[p.kind] ?? 0) + 1 })
    const out = [...keep]
    let guard = 0
    while (out.length < target && guard++ < 40) {
      const kinds = Object.keys(OBJECTS).filter((k) => (used[k] ?? 0) < OBJECTS[k].max)
      if (!kinds.length) break
      const kind = pick(kinds)
      const o = OBJECTS[kind]
      const s = (narrow ? 0.62 : 0.85) + Math.random() * 0.25
      const w = o.w * s, h = o.h * s
      const rot = (Math.random() * 2 - 1) * o.spin
      const rad = (rot * Math.PI) / 180
      const bw = Math.abs(w * Math.cos(rad)) + Math.abs(h * Math.sin(rad))
      const bh = Math.abs(w * Math.sin(rad)) + Math.abs(h * Math.cos(rad))
      for (let t = 0; t < 70; t++) {
        const cx = -bw * 0.3 + Math.random() * (W + bw * 0.6)
        const cy = bh / 2 + Math.random() * Math.max(H - bh, 1)
        const box = new DOMRect(cx - bw / 2, cy - bh / 2, bw, bh)
        if (!inside(box) || blocked.some((b) => hits(b, box)) || out.some((p) => hits(p.box, box))) continue
        out.push({ id: nextId.current++, kind, v: Math.floor(Math.random() * 60), x: cx - w / 2, y: cy - h / 2, w, h, rot, box })
        used[kind] = (used[kind] ?? 0) + 1
        break
      }
    }
    current.current = out
    setItems(out)
  }, [])

  // New view: lay out fresh. Same view, more content: keep what still fits and fill new empty space.
  useLayoutEffect(() => {
    const reset = lastView.current !== viewKey
    lastView.current = viewKey
    const a = requestAnimationFrame(() => place(reset))
    const b = setTimeout(() => place(false), 500)
    return () => { cancelAnimationFrame(a); clearTimeout(b) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewKey, version])

  useLayoutEffect(() => {
    let t = 0
    const onResize = () => { clearTimeout(t); t = window.setTimeout(() => place(true), 200) }
    window.addEventListener('resize', onResize)
    return () => { window.removeEventListener('resize', onResize); clearTimeout(t) }
  }, [place])

  return (
    <div ref={layer} aria-hidden className="pointer-events-none absolute inset-0 z-0 overflow-hidden">
      {items.map((p) => {
        const o = OBJECTS[p.kind]
        return (
          <div key={p.id} className="desk-object absolute" style={{
            left: p.x, top: p.y, width: p.w, height: p.h, transform: `rotate(${p.rot}deg)`,
            filter: o.shadow === false ? undefined : 'drop-shadow(0 1px 1px rgba(30,28,26,.25)) drop-shadow(0 4px 6px rgba(40,44,38,.18))',
          }}>
            <div className="h-full w-full [&>svg]:h-full [&>svg]:w-full">{o.svg(p.v)}</div>
          </div>
        )
      })}
    </div>
  )
}
