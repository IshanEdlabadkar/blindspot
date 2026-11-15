"""Source adapters. Each provider's content can become its own document server (docs/design/specs/
2026-11-14-multi-source-design.md), or be merged into one library (ingest.build_multi). An adapter
module exposes:

  SOURCE_ID, SOURCE_NAME, CORPUS_NAME, ATTRIBUTION   metadata written to the manifest
  fetch(raw_dir: Path) -> Path                       download the raw content (official API or bulk file only)
  parse(path) -> (pages, date_iso)                   pages: {title, url, updated, also_called, sections}

The names C's merged build uses (COLLECTORS, ATTRIBUTION, parse_genetics, ...) are re-exported from
ingest.sources.extra, so `from ingest.sources import ...` keeps working.
"""
from ingest.sources import fmla, genetics, medlineplus, myhealthfinder
from ingest.sources.extra import (ATTRIBUTION, COLLECTORS, collect_genetics, collect_myhealthfinder,  # noqa: F401
                                  fetch_cached, parse_genetics, parse_myhealthfinder_topic)

ALL = {m.SOURCE_ID: m for m in (medlineplus, fmla, genetics, myhealthfinder)}


def get(source_id: str):
    try:
        return ALL[source_id]
    except KeyError:
        raise KeyError(f"unknown source {source_id!r}; known: {', '.join(ALL)}") from None
