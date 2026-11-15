"""Extra corpus sources: parsers on fixtures shaped like the real feeds, and an offline build."""
import json
import struct

import numpy as np

import contracts as c
from ingest import build_multi
from ingest.sources import parse_genetics, parse_myhealthfinder_topic

# Shaped like https://medlineplus.gov/download/ghr-summaries.xml: one summary per element,
# html payload escaped, plus a gene summary that the default build skips.
GENETICS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<summaries>
  <health-condition-summary>
    <name>Alzheimer disease</name>
    <ghr-page>https://medlineplus.gov/genetics/condition/alzheimer-disease</ghr-page>
    <text-list>
      <text><text-role>description</text-role>
        <html>&lt;p&gt;Alzheimer disease is a degenerative disease of the brain that causes dementia.&lt;/p&gt;</html></text>
      <text><text-role>frequency</text-role>
        <html>&lt;p&gt;Alzheimer disease affects an estimated 6.5 million Americans.&lt;/p&gt;</html></text>
    </text-list>
    <synonym-list><synonym>AD</synonym><synonym>Alzheimer's disease</synonym></synonym-list>
    <reviewed>2019-05</reviewed>
    <published>2023-03-23</published>
  </health-condition-summary>
  <gene-summary>
    <name>APOE gene</name>
    <ghr-page>https://medlineplus.gov/genetics/gene/apoe</ghr-page>
    <text-list><text><text-role>function</text-role><html>&lt;p&gt;The APOE gene makes a protein.&lt;/p&gt;</html></text></text-list>
  </gene-summary>
  <health-condition-summary>
    <name>Empty condition</name>
    <ghr-page>https://medlineplus.gov/genetics/condition/empty</ghr-page>
    <text-list/>
  </health-condition-summary>
</summaries>
"""

# Shaped like odphp.health.gov/myhealthfinder/api/v4/topicsearch.json (Content is HTML-escaped).
MHF_TOPIC = {"Result": {"Error": "False", "Total": 1, "Resources": {"Resource": [{
    "Type": "Topic", "Id": "30530", "Title": "Get Enough Calcium", "LastUpdate": "1789052471",
    "AccessibleVersion": "https://odphp.health.gov/myhealthfinder/healthy-living/nutrition/get-enough-calcium",
    "Sections": {"section": [
        {"Title": "The Basics: Overview",
         "Content": "&lt;p&gt;Calcium is important at every age, but many people don&#8217;t get enough.&lt;/p&gt;"},
        {"Title": "Take Action: Vitamin D",
         "Content": "&lt;p&gt;Get enough vitamin D.&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Eat fish.&lt;/li&gt;&lt;/ul&gt;"},
    ]}}]}}}


def test_parse_genetics(tmp_path):
    f = tmp_path / "ghr.xml"
    f.write_text(GENETICS_XML)
    pages = parse_genetics(f)
    assert [p["title"] for p in pages] == ["Alzheimer disease"]          # gene skipped, empty skipped
    p = pages[0]
    assert p["url"].endswith("/condition/alzheimer-disease") and p["updated"] == "2023-03-23"
    assert p["also_called"] == ["AD", "Alzheimer's disease"] and p["source"] == "genetics"
    assert p["sections"][0] == (None, ["Alzheimer disease is a degenerative disease of the brain that causes dementia."])
    assert p["sections"][1][0] == "Frequency"
    assert len(parse_genetics(f, kinds=("condition", "gene"))) == 2


def test_parse_genetics_literal_xhtml(tmp_path):
    f = tmp_path / "ghr.xml"
    f.write_text("<summaries><health-condition-summary><name>X</name><ghr-page>https://e/x</ghr-page>"
                 "<text-list><text><text-role>description</text-role><html><p>Plain <b>bold</b> text.</p></html>"
                 "</text></text-list></health-condition-summary></summaries>")
    assert parse_genetics(f)[0]["sections"][0][1] == ["Plain bold text."]


def test_parse_myhealthfinder():
    pages = parse_myhealthfinder_topic(MHF_TOPIC)
    assert len(pages) == 1
    p = pages[0]
    assert p["title"] == "Get Enough Calcium" and p["url"].startswith("https://odphp.health.gov/")
    assert p["updated"] == "2026-09-10" and p["source"] == "myhealthfinder"
    assert p["sections"][0] == ("The Basics: Overview", ["Calcium is important at every age, but many people don’t get enough."])
    assert p["sections"][1][0] == "Take Action: Vitamin D" and "- Eat fish." in p["sections"][1][1]
    assert parse_myhealthfinder_topic({"Result": {}}) == []


def test_build_offline_matches_contracts(tmp_path, monkeypatch):
    """Whole build with the network and the embedding model faked out."""
    f = tmp_path / "ghr.xml"
    f.write_text(GENETICS_XML)
    gen = parse_genetics(f)
    mhf = parse_myhealthfinder_topic(MHF_TOPIC)
    monkeypatch.setattr(build_multi, "COLLECTORS", {"genetics": lambda raw: gen, "myhealthfinder": lambda raw: mhf})
    rng = np.random.default_rng(0)

    def fake_embed(chunks):
        v = rng.standard_normal((len(chunks), c.DIM)).astype(np.float32)
        return v / np.linalg.norm(v, axis=1, keepdims=True)

    monkeypatch.setattr(build_multi, "embed", fake_embed)
    out = tmp_path / "out"
    monkeypatch.setattr("sys.argv", ["build_multi", "--sources", "genetics,myhealthfinder", "--out", str(out),
                                     "--corpus-version", "test.1"])
    build_multi.main()

    m = json.loads((out / "manifest.json").read_text())
    n = m["num_chunks"]
    assert n >= 2 and m["corpus_version"] == "test.1" and m["quantization"]["scale"] == 127
    assert m["sources"]["genetics"] >= 1 and m["sources"]["myhealthfinder"] >= 1
    assert "ODPHP" in m["attribution"] or "health.gov" in m["attribution"]
    assert (out / "score_table.bin").stat().st_size == n * c.DIM
    store = (out / "fetch_store.bin").read_bytes()
    assert len(store) == n * c.RECORD_BYTES
    recs = [c.unpack_record(store[i * c.RECORD_BYTES:(i + 1) * c.RECORD_BYTES]) for i in range(n)]
    assert [r["id"] for r in recs] == list(range(n))                      # ids dense, in order
    assert struct.unpack("<H", store[:2])[0] < c.RECORD_BYTES             # little-endian length
    assert {r["url"] for r in recs} == {gen[0]["url"], mhf[0]["url"]}
