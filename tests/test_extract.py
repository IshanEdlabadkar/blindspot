from ingest.extract import parse_topics

XML = """<?xml version="1.0"?>
<health-topics total="3" date-generated="11/13/2026 08:58:25">
 <health-topic title="Asthma" url="https://medlineplus.gov/asthma.html" id="1" language="English" date-created="01/01/2010">
  <also-called>Bronchial asthma</also-called>
  <full-summary>&lt;p&gt;Asthma is a &lt;a href="x"&gt;lung&lt;/a&gt; disease.&lt;/p&gt;
&lt;h3&gt;Symptoms&lt;/h3&gt;&lt;ul&gt;&lt;li&gt;Wheezing&lt;/li&gt;&lt;li&gt;Coughing&lt;/li&gt;&lt;/ul&gt;
&lt;table&gt;&lt;tr&gt;&lt;th&gt;Level&lt;/th&gt;&lt;th&gt;Meaning&lt;/th&gt;&lt;/tr&gt;&lt;/table&gt;</full-summary>
 </health-topic>
 <health-topic title="Asma" url="https://medlineplus.gov/spanish/asthma.html" id="2" language="Spanish" date-created="01/01/2010">
  <full-summary>&lt;p&gt;El asma&lt;/p&gt;</full-summary>
 </health-topic>
 <health-topic title="Empty" url="https://medlineplus.gov/empty.html" id="3" language="English" date-created="01/01/2010">
 </health-topic>
</health-topics>"""


def test_parse_topics(tmp_path):
    p = tmp_path / "t.xml"
    p.write_text(XML)
    pages, generated = parse_topics(p)
    assert generated == "2026-11-13"
    assert [pg["title"] for pg in pages] == ["Asthma"]
    pg = pages[0]
    assert pg["updated"] == "2026-11-13"
    assert pg["also_called"] == ["Bronchial asthma"]
    assert pg["sections"] == [
        (None, ["Asthma is a lung disease."]),
        ("Symptoms", ["- Wheezing", "- Coughing", "Level | Meaning"]),
    ]
