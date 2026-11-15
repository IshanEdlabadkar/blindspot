import { useEffect, useState } from 'react'

export const THEMES = [
  { id: 'paper', name: 'Paper', desk: '#CDD3CB', note: 'The original light desk' },
  { id: 'night', name: 'Night library', desk: '#141A19', note: 'Charcoal green, reading-lamp dark' },
  { id: 'ink', name: 'Midnight ink', desk: '#0E1424', note: 'Deep navy' },
  { id: 'ember', name: 'Ember', desk: '#1C1112', note: 'Dark maroon, a nod to the badger red' },
  { id: 'forest', name: 'Forest', desk: '#0F1D17', note: 'Deep green baize' },
] as const
export type ThemeId = (typeof THEMES)[number]['id']

/** The theme from ?theme=, else the last one picked, else paper. Set before the first paint. */
export function initialTheme(): ThemeId {
  let id: string | null = null
  try { id = new URLSearchParams(location.search).get('theme') ?? localStorage.getItem('blindspot.theme') } catch { /* private mode */ }
  return (THEMES.find((t) => t.id === id)?.id ?? 'paper') as ThemeId
}

export function applyTheme(id: ThemeId) {
  document.documentElement.dataset.theme = id
  document.documentElement.style.colorScheme = id === 'paper' ? 'light' : 'dark'
  try { localStorage.setItem('blindspot.theme', id) } catch { /* private mode */ }
}

/** Five round swatches in the header: the desk colour of each theme. */
export function ThemePicker() {
  const [theme, setTheme] = useState<ThemeId>(initialTheme)
  useEffect(() => { applyTheme(theme) }, [theme])
  return (
    <div role="radiogroup" aria-label="Colour theme" className="flex items-center gap-1.5">
      {THEMES.map((t) => (
        <button key={t.id} type="button" role="radio" aria-checked={theme === t.id} aria-label={`${t.name}: ${t.note}`} title={`${t.name}: ${t.note}`}
          onClick={() => setTheme(t.id)}
          className={`size-5 rounded-full border-2 ${theme === t.id ? 'border-badger' : 'border-graphite/50 hover:border-ink'}`}
          style={{ background: t.desk, boxShadow: 'inset 0 0 0 1px rgba(255,255,255,.35)' }} />
      ))}
    </div>
  )
}
