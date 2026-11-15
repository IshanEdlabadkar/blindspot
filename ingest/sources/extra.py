"""Extra public-domain sources for the corpus, beyond MedlinePlus health topics.

Each collector returns pages in the same shape as ingest.extract.parse_topics:
    {"title", "url", "updated", "also_called": [...], "sections": [(heading or None, [paragraphs])],
     "source": short source name}

Only sources whose text we may copy and redistribute are here (Blindspot ships every
passage to every asker). Reuse terms checked Nov 14, 2026:

  genetics      MedlinePlus Genetics condition summaries. Listed as public domain by NLM:
                https://medlineplus.gov/about/using/usingcontent/
  myhealthfinder  ODPHP MyHealthfinder topics (health.gov). Public domain; link to the page
                and acknowledge ODPHP: https://health.gov/copyright-policy

Not included, and why:
  WebMD         Terms of use forbid copying and scraping.
  CDC           Text is public domain, but there is no bulk feed, and its syndication API
                forbids redistribution. Scraping cdc.gov HTML is left for later.
  NCI / PDQ     Text is public domain, but the bulk XML comes through NCI's syndication
                program (registration). "PDQ" is a trademark, so titles must drop it.
"""
import html as htmllib
import json
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests

from ingest.extract import html_to_sections

UA = {"User-Agent": "blind-rag-ingest/1 (hackathon research; public-domain health content)"}

GENETICS_URL = "https://medlineplus.gov/download/ghr-summaries.xml"
MHF_BASE = "https://odphp.health.gov/myhealthfinder/api/v4"

ATTRIBUTION = {
    "medlineplus": "MedlinePlus, National Library of Medicine",
    "genetics": "MedlinePlus Genetics, National Library of Medicine",
    "myhealthfinder": "MyHealthfinder, Office of Disease Prevention and Health Promotion (health.gov)",
}


def _get(url: str, params=None, timeout: float = 120) -> requests.Response:
    r = requests.get(url, params=params, headers=UA, timeout=timeout)
    r.raise_for_status()
    return r


def fetch_cached(url: str, dest: Path, params=None) -> Path:
    """Download once into data/raw/ so a rebuild does not hit the source again."""
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(_get(url, params).content)
    return dest


# ---------------------------------------------------------------- MedlinePlus Genetics

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el, *names):
    for c in el:
        if _local(c.tag) in names:
            return c
    return None


def _inner_html(el) -> str:
    """The <html> payload: escaped text (usual) or literal XHTML child elements."""
    if len(el):
        return (el.text or "") + "".join(ET.tostring(c, encoding="unicode") for c in el)
    return el.text or ""


def _role_heading(role: str | None) -> str | None:
    if not role or role in ("description", "summary"):
        return None
    return role.replace("-", " ").replace("_", " ").strip().capitalize()


def parse_genetics(xml_path, kinds=("condition",)) -> list[dict]:
    """MedlinePlus Genetics compendium (ghr-summaries.xml) -> pages.

    Schema-tolerant: any element with a name, a page URL and a text list is a summary;
    its kind (condition, gene, chromosome) is read from the element's tag.
    """
    pages = []
    for el in ET.parse(xml_path).getroot().iter():
        tag = _local(el.tag)
        name, page, texts = _child(el, "name"), _child(el, "ghr-page", "ghr_page"), _child(el, "text-list")
        if name is None or page is None or texts is None:
            continue
        kind = next((k for k in ("condition", "gene", "chromosome") if k in tag), "condition")
        if kind not in kinds:
            continue
        sections = []
        for t in texts.iter():
            if _local(t.tag) != "text":
                continue
            h = _child(t, "html")
            if h is None:
                continue
            role = _child(t, "text-role")
            heading = _role_heading(role.text.strip() if role is not None and role.text else None)
            for i, (sub, paras) in enumerate(html_to_sections(_inner_html(h))):
                sections.append(((heading if i == 0 and not sub else sub) or None, paras))
        if not sections:
            continue
        syn = [s.text.strip() for s in el.iter() if _local(s.tag) == "synonym" and s.text and s.text.strip()]
        date = _child(el, "published")
        if date is None or not (date.text or "").strip():
            date = _child(el, "reviewed")  # (an empty Element is falsy, so no `or` here)
        pages.append({
            "title": name.text.strip(),
            "url": (page.text or "").strip(),
            "updated": (date.text or "").strip() if date is not None else "",
            "also_called": syn[:6],
            "sections": sections,
            "source": "genetics",
        })
    return pages


def collect_genetics(raw_dir: Path, kinds=("condition",)) -> list[dict]:
    path = fetch_cached(GENETICS_URL, raw_dir / "ghr-summaries.xml")
    return parse_genetics(path, kinds)


# ---------------------------------------------------------------- MyHealthfinder (health.gov)

def _epoch_date(v) -> str:
    try:
        return datetime.fromtimestamp(int(v), tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def parse_myhealthfinder_topic(data: dict) -> list[dict]:
    """One topicsearch.json response -> pages (normally one)."""
    resources = (((data.get("Result") or {}).get("Resources") or {}).get("Resource")) or []
    if isinstance(resources, dict):
        resources = [resources]
    pages = []
    for r in resources:
        secs = ((r.get("Sections") or {}).get("section")) or []
        if isinstance(secs, dict):
            secs = [secs]
        sections = []
        for s in secs:
            content = htmllib.unescape(s.get("Content") or "")
            for i, (sub, paras) in enumerate(html_to_sections(content)):
                head = (s.get("Title") or "").strip() if i == 0 else sub
                sections.append((head or sub or None, paras))
        url = (r.get("AccessibleVersion") or "").strip()
        if not sections or not url:
            continue
        pages.append({
            "title": (r.get("Title") or "").strip(),
            "url": url,
            "updated": _epoch_date(r.get("LastUpdate")),
            "also_called": [],
            "sections": sections,
            "source": "myhealthfinder",
        })
    return pages


def collect_myhealthfinder(raw_dir: Path, pause: float = 0.25) -> list[dict]:
    d = raw_dir / "myhealthfinder"
    listing = json.loads(fetch_cached(f"{MHF_BASE}/itemlist.json", d / "itemlist.json",
                                      params={"Type": "topic", "Lang": "en"}).read_text())
    items = ((listing.get("Result") or {}).get("Items") or {}).get("Item") or []
    pages, seen = [], set()
    for it in items:
        tid = str(it.get("Id") or "")
        if not tid or tid in seen:
            continue
        seen.add(tid)
        dest = d / f"topic-{tid}.json"
        fresh = not dest.exists()
        data = json.loads(fetch_cached(f"{MHF_BASE}/topicsearch.json", dest,
                                       params={"TopicId": tid, "Lang": "en"}).read_text())
        pages += parse_myhealthfinder_topic(data)
        if fresh:
            time.sleep(pause)  # be polite to a public API
    return pages


COLLECTORS = {"genetics": collect_genetics, "myhealthfinder": collect_myhealthfinder}
