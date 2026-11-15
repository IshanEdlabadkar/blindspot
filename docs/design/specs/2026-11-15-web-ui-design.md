# Blind RAG web UI ("Vault"): design

Date: 2026-11-15 · Owner: B · Replaces C's Streamlit UI as the main demo; `ui/` stays untouched as the fallback.

## Goal

A premium web app where a judge asks anything, gets a cited answer, then watches an animated "X-ray" of their own question that proves their words never left the laptop in readable form. Scope: API, Chat and X-ray first; landing and evidence pages only if time remains.

## Architecture

```
browser (web/: React + Vite + TS + Tailwind + Framer Motion, built to web/dist)
   │ fetch + Server-Sent Events
api/ (FastAPI, :8600, also serves web/dist)
   ├─ client.multi.MultiPipeline / client.pipeline.Pipeline   (C, unchanged)
   ├─ wiretap.search over data/wire/wire.jsonl                (B, unchanged)
   └─ plaintext "normal RAG" server via its relay (:9001)     (B, unchanged)
```

Document servers come from `BLIND_RAG_SERVERS` (the wiretap relay ports when started with `wiretap/demo.sh`). No crypto, retrieval or answer logic is rewritten.

### Endpoints

| Endpoint | Returns |
|---|---|
| `GET /api/status` | per server: url, source name, passages, corpus version, up/down; helper and local model ok |
| `POST /api/ask` `{question, compare}` | `text/event-stream`: `stage` (name, seconds) as each step finishes → `answer` (result + trace) → `plain` (normal server's log entry, if compare) → `proof` (traffic search per route) → `done`; `error` (stage, message, fix) on failure |
| `GET /api/wire?word=&since=` | traffic search for any word since a time |

## Screens

**Chat.** Empty state: "Ask anything. Your words stay on this laptop.", input, three suggestion chips, live server chips. Answer cards: inline citation markers with the exact source sentence, source name and link on hover/expand; 988/911 notice pinned on top; kind decline state; "X-ray this answer".

**X-ray.** Five stages, all real data from that question: ① on your laptop (question → 384 numbers → locked, hex scramble) ② on the wire (packets with real byte counts per server) ③ at each server (passages scored without reading; exactly 10 fetched) ④ back on the laptop (unlock, rerank, answer) ⑤ the proof (0/N words per Blind RAG server vs N/N at the normal server with its log highlighted; secret-word search). Closing honest line: servers still see that you asked, when, and your IP.

## Visual system ("Vault")

Near-black surfaces (#0B0D10), soft borders, one sans + monospace for bytes and ciphertext, mint = locked/safe, red only where something leaked. No mascot. Purposeful motion with `prefers-reduced-motion` support. Desktop first (1280–1440), usable at 390 px.

## Testing

API: unit tests with a fake pipeline (event order, error event, proof uses `since`). Web: type-check and build. End to end: real encrypted system through the relays in the browser pane, at 1440 and 390 widths.
