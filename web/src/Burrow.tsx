import burrowSvg from './assets/burrow.svg'

/** C's Burrow mascot, unchanged, with motion around it:
 *  idle = a slow breath, dig = paws-at-work wobble with clods of soil flying, peek = rises out of the ground. */
export function Burrow({ mood = 'idle', size = 112, className = '' }: {
  mood?: 'idle' | 'dig' | 'peek'; size?: number; className?: string
}) {
  const anim = mood === 'dig' ? 'dig .5s ease-in-out infinite' : mood === 'idle' ? 'bob 3.4s ease-in-out infinite' : undefined
  return (
    <div className={`relative inline-block ${className}`} style={{ width: size, height: size * 1.03 }}>
      <img src={burrowSvg} alt="Burrow, the Blindspot badger" width={size} height={Math.round(size * 1.03)}
        draggable={false} className="select-none" style={{ animation: anim, transformOrigin: '50% 85%' }} />
      {mood === 'dig' && Array.from({ length: 8 }, (_, i) => (
        <span key={i} aria-hidden className="absolute rounded-full"
          style={{
            left: `${22 + ((i * 17) % 56)}%`, bottom: `${2 + (i % 3) * 2}%`,
            width: 5 + (i % 3) * 2, height: 5 + (i % 3) * 2,
            background: i % 3 === 0 ? '#5A3E33' : i % 3 === 1 ? '#3B2C26' : '#7A5644',
            ['--dx' as string]: `${(i % 2 ? 1 : -1) * (10 + i * 4)}px`,
            animation: `clod ${0.75 + (i % 3) * 0.12}s ease-out ${i * 0.08}s infinite`,
          }} />
      ))}
    </div>
  )
}
