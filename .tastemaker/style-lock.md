# Style lock: Blind RAG web UI ("Card catalog")

Locked 2026-11-15, replacing the dark "Burrow cross-section" direction, which the user rejected as looking AI-generated.
Reuse these tokens for every screen; change only on an explicit request.

## Direction contract
- **Thesis:** you are asking a library. Every screen is a real library object: the question is a call slip, the answer is a catalog card, the proof is a printed traffic receipt with rubber stamps.
- **Surfaces:** landing (intro plus a blank call slip), chat (filed slips and catalog cards on a desk), X-ray (a till receipt beside a plain explanation).
- **Rejected on purpose:** dark backgrounds, glows, gradients as decoration, rounded cards, chat bubbles, big-number stat tiles, illustrated "worlds".

## Identity
- Mascot: **Burrow** (`web/src/assets/burrow.svg`, C's original, unchanged). Small, sitting on the desk or a slip corner.
- Brand colour: UW–Madison Badger red, for the card head rule, the main button and red ink. No Bucky Badger, no Motion W.

## Color contract (light only)
| Token | Hex | Role |
|---|---|---|
| blotter | #CDD3CB | desk/page background, fine dot fibre |
| card | #FFFDF8 | catalog cards, receipt |
| slip | #F3EEDC | call slips (thinner stock) |
| ink | #1E1C1A | text |
| graphite | #57524B | secondary text (6.9:1 on card) |
| rule | #A9C0DA | ruled lines only, never text |
| badger | #C5050C | head rule, button fill, citation numbers (6.2:1 on card) |
| stamp | #B10E16 | "Read"/"Answered" stamps, errors |
| sealed | #23408E | "Not read" stamps, sealed ciphertext |
| highlighter | #FFE14D | only words that leaked |

## Type
- Courier Prime 400/700: anything typed onto paper (questions, answers, receipts, slip numbers).
- Red Hat Display 700/900: headlines, slip headings, buttons, stamps. Red Hat Text 400/500: explanations around the objects.

## Shape and depth
- Paper corners: square (2px on buttons). One paper shadow. Slips have a perforated top edge, the receipt a torn bottom, cards a red head rule, blue lines and a rod hole.

## Motion
- One moment: stamps thud onto the receipt one after another; the highlighter draws across leaked words. Everything else: short ease-out responses. All off under reduced motion.

## Copy
- Plain and specific, no em dashes, no slogans. Library words: call slip, hand it in, receipt.

## Desk objects
- `web/src/DeskObjects.tsx` scatters real library things on the empty desk at random on each view: pencil, paperclip, date stamp, ink pad, closed books with call numbers, an open book, reading glasses, a magnifying glass, a rubber band, a coffee ring, a date-due card, index tabs.
- Drawn flat in ink from this palette. They sit behind content and are placed only where they don't touch text, slips, cards, the receipt or the mascot. Existing objects stay put as answers arrive; a new view reshuffles them.
