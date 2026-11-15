"""MedlinePlus health-topics XML -> pages of plain-text sections."""
import xml.etree.ElementTree as ET
from datetime import datetime
from html.parser import HTMLParser


class _SummaryParser(HTMLParser):
    """Turns summary HTML into [(heading or None, [paragraph, ...]), ...]."""

    BLOCK = {"p", "li", "h2", "h3", "h4", "tr"}
    HEADINGS = {"h2", "h3", "h4"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sections: list[list] = [[None, []]]
        self.buf: list[str] = []
        self.tag: str | None = None

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCK:
            self._flush()
            self.tag = tag
        elif tag in ("td", "th") and "".join(self.buf).strip():
            self.buf.append(" | ")
        elif tag == "br":
            self.buf.append(" ")

    def handle_endtag(self, tag):
        if tag in self.BLOCK:
            self._flush()

    def handle_data(self, data):
        self.buf.append(data)

    def _flush(self):
        text = " ".join("".join(self.buf).split())
        tag, self.buf, self.tag = self.tag, [], None
        if not text:
            return
        if tag in self.HEADINGS:
            self.sections.append([text, []])
        else:
            self.sections[-1][1].append(("- " if tag == "li" else "") + text)

    def close(self):
        super().close()
        self._flush()


def html_to_sections(html: str) -> list[tuple[str | None, list[str]]]:
    p = _SummaryParser()
    p.feed(html)
    p.close()
    return [(h, paras) for h, paras in p.sections if paras]


def parse_topics(xml_path) -> tuple[list[dict], str]:
    root = ET.parse(xml_path).getroot()
    generated = datetime.strptime(root.get("date-generated"), "%m/%d/%Y %H:%M:%S").date().isoformat()
    pages = []
    for t in root.findall("health-topic"):
        if t.get("language") != "English":
            continue
        summary = t.find("full-summary")
        if summary is None or not (summary.text or "").strip():
            continue
        pages.append({
            "title": t.get("title"),
            "url": t.get("url"),
            "updated": generated,
            "also_called": [a.text.strip() for a in t.findall("also-called") if a.text and a.text.strip()],
            "sections": html_to_sections(summary.text),
        })
    return pages, generated
