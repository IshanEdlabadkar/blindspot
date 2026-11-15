# Multi-source Phase 1 (MedlinePlus + FMLA) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn ingestion into per-source adapters, add the FMLA regulations (29 CFR 825) as a second source with its own artifacts, and make the plaintext baseline, `answer()` and the eval work across several sources.

**Architecture:** `ingest/sources/<id>.py` adapters share one interface (`fetch`, `parse`, metadata). `ingest.build --source <id>` writes `artifacts/<id>/` with `source_id`/`source_name` in the manifest. `baseline.retrieve.MultiIndex` queries every local source, takes exactly k from each, and merges by score; `answer()` reranks the merged list and cites with source fields.

**Tech Stack:** Python 3.12, numpy, requests, sentence-transformers, pytest (as before).

**Spec:** `docs/superpowers/specs/2026-11-14-multi-source-design.md`

## Global Constraints

- Embedding contract unchanged for every source: `BAAI/bge-small-en-v1.5` @ `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`, 384 dims, L2, query prefix, scale 127.
- Record format unchanged: 2,048 bytes, little-endian length, JSON `{id,title,url,updated,text}`.
- Root `artifacts/` (MedlinePlus, version `2026-11-14.2`) must not change in this plan. Building without `--source` keeps today's behaviour.
- Fan-out privacy: every source is always queried and always returns exactly k chunks.
- eCFR requests must allow compression (requests does by default).
- No new dependencies.

## File structure

| File | Responsibility |
|---|---|
| `ingest/sources/__init__.py` | Registry: `get(source_id)` returns the adapter module |
| `ingest/sources/medlineplus.py` | Wraps existing MedlinePlus download and `parse_topics` |
| `ingest/sources/fmla.py` | eCFR fetch and parse of 29 CFR Part 825, one page per section |
| `ingest/build.py` | `--source` flag; `write_artifacts(..., source=...)` adds `source_id`, `source_name`, names, attribution |
| `baseline/retrieve.py` | `PlainIndex.fetch`, new `MultiIndex`, `discover_sources()` |
| `baseline/ask_plain.py` | Uses `MultiIndex` when `artifacts/*/manifest.json` exist |
| `client/answer.py` | Citations carry `source`, `source_name` when the chunk has them |
| `eval/questions.jsonl`, `eval/run_eval.py` | FMLA and cross-domain questions; retrieval over the merged list |
| `docs/contracts.md` | `servers.json`, manifest fields, fan-out rules, citation source fields |

---

### Task 1: Source adapters and FMLA parsing

**Files:** Create `ingest/sources/__init__.py`, `ingest/sources/medlineplus.py`, `ingest/sources/fmla.py`. Test `tests/test_sources.py`.

**Interfaces:**
- Produces: each adapter module has `SOURCE_ID`, `SOURCE_NAME`, `CORPUS_NAME`, `ATTRIBUTION`, `fetch(raw_dir: Path) -> Path`, `parse(path) -> (pages, date_iso)`. Pages use the existing page shape `{title, url, updated, also_called, sections}`. `ingest.sources.get(id)`, `ingest.sources.ALL`.

- [ ] **Step 1: Failing test** with a small eCFR XML fixture: two sections, one `[Reserved]`, italics inside paragraphs; assert one page per real section, title `29 CFR 825.120 Leave for pregnancy or birth.`, URL `https://www.ecfr.gov/current/title-29/section-825.120`, `also_called` holds the subpart heading, paragraph text joins italic runs, reserved sections skipped, date from the filename. Assert `get("medlineplus").parse` matches `parse_topics`, and `get("nope")` raises `KeyError`.
- [ ] **Step 2:** Run, see it fail (`No module named 'ingest.sources'`).
- [ ] **Step 3: Implement.** `fmla.parse` walks `DIV6` (subpart, heading as `also_called`) and its `DIV8` sections; title is the `HEAD` text with `§ ` replaced by `29 CFR `; paragraphs are `" ".join(P.itertext())` whitespace-normalised; date comes from `ecfr_29cfr825_<date>.xml`. `fmla.fetch` reads `latest_issue_date` for title 29 from `/api/versioner/v1/titles.json`, downloads `/api/versioner/v1/full/<date>/title-29.xml?part=825`, saves under that filename. `medlineplus.fetch/parse` delegate to the existing functions.
- [ ] **Step 4:** Tests pass. **Step 5:** Commit.

### Task 2: Build per source

**Files:** Modify `ingest/build.py`. Test `tests/test_build.py`.

**Interfaces:**
- Produces: `write_artifacts(chunks, vecs, out_dir, corpus_version, source=None)` where `source` is an adapter module (default MedlinePlus metadata); manifest gains `source_id`, `source_name`. CLI: `python -m ingest.build --source fmla` → `artifacts/fmla/`; no `--source` → unchanged root build.

- [ ] **Step 1: Failing test:** `write_artifacts(..., source=fmla)` writes `source_id == "fmla"`, `source_name`, `corpus_name`, `attribution` from the adapter; default call writes `source_id == "medlineplus"`.
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5: Real builds:** `uv run python -m ingest.build --source fmla` and `--source medlineplus --corpus-version 2026-11-14.2`. Check that `artifacts/medlineplus/score_table.bin` and `fetch_store.bin` are byte-identical to the root files (same content, deterministic), and that the root `artifacts/` is untouched (`git status`).
- [ ] **Step 6:** Commit, including `artifacts/fmla/` and `artifacts/medlineplus/`.

### Task 3: Multi-source retrieval and baseline

**Files:** Modify `baseline/retrieve.py`, `baseline/ask_plain.py`. Test `tests/test_retrieve.py`, `tests/test_ask_plain.py`.

**Interfaces:**
- Produces: `PlainIndex.fetch(qvec, k, mode) -> list[chunk]` with `source`, `source_name`, `score`; `discover_sources(root=ARTIFACTS) -> list[Path]` (subfolders with `manifest.json`, sorted); `MultiIndex(dirs, float_paths=None)` with `.fetch(qvec, k, mode)` returning exactly `k` chunks **per source**, merged and sorted by score descending, and `.sources`. `default_index()` returns `MultiIndex` over `discover_sources()` when non-empty, else `PlainIndex` on the root.

- [ ] **Step 1: Failing tests:** two synthetic sources; a query vector equal to a row in source B returns that chunk first with `source == "b"`; result length is `2 * k`; each source contributes exactly k; an empty discovery falls back to the root.
- [ ] **Step 2–4:** Fail, implement, pass. `ask_plain` calls `idx.fetch(...)` for both index types.
- [ ] **Step 5:** Commit.

### Task 4: Citations name their source

**Files:** Modify `client/answer.py`. Test `tests/test_answer.py`.

- [ ] **Step 1: Failing test:** chunks with `source`/`source_name` produce citations with the same fields; chunks without them produce citations without them (backward compatible).
- [ ] **Step 2–4:** Fail, implement in `_cite`, pass. **Step 5:** Commit.

### Task 5: Eval across sources

**Files:** Modify `eval/questions.jsonl`, `eval/run_eval.py`, `docs/contracts.md`. Test `tests/test_eval.py`.

- [ ] **Step 1:** Retrieval ranks use the merged `fetch` list (top 20 merged); `int8_top10_ids` become `"source:id"` strings so the encrypted pipeline can be compared the same way. Test updates first.
- [ ] **Step 2:** Add ~10 FMLA questions labelled from the real section list (including the spec's "Can I take FMLA leave for a pregnancy complication?") and 2 cross-domain questions. Relabel q024 ("How do I appeal a denied FMLA leave request at work?"), which the FMLA source can now answer. Gold URLs must exist in `artifacts/*/chunks.jsonl`.
- [ ] **Step 3:** Contract update: `servers.json` format, manifest `source_id`/`source_name`, fan-out privacy rules, citation `source` fields.
- [ ] **Step 4:** Full eval; check that MedlinePlus questions do not regress compared with the 82-question scorecard. Rebuild the scorecard.
- [ ] **Step 5:** Commit and push.
