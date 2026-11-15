# Growing the library

The demo corpus is `artifacts/`: 2,101 chunks from MedlinePlus health topics (B's build). An expanded corpus can be built next to it without touching it.

## Sources

| Source | Content | Reuse terms (checked Nov 14, 2026) | In the build |
| --- | --- | --- | --- |
| MedlinePlus health topics | Health topic summaries | Public domain (NLM). The A.D.A.M. encyclopedia on the same site is copyrighted and excluded. | Yes (B's parser) |
| MedlinePlus Genetics | Genetic condition summaries | Public domain (NLM lists the genetics summaries explicitly) | Yes, conditions only (genes are optional) |
| MyHealthfinder (health.gov) | Prevention and healthy-living topics | Public domain; link to the page and credit ODPHP | Yes |
| CDC | Disease and prevention pages | Text is public domain, but no bulk feed, and the syndication API forbids redistribution | No: would need an HTML scraper |
| NCI cancer.gov | Cancer information | Text is public domain; bulk XML comes through NCI's syndication program (registration); "PDQ" is a trademark | No: needs registration |
| WebMD | Everything | Terms of use forbid copying and scraping | Never |

Every passage is shipped to every asker's device, so only text we may copy and redistribute can go in.

## Build it (on a machine with internet, e.g. the demo Mac)

```bash
make corpus-expanded            # writes artifacts-expanded/ (~5 min: downloads, then embeds every chunk)
```

Or pick sources: `python3.12 -m ingest.build_multi --sources medlineplus,genetics --out artifacts-expanded`.
`--dry-run` downloads and chunks only, and prints the chunk count per source without embedding.

Downloads are cached in `data/raw/`. The build refuses no size, but warns above 10,000 chunks, the spec's v1 target: every question scores every chunk, and the one-time scoring download grows with the library (about 17 MB at 2,101 chunks).

## Serve it

```bash
make stop
make demo DATA=artifacts-expanded
make preflight DATA=artifacts-expanded      # in a second tab
```

The manifest gets a new `corpus_version`, so clients reload automatically.

## Before switching the demo to it

- Re-run B's evaluation on the new corpus. The numbers in the Evidence tab are for `artifacts/`.
- Check the size and speed with `make measure` (A).
- The hosted server (Render) reads its corpus from the provider's storage, not from this repo. Publishing it there is A's step (`scripts/publish_corpus.sh` on the `deploy/render` branch).
- B owns `ingest/`. This build reuses B's chunker and table writer unchanged; the new code is `ingest/sources.py` and `ingest/build_multi.py`.

## What was verified

- Parsers tested on fixtures shaped like the real feeds (`tests/test_sources.py`). The feed structures were read from the live MedlinePlus Genetics JSON and MyHealthfinder API on Nov 14.
- An offline build (B's real MedlinePlus chunks plus fixture pages, fake embeddings) was served by A's real crypto server: encrypted top 10 equalled plaintext top 10, with both download-all and batched PIR fetch.
- **Not yet run against the live downloads.** The bulk Genetics file (`ghr-summaries.xml`) is parsed schema-tolerantly because its exact XML layout could not be inspected from the build workspace. Run `--dry-run` first and check the per-source counts are in the hundreds, not zero.
