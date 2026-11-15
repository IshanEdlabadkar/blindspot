"""Source adapters. Each provider's content becomes its own document server (docs/superpowers/specs/
2026-11-14-multi-source-design.md). An adapter module exposes:

  SOURCE_ID, SOURCE_NAME, CORPUS_NAME, ATTRIBUTION   metadata written to the manifest
  fetch(raw_dir: Path) -> Path                       download the raw content (official API or bulk file only)
  parse(path) -> (pages, date_iso)                   pages: {title, url, updated, also_called, sections}
"""
from ingest.sources import fmla, medlineplus

ALL = {m.SOURCE_ID: m for m in (medlineplus, fmla)}


def get(source_id: str):
    try:
        return ALL[source_id]
    except KeyError:
        raise KeyError(f"unknown source {source_id!r}; known: {', '.join(ALL)}") from None
