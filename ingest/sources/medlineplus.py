"""MedlinePlus health topics (NLM), from the official XML bulk file. Public domain."""
import re
from pathlib import Path

import requests

from ingest.extract import parse_topics

SOURCE_ID = "medlineplus"
SOURCE_NAME = "MedlinePlus (National Library of Medicine)"
CORPUS_NAME = "MedlinePlus health topics (public domain subset)"
ATTRIBUTION = "Source: MedlinePlus, National Library of Medicine"

XML_INDEX = "https://medlineplus.gov/xml.html"
XML_LINK = re.compile(r"https://medlineplus\.gov/xml/mplus_topics_\d{4}-\d{2}-\d{2}\.xml")


def latest_xml_url() -> str:
    html = requests.get(XML_INDEX, timeout=30).text
    urls = sorted(set(XML_LINK.findall(html)))
    if not urls:
        raise RuntimeError(f"no health-topics XML link found on {XML_INDEX}")
    return urls[-1]


def fetch(raw_dir: Path) -> Path:
    url = latest_xml_url()
    dest = Path(raw_dir) / url.rsplit("/", 1)[1]
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get(url, timeout=300)
        r.raise_for_status()
        dest.write_bytes(r.content)
    return dest


def parse(path):
    return parse_topics(path)
