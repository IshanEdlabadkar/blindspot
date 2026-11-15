"""Federal FMLA regulations, 29 CFR Part 825, from the official eCFR versioner API. US federal law, public domain.

dol.gov blocks automated access, so its plain-language pages are not used; the regulation itself is the
authoritative text. One page per section, linked to the section's eCFR URL.
"""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

SOURCE_ID = "fmla"
SOURCE_NAME = "Federal FMLA regulations (29 CFR Part 825, eCFR)"
CORPUS_NAME = "The Family and Medical Leave Act regulations, 29 CFR Part 825"
ATTRIBUTION = "Source: Electronic Code of Federal Regulations (eCFR), 29 CFR Part 825"

API = "https://www.ecfr.gov/api/versioner/v1"
SECTION_URL = "https://www.ecfr.gov/current/title-29/section-{}"
FILENAME = re.compile(r"ecfr_29cfr825_(\d{4}-\d{2}-\d{2})\.xml$")


def _text(el) -> str:
    return " ".join("".join(el.itertext()).split())


def fetch(raw_dir: Path) -> Path:
    titles = requests.get(f"{API}/titles.json", timeout=60).json()["titles"]
    date = next(t["latest_issue_date"] for t in titles if t["number"] == 29)
    dest = Path(raw_dir) / f"ecfr_29cfr825_{date}.xml"
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get(f"{API}/full/{date}/title-29.xml", params={"part": "825"}, timeout=300)
        r.raise_for_status()  # requests asks for gzip by default, which the API requires
        dest.write_bytes(r.content)
    return dest


def parse(path) -> tuple[list[dict], str]:
    m = FILENAME.search(str(path))
    if not m:
        raise ValueError(f"expected a file named ecfr_29cfr825_<date>.xml, got {path}")
    date = m.group(1)
    root = ET.parse(path).getroot()
    pages = []
    for subpart in root.iter("DIV6"):
        heading = _text(subpart.find("HEAD")) if subpart.find("HEAD") is not None else ""
        subpart_name = heading.split("—", 1)[-1].strip() if heading else ""
        for sec in subpart.iter("DIV8"):
            head = _text(sec.find("HEAD"))
            paras = [t for t in (_text(p) for p in sec.findall("P")) if t]
            if "[Reserved]" in head or not paras:
                continue
            pages.append({
                "title": head.replace("§ ", "29 CFR ", 1),
                "url": SECTION_URL.format(sec.get("N")),
                "updated": date,
                "also_called": [subpart_name] if subpart_name else [],
                "sections": [(None, paras)],
            })
    return pages, date
