# Multi-source document servers: design

Date: 2026-11-14 · Owner: B (ML and content), with changes for A and C listed below.

## Goal

Answer questions from several independent providers, each running its own Blindspot document server, without any server learning the question, the scores, which chunks were read, or which server held the answer.

First three servers:

| id | Source | Access | Licence | Size |
|---|---|---|---|---|
| `medlineplus` | MedlinePlus health topics (NLM) | Official XML bulk file | Public domain | 2,101 chunks (existing) |
| `fmla` | Federal FMLA regulations, 29 CFR Part 825 | eCFR versioner API (`--compressed` required) | US federal law, public domain | ~260 chunks (79 sections, ~52k words) |
| `cdc` | CDC health pages | CDC content syndication API (`tools.cdc.gov/api/v2`) | Public domain items only; others skipped | capped at ~2,000 chunks |

Rejected: dol.gov pages (site blocks automated access; not to be worked around), Healthline (copyrighted), FDA labels and NIH institutes (lower value for the cost; later).

## Architecture

1. **One server per source.** Each source builds its own `manifest.json`, `score_table.bin`, `fetch_store.bin` and `chunks.jsonl` in `artifacts/<id>/`. A's server is unchanged: one instance per folder.
2. **Shared embedding contract.** Every manifest uses the same model, revision, dimension, query prefix and scale (127). Clients refuse a server whose manifest differs.
3. **New manifest fields:** `source_id` and `source_name`. Each server keeps its own `corpus_version`.
4. **Server list:** `servers.json` at the repo root, `[{"id", "name", "url"}]`. An environment variable may override it. With no list, clients behave exactly as today (one server).
5. **Record format unchanged.** Chunk ids are unique per server; a chunk's identity is `(source, id)`. Clients tag each fetched chunk with `source` and `source_name`.

## Privacy rules for fan-out

- Every question is sent to **every** server, always. Choosing servers by topic would reveal the topic.
- Every server receives exactly **k = 10** fetches per question, whatever the scores. A different count per server would reveal where the answer was.
- Remaining leakage per server is unchanged: that a query happened, its time and its sizes.

## Merge on the device

The client decrypts each server's scores, fetches the top 10 from each (30 chunks for 3 servers), and `answer()` reranks all of them with the local cross-encoder and keeps the best 5 as sources. Cross-server search scores are comparable because the embedding contract is shared; the score-threshold decline uses the best search score across servers. Citations carry `source` and `source_name`.

## Compatibility and the demo

- MedlinePlus's current files stay in `artifacts/` (root) unchanged until A and C read `artifacts/medlineplus/`; the same tables are also written there. The root copies are removed only after both switch, with the team's agreement.
- Multi-server is additive: without `servers.json`, the pipeline, baseline and eval run single-server as today, so the existing demo cannot regress.

## Work by owner

| Owner | Work |
|---|---|
| B | Source adapters (`ingest/sources/`), `ingest.build --source`, per-source artifacts, multi-source `ask_plain`, citation source fields, eval questions per source and cross-domain, contract update |
| C | Fan-out in `client/pipeline.py` over `servers.json`, following the privacy rules; show the source on each citation |
| A | Run one server instance per source (local ports 8080–8082 or Render services) |

## Costs and risks

- Each question does ~3x the encrypted work and traffic (one round of scoring and 10 fetches per server).
- Memory: ~650 MB per server instance in token mode; three instances do not fit comfortably on the 8 GB dev Mac. Prefer remote hosting or hint mode for the extra servers.
- eCFR text is formal legal language; answers will quote regulations rather than plain-language guidance.
- CDC syndication includes non-topic content (news, features); the adapter filters and caps it, and its quality is checked by the eval.

## Testing

- Unit tests per adapter on small fixtures (no network).
- Build tests: each source's artifacts round-trip and verify, `source_id` set, ids contiguous.
- Baseline: fan-out queries every source, fetches exactly k per source, merges.
- Eval: FMLA questions (including the spec's "Can I take FMLA leave for a pregnancy complication?"), CDC questions, and cross-domain questions; previous 82 questions must not regress.
