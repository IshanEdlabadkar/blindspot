"""MyHealthfinder topics (ODPHP, health.gov), from its public API. Public domain; link to the page and
acknowledge ODPHP. Fetching and parsing live in ingest.sources.extra (C)."""
import json
import time
from pathlib import Path

from ingest.sources.extra import collect_myhealthfinder, parse_myhealthfinder_topic

SOURCE_ID = "myhealthfinder"
SOURCE_NAME = "MyHealthfinder (ODPHP, health.gov)"
CORPUS_NAME = "MyHealthfinder health topics"
ATTRIBUTION = "Source: MyHealthfinder, Office of Disease Prevention and Health Promotion (health.gov)"


def fetch(raw_dir: Path) -> Path:
    """Downloads every topic once into raw_dir/myhealthfinder/ (cached) and returns that folder."""
    collect_myhealthfinder(Path(raw_dir))
    return Path(raw_dir) / "myhealthfinder"


def parse(path) -> tuple[list[dict], str]:
    folder = Path(path)
    pages = []
    for f in sorted(folder.glob("topic-*.json")):
        pages += parse_myhealthfinder_topic(json.loads(f.read_text()))
    stamp = folder / "itemlist.json"
    date = time.strftime("%Y-%m-%d", time.localtime((stamp if stamp.exists() else folder).stat().st_mtime))
    return pages, date
