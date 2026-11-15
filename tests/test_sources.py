import pytest

from ingest import sources
from ingest.extract import parse_topics
from ingest.sources import fmla

ECFR = """<?xml version="1.0"?>
<DIV5 N="825" TYPE="PART">
 <HEAD>PART 825—THE FAMILY AND MEDICAL LEAVE ACT OF 1993</HEAD>
 <DIV6 N="B" TYPE="SUBPART">
  <HEAD>Subpart B—Employee Leave Entitlements Under the Family and Medical Leave Act</HEAD>
  <DIV8 N="825.120" TYPE="SECTION">
   <HEAD>§ 825.120 Leave for pregnancy or birth.</HEAD>
   <P>(a) <I>General rules.</I> Eligible employees are entitled to FMLA leave for pregnancy or birth of a child.</P>
   <P>(4) An expectant mother may take FMLA leave
      before the birth of the child for prenatal care.</P>
  </DIV8>
  <DIV8 N="825.121" TYPE="SECTION">
   <HEAD>§ 825.121 [Reserved]</HEAD>
  </DIV8>
 </DIV6>
</DIV5>"""


def test_fmla_parse_one_page_per_section(tmp_path):
    p = tmp_path / "ecfr_29cfr825_2026-11-10.xml"
    p.write_text(ECFR)
    pages, date = fmla.parse(p)
    assert date == "2026-11-10"
    assert len(pages) == 1
    pg = pages[0]
    assert pg["title"] == "29 CFR 825.120 Leave for pregnancy or birth."
    assert pg["url"] == "https://www.ecfr.gov/current/title-29/section-825.120"
    assert pg["updated"] == "2026-11-10"
    assert pg["also_called"] == ["Employee Leave Entitlements Under the Family and Medical Leave Act"]
    assert pg["sections"] == [(None, [
        "(a) General rules. Eligible employees are entitled to FMLA leave for pregnancy or birth of a child.",
        "(4) An expectant mother may take FMLA leave before the birth of the child for prenatal care.",
    ])]


def test_genetics_adapter_parses_c_fixture_with_a_date(tmp_path):
    import json as _json
    from tests.test_sources_extra import GENETICS_XML
    p = tmp_path / "ghr-summaries.xml"
    p.write_text(GENETICS_XML)
    pages, date = sources.get("genetics").parse(p)
    assert [pg["title"] for pg in pages] == ["Alzheimer disease"]
    assert len(date) == 10 and date[4] == "-"


def test_myhealthfinder_adapter_reads_a_cached_folder(tmp_path):
    import json as _json
    from tests.test_sources_extra import MHF_TOPIC
    d = tmp_path / "myhealthfinder"
    d.mkdir()
    (d / "itemlist.json").write_text("{}")
    (d / "topic-30530.json").write_text(_json.dumps(MHF_TOPIC))
    pages, date = sources.get("myhealthfinder").parse(d)
    assert [pg["title"] for pg in pages] == ["Get Enough Calcium"] and len(date) == 10


def test_c_names_still_import_from_ingest_sources():
    from ingest.sources import ATTRIBUTION, COLLECTORS, parse_genetics, parse_myhealthfinder_topic  # noqa: F401
    assert set(COLLECTORS) == {"genetics", "myhealthfinder"} and "medlineplus" in ATTRIBUTION


def test_registry_and_metadata():
    for sid in ("medlineplus", "fmla", "genetics", "myhealthfinder"):
        mod = sources.get(sid)
        assert mod.SOURCE_ID == sid
        for attr in ("SOURCE_NAME", "CORPUS_NAME", "ATTRIBUTION"):
            assert getattr(mod, attr)
        assert callable(mod.fetch) and callable(mod.parse)
    assert set(sources.ALL) >= {"medlineplus", "fmla"}
    with pytest.raises(KeyError):
        sources.get("nope")


def test_medlineplus_adapter_delegates_to_parse_topics(tmp_path):
    from tests.test_extract import XML
    p = tmp_path / "m.xml"
    p.write_text(XML)
    assert sources.get("medlineplus").parse(p) == parse_topics(p)
