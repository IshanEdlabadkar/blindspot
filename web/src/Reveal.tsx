import { motion } from 'motion/react'

const EASE = [0.16, 1, 0.3, 1] as const   // the slow-out curve Apple's pages use

/** Content that rises, sharpens and fades in the first time it scrolls into view. */
export function Reveal({ children, delay = 0, y = 36, className, as = 'div', label }: {
  children: React.ReactNode; delay?: number; y?: number; className?: string; as?: 'div' | 'li' | 'section'; label?: string
}) {
  const M = motion[as]
  return (
    <M className={className} aria-label={label} initial={{ opacity: 0, y, scale: 0.985, filter: 'blur(6px)' }}
      whileInView={{ opacity: 1, y: 0, scale: 1, filter: 'blur(0px)' }}
      viewport={{ once: true, amount: 0.25, margin: '0px 0px -8% 0px' }}
      transition={{ duration: 0.9, delay, ease: EASE }}>
      {children}
    </M>
  )
}
