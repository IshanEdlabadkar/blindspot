"""MedlinePlus Genetics condition summaries (NLM). Public domain. Parsing lives in ingest.sources.extra (C)."""
import time
from pathlib import Path

from ingest.sources.extra import GENETICS_URL, fetch_cached, parse_genetics

SOURCE_ID = "genetics"
SOURCE_NAME = "MedlinePlus Genetics (National Library of Medicine)"
CORPUS_NAME = "MedlinePlus Genetics condition summaries"
ATTRIBUTION = "Source: MedlinePlus Genetics, National Library of Medicine"


def fetch(raw_dir: Path) -> Path:
    return fetch_cached(GENETICS_URL, Path(raw_dir) / "ghr-summaries.xml")


def parse(path) -> tuple[list[dict], str]:
    """Pages carry their own published dates; the corpus date is the day the file was downloaded."""
    return parse_genetics(path), time.strftime("%Y-%m-%d", time.localtime(Path(path).stat().st_mtime))
