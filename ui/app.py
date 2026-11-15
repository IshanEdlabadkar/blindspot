"""Blind RAG client UI.

    make demo                      # real crypto + local model (what judges see)
    streamlit run ui/app.py        # same, if server and helper are already running

The UI defaults to the REAL encrypted path. The plaintext mock is only used when
you ask for it (BLIND_RAG_CRYPTO=mock) and is labelled on every answer.

Env: BLIND_RAG_SERVER, BLIND_RAG_CRYPTO, BLIND_RAG_ANSWER, BLIND_RAG_FETCH, BLIND_RAG_EMBED
(see client/pipeline.py), BLIND_RAG_SERVER_LOG (file path or URL of the server's log),
BLIND_RAG_PLAIN_SERVER (B's plaintext demo server, default http://127.0.0.1:8001).
"""
import csv
import hashlib
import html
import json
import os
import pathlib
import random
import re
import sys
from urllib.parse import urlparse

import requests
import streamlit as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BLIND_RAG_CRYPTO", "real")   # the product path; mock must be asked for
os.environ.setdefault("BLIND_RAG_ANSWER", "real")
import contracts as c  # noqa: E402
from client import canned  # noqa: E402
from client.evidence import supporting_excerpt  # noqa: E402
from client.pipeline import Pipeline, PipelineError, health  # noqa: E402

PLAIN_DEFAULT = os.environ.get("BLIND_RAG_PLAIN_SERVER", "http://127.0.0.1:8001")
DECOYS = [
    "Can I take FMLA leave for a pregnancy complication?",
    "What are the symptoms of depression?",
    "How is chlamydia treated and can I get it again?",
    "What is LDL and why is it called the bad kind?",
    "How much salt should I eat in a day?",
    "What is MRSA and how do people catch it?",
]
STAGE_LABEL = {"embedding": "Embedding question on device", "encrypting": "Encrypting on device",
               "scoring": "Server scoring every chunk", "fetching": "Fetching the top chunks",
               "answering": "Writing the answer on device"}

st.set_page_config(page_title="Blind RAG", page_icon=":lock:", layout="wide",
                   initial_sidebar_state="collapsed")
ss = st.session_state
ss.setdefault("history", [])     # list of {"q", "result", "trace", "plain"}
ss.setdefault("error", None)

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Space+Grotesk:wght@500;700&family=JetBrains+Mono:wght@400;500&display=swap');
html, body, .stApp, .stApp p, .stApp label, .stApp input, .stApp button {font-family: Inter, system-ui, sans-serif;}
.stApp {background: #F6F7F9; color: #12151C;}
.block-container {max-width: MAXWpx; padding-top: 4rem; padding-bottom: 3rem;}
header[data-testid="stHeader"] {background: transparent;}
.br-brand {font-family: 'Space Grotesk', system-ui, sans-serif; font-weight: 700; font-size: 24px; line-height: 1.2;}
.br-tag {font-size: 12px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: #1F4FC9; margin-top: 2px;}
.br-mode {display: inline-block; font-size: 12px; font-weight: 600; letter-spacing: .04em; padding: 4px 10px; border-radius: 6px;}
.br-mode.ok {background: #DDF3E4; color: #0B5A2A;}
.br-mode.warn {background: #FDE7C8; color: #7A3A08;}
.br-modeline {font-size: 13px; color: #4A5362; margin: 6px 0 2px;}
.br-health {display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 13px; color: #2B313C; margin: 8px 0 4px;}
.br-health .dot {display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 6px;}
.br-health .up {background: #17803D;} .br-health .down {background: #B42318;}
.br-health code {background: #E6E9EF; padding: 1px 6px; border-radius: 4px; font-size: 12px;}
.br-err {background: #FDECEA; border: 1px solid #F3B8B1; color: #7A1810; border-radius: 12px; padding: 14px 16px; margin: 12px 0;}
.br-err b {display: block; margin-bottom: 4px;}
.br-err code {background: #fff; padding: 2px 6px; border-radius: 4px; color: #12151C; font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 13px;}
.br-empty {color: #4A5362; font-size: 16px; padding: 30px 0 12px;}
.br-turn {display: flex; flex-direction: column; gap: 12px; margin: 18px 0 26px;}
.br-q {align-self: flex-end; max-width: 80%; background: #1F4FC9; color: #fff; padding: 14px 18px;
       border-radius: 16px 16px 4px 16px; font-size: 17px; line-height: 1.4;}
.br-chips {display: flex; flex-wrap: wrap; gap: 8px; font-size: 12px; color: #4A5362; align-items: center;}
.br-chips span.chip {background: #E6E9EF; padding: 5px 10px; border-radius: 999px;}
.br-card {background: #fff; border: 1px solid #DDE1E8; border-radius: 14px; padding: 22px 24px;
          display: flex; flex-direction: column; gap: 14px;}
.br-card.declined {border-color: #E3C58F; background: #FFFBF2;}
.br-urgent {background: #B42318; color: #fff; border-radius: 10px; padding: 12px 16px; margin-bottom: 14px;
            font-weight: 600; line-height: 1.45;}
.br-label {font-family: 'Space Grotesk', system-ui, sans-serif; font-weight: 500; font-size: 13px;
           letter-spacing: .06em; text-transform: uppercase; color: #4A5362;}
.br-answer {font-size: 17px; line-height: 1.6; white-space: pre-wrap; margin: 0;}
.br-answer sup {background: #1F4FC9; color: #fff; border-radius: 4px; padding: 0 5px; font-size: 11px; font-weight: 600; margin-left: 2px;}
.br-src {border: 1px solid #DDE1E8; border-radius: 10px; padding: 12px 14px; font-size: 14px; display: flex; flex-direction: column; gap: 8px;}
.br-src .ttl {display: flex; gap: 10px; align-items: baseline; font-size: 15px;}
.br-src .ttl b {background: #1F4FC9; color: #fff; border-radius: 4px; padding: 0 6px; font-size: 12px;}
.br-src .meta {font-size: 12px; color: #4A5362;}
.br-src a {color: #1F4FC9; word-break: break-all;}
.br-src blockquote {margin: 0; padding: 8px 12px; background: #EEF3FF; border-radius: 6px; color: #12151C; line-height: 1.5;}
.br-src .cap {font-size: 11px; letter-spacing: .05em; text-transform: uppercase; color: #4A5362;}
.br-src details summary {cursor: pointer; color: #1F4FC9; font-size: 13px;}
.br-src details div {margin-top: 6px; color: #2B313C; line-height: 1.55;}
.br-note {font-size: 13px; color: #4A5362;}
.stTextInput div[data-baseweb="input"], .stTextInput div[data-baseweb="base-input"] {min-height: 52px; border-radius: 12px; background: #fff;}
.stTextInput input {font-size: 16px; background: #fff; min-height: 50px;}
.stFormSubmitButton button {height: 52px; border-radius: 12px; font-weight: 600; font-size: 16px; width: 100%; white-space: nowrap;}
[data-testid="stForm"] {border: 0; padding: 0;}
.st-key-server_pane {background: #0B0E14; border-radius: 16px; padding: 28px 30px;}
.br-s {color: #C9D3E3; font-family: 'JetBrains Mono', ui-monospace, monospace; display: flex; flex-direction: column; gap: 20px;}
.br-s .tag {font-family: Inter, system-ui, sans-serif; font-size: 12px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: #F2A33A;}
.br-s .tag.bad {color: #FF8A7A;}
.br-s .lbl {font-size: 12px; color: #8A96A8; margin-bottom: 8px;}
.br-s .box {background: #121722; border: 1px solid #222A38; border-radius: 10px; padding: 16px;}
.br-s .box.plain {border-color: #7A2E26; background: #1D1214;}
.br-s .hex {font-size: 14px; line-height: 1.7; word-break: break-all;}
.br-s .nums {display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 12px;}
.br-s .nums .v {font-size: 22px; color: #fff; white-space: nowrap;}
.br-s .log {font-size: 13px; line-height: 1.9; overflow-x: auto; white-space: pre;}
.br-s .log i {color: #F2A33A; font-style: normal;}
.br-s .wrap {white-space: pre-wrap; word-break: break-word; font-size: 13px; line-height: 1.7;}
.br-s .wrap em {color: #FF8A7A; font-style: normal;}
.br-s .wrap i {color: #F2A33A; font-style: normal;}
.br-s .dim {color: #8A96A8;}
.br-s .cmp {display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; align-items: start;}
.br-s .punch {font-family: 'Space Grotesk', system-ui, sans-serif; font-weight: 700; font-size: 22px; line-height: 1.25; color: #fff; margin-top: 4px;}
.br-grid {display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 14px; margin: 10px 0 22px;}
.br-stat {background: #fff; border: 1px solid #DDE1E8; border-radius: 14px; padding: 18px 20px;}
.br-stat .n {font-family: 'Space Grotesk', system-ui, sans-serif; font-weight: 700; font-size: 34px; line-height: 1.1;}
.br-stat .l {font-size: 14px; margin-top: 6px;}
.br-stat .s {font-size: 12px; color: #4A5362; margin-top: 8px;}
.br-pill {display: inline-block; font-size: 11px; font-weight: 600; letter-spacing: .05em; text-transform: uppercase; padding: 2px 8px; border-radius: 999px; margin-bottom: 8px;}
.br-pill.m {background: #DDF3E4; color: #0B5A2A;} .br-pill.t {background: #E6E9EF; color: #2B313C;} .br-pill.x {background: #FDE7C8; color: #7A3A08;}
.br-h {font-family: 'Space Grotesk', system-ui, sans-serif; font-weight: 700; font-size: 20px; margin: 18px 0 2px;}
.br-sub {color: #4A5362; font-size: 14px; margin-bottom: 6px;}
.br-who {display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 14px; margin: 12px 0 20px;}
.br-who > div {border-radius: 14px; padding: 20px 22px; background: #fff; border: 1px solid #DDE1E8;}
.br-who > div.srv {background: #0B0E14; color: #C9D3E3; border-color: #0B0E14;}
.br-who h4 {margin: 0 0 4px; font-family: 'Space Grotesk', system-ui, sans-serif; font-size: 18px;}
.br-who .srv h4 {color: #fff;}
.br-who ul {margin: 10px 0 0; padding-left: 18px; line-height: 1.7; font-size: 14px;}
.br-who .k {font-size: 12px; letter-spacing: .06em; text-transform: uppercase; font-weight: 600; color: #1F4FC9;}
.br-who .srv .k {color: #F2A33A;}
table.br-t {border-collapse: collapse; width: 100%; font-size: 14px; background: #fff; border: 1px solid #DDE1E8;}
table.br-t th, table.br-t td {text-align: left; padding: 9px 12px; border-bottom: 1px solid #E6E9EF; vertical-align: top;}
table.br-t th {font-size: 12px; letter-spacing: .05em; text-transform: uppercase; color: #4A5362;}
</style>
"""


# ---------------------------------------------------------------- helpers
def esc(x):
    return html.escape(str(x))


def fmt_bytes(n):
    for unit in ("B", "KB", "MB"):
        if n < 1024 or unit == "MB":
            return f"{n:,.0f} {unit}" if unit == "B" else f"{n:,.1f} {unit}"
        n /= 1024


def is_local(url):
    return (urlparse(url).hostname or "") in ("127.0.0.1", "localhost", "::1")


def log_source(server):
    """Where the document server's log is: env override, local file, or the server's public log."""
    src = os.environ.get("BLIND_RAG_SERVER_LOG")
    if src:
        return src
    return str(ROOT / "data" / "server.log") if is_local(server) else server.rstrip("/") + "/v1/server_log"


def log_tail(src, k):
    """Last k log entries, exactly as the server wrote them. [] if unavailable."""
    try:
        if str(src).startswith("http"):
            lines = requests.get(src, params={"n": k}, timeout=5).text.splitlines()
        else:
            p = pathlib.Path(src)
            lines = p.read_text().splitlines() if p.exists() else []
    except (requests.RequestException, OSError):
        return []
    out = []
    for line in lines[-k:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def question_log(src, trace):
    """The server's own log lines for this question: those stamped while it ran.

    Falls back to the last lines if the clocks disagree (remote server).
    """
    entries = log_tail(src, 200)
    lo, hi = trace.get("started_utc", "")[:23], trace.get("ended_utc", "")[:23]
    mine = [e for e in entries if lo and lo <= str(e.get("ts", "")).replace("Z", "")[:23] <= hi
            and e.get("endpoint") != "/v1/manifest"]
    if mine:
        return mine
    return [e for e in entries if e.get("endpoint") != "/v1/manifest"][-len(trace["requests"]):]


@st.cache_data(ttl=8, show_spinner=False)
def cached_health(server, crypto_kind, answer_kind):
    return health(server, crypto_kind, answer_kind)


def get_pipeline(server):
    if ss.get("pipeline_server") != server:
        ss.pipeline, ss.pipeline_server = Pipeline(server=server), server
    return ss.pipeline


def mode_text(mode, planned=False):
    """(badge text, css class, detail line) from what the pipeline REALLY ran (or will run)."""
    if mode is None:
        return "CANNED · layout only, nothing was sent", "warn", "Fixed sample output. No server, no crypto, no model."
    parts = []
    if mode["crypto"] == "mock":
        badge, cls = "MOCK · NOT PRIVATE", "warn"
        parts.append("the question goes unencrypted to the development mock" if planned
                     else "the question was sent unencrypted to the development mock")
    else:
        badge, cls = "REAL ENCRYPTED SEARCH", "ok"
        parts.append("encrypted scoring" + (f" ({mode['score']} mode)" if mode.get("score") else ""))
    parts.append("PIR fetch" if mode["fetch"] == "pir" else "download-all fetch (whole store, not PIR)")
    parts.append("local model" if mode["answer"] == "real" else "stub answer, no language model")
    if mode.get("embed") == "fake":
        parts.append("FAKE embedding, retrieval is meaningless")
    return badge, cls, " · ".join(parts)


def answer_html(text):
    out = esc(text)
    return re.sub(r"\[(\d+)\]", r"<sup>\1</sup>", out)


def turn_html(t):
    q, result, trace = t["q"], t["result"], t["trace"]
    badge, cls, detail = mode_text(trace["mode"] if trace else None)
    chips = f'<div class="br-chips"><span class="br-mode {cls}">{esc(badge)}</span>'
    if trace:
        chips += (f'<span class="chip">{trace["num_chunks"]:,} chunks scored</span>'
                  f'<span class="chip">{trace["total_seconds"]:.2f} s</span>')
    chips += f'</div><div class="br-modeline">{esc(detail)}</div>'

    answer = result["answer"]
    for d in ("This is general health information, not medical advice.", c.DISCLAIMER):
        answer = answer.replace(d, "").strip()
    # B's answer() flags crisis/emergency questions (988 / 911). Show it on every card, answered or
    # declined, and keep it out of the answer text so it isn't shown twice.
    urgent = result.get("urgent") or None
    urgent_html = ""
    if urgent and urgent.get("message"):
        answer = answer.replace(urgent["message"], "").strip()
        urgent_html = f'<div class="br-urgent">{esc(urgent["message"])}</div>'
    srcs = ""
    for i, cit in enumerate(result["citations"], 1):
        url = str(cit.get("url") or "")
        link = (f'<a href="{esc(url)}" target="_blank" rel="noopener">{esc(url)}</a>'
                if url.startswith(("http://", "https://")) else "")
        meta = []
        if cit.get("updated"):
            meta.append(f'updated {esc(cit["updated"])}')
        if isinstance(cit.get("score"), float) and 0 < cit["score"] <= 1:
            meta.append(f'similarity {cit["score"]:.2f}')
        # B's answer() verifies each cited sentence and returns the matching source sentence; use it.
        # Otherwise (stub answer) fall back to a word-overlap pointer.
        exc = "" if result["declined"] else (cit.get("excerpt") or supporting_excerpt(answer, i, cit.get("text", "")))
        exc_html = (f'<div class="cap">Closest sentence in the source</div><blockquote>{esc(exc)}</blockquote>'
                    if exc else "")
        srcs += (f'<div class="br-src"><div class="ttl"><b>{i}</b><span>{esc(cit.get("title"))}</span></div>'
                 f'<div class="meta">{link}{" · " if link and meta else ""}{" · ".join(meta)}</div>{exc_html}'
                 f'<details><summary>Full passage</summary><div>{esc(cit.get("text"))}</div></details></div>')
    if result["declined"]:
        body = ('<div class="br-label">No reliable source found</div>'
                '<p class="br-answer">The library did not contain a passage that answers this, so no answer was '
                'written. These are the closest passages.</p>')
        card = "br-card declined"
    else:
        body = f'<div class="br-label">Answer</div><p class="br-answer">{answer_html(answer)}</p>'
        card = "br-card"
    return (f'<div class="br-turn"><div class="br-q">{esc(q)}</div>{chips}'
            f'<div class="{card}">{urgent_html}{body}{srcs}'
            f'<div class="br-note">{esc(c.DISCLAIMER)}</div></div></div>')


def server_html(t, src):
    trace, plain = t["trace"], t.get("plain")
    real = trace["mode"]["crypto"] == "real"
    rows = question_log(src, trace)
    lines = [f'{esc(str(r.get("ts", ""))[11:23])}  {esc(r.get("endpoint", ""))}  '
             f'<i>{r.get("response_bytes", 0):,} B</i>  {r.get("latency_ms", "")} ms' for r in rows[:5]]
    if len(rows) > 5:
        lines.append(f'<span class="dim">… {len(rows) - 5} more lines, same four fields</span>')
    log = "\n".join(lines) or f'<span class="dim">no log available at {esc(src)}</span>'
    hx = trace["ciphertext_sample"]
    hx = " ".join(hx[i:i + 32] for i in range(0, len(hx), 32))
    head = ('<div class="tag">The Blind RAG server · sees only this</div>' if real else
            '<div class="tag bad">Development mock · this server is NOT blind</div>')
    qlabel = "question, as received (ciphertext)" if real else "question, as received (UNENCRYPTED embedding bytes)"
    punch = ('<div class="punch">No question. No scores.<br>No record of what you read.</div>' if real else
             '<div class="punch">Mock mode proves nothing about privacy.</div>')
    blind_box = ('<div><div class="tag">Blind RAG\'s server logged</div>'
                 f'<div class="lbl" style="margin-top:8px">everything it keeps</div><div class="box wrap">{log}</div></div>')
    if plain is not None:
        if plain.get("error"):
            pbox = f'<div class="box plain wrap"><span class="dim">{esc(plain["error"])}</span></div>'
        else:
            e = plain["entry"]
            returned = "\n".join(f'  - {esc(x.get("title"))}' for x in e.get("returned", [])[:5]) or "  (none)"
            pbox = (f'<div class="box plain wrap">{esc(str(e.get("time", ""))[11:19])}  {esc(e.get("endpoint", ""))}\n'
                    f'question: <em>{esc(e.get("question", ""))}</em>\n'
                    f'returned:\n{returned}</div>')
        blind_box = ('<div class="cmp"><div><div class="tag bad">A normal RAG server logged</div>'
                     f'<div class="lbl" style="margin-top:8px">same question, read from it just now</div>{pbox}</div>'
                     f'{blind_box}</div>')
    cmp_html = ""
    return f"""<div class="br-s">
{head}
<div><div class="lbl">{qlabel}</div><div class="box hex">{hx} …</div></div>
<div class="nums">
<div class="box"><div class="lbl">sent</div><div class="v">{fmt_bytes(trace["upload_bytes"])}</div></div>
<div class="box"><div class="lbl">received</div><div class="v">{fmt_bytes(trace["download_bytes"])}</div></div>
<div class="box"><div class="lbl">total</div><div class="v">{trace["total_seconds"]:.2f} s</div></div>
</div>
{blind_box}
{cmp_html}
{punch}
</div>"""


def ask_plain_server(url, question):
    """Send the question to B's plaintext demo server and read back what it logged. Real data only."""
    try:
        requests.post(url + "/ask", json={"question": question}, timeout=180).raise_for_status()
        entries = requests.get(url + "/log", timeout=10).json()
        mine = [e for e in entries if e.get("question") == question]
        if not mine:
            return {"error": "The plaintext server answered but its log has no entry for this question."}
        return {"entry": mine[-1]}
    except requests.RequestException:
        return {"error": f"Plaintext demo server not reachable at {url}. Start it: python3.12 -m baseline.server"}


# ---------------------------------------------------------------- evidence data
def load_retrieval():
    p = ROOT / "eval" / "results" / "retrieval.csv"
    if not p.exists():
        return None
    rows = [r for r in csv.DictReader(open(p, newline="", encoding="utf-8")) if r.get("gold")]
    out = {"n": len(rows), "path": "eval/results/retrieval.csv"}
    for m in ("float", "int8"):
        ranks = [int(r[f"{m}_rank"]) if (r.get(f"{m}_rank") or "").isdigit() else None for r in rows]
        out[m] = {k: sum(1 for x in ranks if x and x <= k) for k in (1, 5, 10)}
    return out if rows else None


def load_answers():
    p = ROOT / "eval" / "results" / "answers.jsonl"
    if not p.exists():
        return None
    rows = [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()]
    ans = [r for r in rows if r.get("source_url")]
    un = [r for r in rows if not r.get("source_url")]
    ms = sorted(r["timings"]["answer_ms"] for r in rows if r.get("timings", {}).get("answer_ms"))
    return {"answerable": len(ans), "answered": sum(r["status"] == "answered" for r in ans),
            "gold_cited": sum(bool(r.get("gold_cited")) for r in ans),
            "unanswerable": len(un), "declined": sum(r["status"] == "declined" for r in un),
            "median_answer_s": ms[len(ms) // 2] / 1000 if ms else None, "path": "eval/results/answers.jsonl"}


def load_measurements():
    """Rows of A's `make measure` table: Metric | Target | Measured | Met."""
    p = ROOT / "data" / "measurements.md"
    if not p.exists():
        return None
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        cells = [x.strip() for x in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) >= 3 and cells[0] not in ("Metric", "") and not set(cells[0]) <= set("-: "):
            rows.append((cells + [""])[:4])
    return rows or None


def stat(n, label, sub, kind="m"):
    pill = {"m": "Measured", "t": "Target", "x": "Not measured yet"}[kind]
    return (f'<div class="br-stat"><span class="br-pill {kind}">{pill}</span><div class="n">{esc(n)}</div>'
            f'<div class="l">{esc(label)}</div><div class="s">{sub}</div></div>')


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Settings")
    backend = st.radio("Backend", ["Pipeline", "Canned (layout only)"], key="backend")
    server = st.text_input("Document server", os.environ.get("BLIND_RAG_SERVER", "http://127.0.0.1:8080"))
    plain_url = st.text_input("Plaintext demo server", PLAIN_DEFAULT).rstrip("/")
    st.caption(f"requested: crypto `{os.environ['BLIND_RAG_CRYPTO']}` · answer `{os.environ['BLIND_RAG_ANSWER']}` · "
               f"fetch `{os.environ.get('BLIND_RAG_FETCH', 'auto')}` · embed `{os.environ.get('BLIND_RAG_EMBED', 'real')}`")
    if st.button("New session (wipe key and history)"):
        if "pipeline" in ss:
            ss.pipeline.close()
        for k in ("pipeline", "pipeline_server"):
            ss.pop(k, None)
        ss.history, ss.error = [], None
        st.rerun()

canned_mode = backend.startswith("Canned")
want_mock = os.environ["BLIND_RAG_CRYPTO"] != "real"
want_stub = os.environ["BLIND_RAG_ANSWER"] != "real"

# ---------------------------------------------------------------- header
head_l, head_r = st.columns([3, 2], vertical_alignment="center")
with head_r:
    show_server = st.toggle("Show what the server saw", key="show_server")
st.markdown(CSS.replace("MAXW", "1280" if show_server else "820"), unsafe_allow_html=True)
with head_l:
    st.markdown('<div class="br-brand">Blind RAG</div>'
                '<div class="br-tag">Your device · holds the only key</div>', unsafe_allow_html=True)

if canned_mode:
    cur = None
else:
    cur = {"crypto": "mock" if want_mock else "real", "fetch": os.environ.get("BLIND_RAG_FETCH", "download"),
           "answer": "stub" if want_stub else "real", "embed": os.environ.get("BLIND_RAG_EMBED", "real"), "score": ""}
badge, cls, detail = mode_text(cur, planned=True)
st.markdown(f'<div style="margin-top:10px"><span class="br-mode {cls}">Next question runs as: {esc(badge)}</span>'
            f'<div class="br-modeline">{esc(detail)}</div></div>', unsafe_allow_html=True)

if not canned_mode:
    items = cached_health(server, "mock" if want_mock else "real", "stub" if want_stub else "real")
    st.markdown('<div class="br-health">' + "".join(
        f'<span><span class="dot {"up" if h["ok"] else "down"}"></span><b>{esc(h["name"])}</b>: {esc(h["detail"])}'
        + (f' &nbsp;fix: <code>{esc(h["fix"])}</code>' if h["fix"] else "") + "</span>" for h in items)
        + "</div>", unsafe_allow_html=True)

tab_ask, tab_evidence, tab_who = st.tabs(["Ask", "Evidence", "Who sees what"])

# ---------------------------------------------------------------- ask
with tab_ask:
    if show_server:
        left, right = st.columns([11, 9], gap="large")
    else:
        left, right = st.container(), None

    with left:
        history_box = st.container()
        status_box = st.container()
        compare = False
        if show_server and not canned_mode:
            compare = st.checkbox("Demo contrast: also send the question to a normal (plaintext) RAG server",
                                  help="Off by default. When on, the question really is sent in the clear to the "
                                       "plaintext demo server so its log can be shown next to Blind RAG's.")
        with st.form("ask", clear_on_submit=True):
            f1, f2 = st.columns([7, 3], vertical_alignment="bottom")
            question = f1.text_input("Your question", placeholder="Ask a sensitive question",
                                     label_visibility="collapsed")
            go = f2.form_submit_button("Ask privately", type="primary")
        if go and question.strip():
            question, ss.error = question.strip(), None
            try:
                if canned_mode:
                    turn = {"q": question, "result": c.normalize_result(canned.ask(question)), "trace": None}
                else:
                    with status_box.status("Working…", expanded=True) as status:
                        def on_stage(name, secs):
                            st.write(f"{STAGE_LABEL[name]} · {secs:.2f} s")
                        try:
                            result, trace = get_pipeline(server).ask_traced(question, on_stage)
                        except Exception:
                            status.update(label="Stopped: no answer", state="error", expanded=False)
                            raise
                        turn = {"q": question, "result": result, "trace": trace}
                        if compare:
                            st.write("Sending the same question to the plaintext server…")
                            turn["plain"] = ask_plain_server(plain_url, question)
                        status.update(label=f"Done in {trace['total_seconds']:.2f} s", state="complete",
                                      expanded=False)
                ss.history.append(turn)
            except PipelineError as e:
                ss.error = {"stage": e.stage, "message": e.message, "fix": e.fix, "q": question}
            except Exception as e:  # noqa: BLE001
                ss.error = {"stage": "unexpected", "message": f"{type(e).__name__}: {e}", "fix": "", "q": question}
        with history_box:
            if not ss.history and not ss.error:
                st.markdown('<div class="br-empty">Ask a sensitive question. The server never sees it, '
                            'the scores, or what you read.</div>', unsafe_allow_html=True)
            st.markdown("".join(turn_html(t) for t in ss.history), unsafe_allow_html=True)
            if ss.error:
                e = ss.error
                fix = f'<br>Fix: <code>{esc(e["fix"])}</code>' if e["fix"] else ""
                st.markdown(f'<div class="br-err"><b>No answer for “{esc(e["q"])}” (failed at: {esc(e["stage"])})</b>'
                            f'{esc(e["message"])}{fix}<br><span style="font-size:13px">Nothing was retried in a '
                            f'weaker mode.</span></div>', unsafe_allow_html=True)

    last = next((t for t in reversed(ss.history) if t["trace"]), None)
    if right is not None:
        with right:
            with st.container(key="server_pane"):
                if last:
                    st.markdown(server_html(last, log_source(server)), unsafe_allow_html=True)
                else:
                    st.markdown('<div class="br-s"><div class="tag">The server · sees only this</div>'
                                '<div class="dim">Ask a question to see what crosses the network.</div></div>',
                                unsafe_allow_html=True)
            if last:
                q, trace = last["q"], last["trace"]
                with st.expander("Attacker console: guess which question was asked"):
                    if trace["mock"]:
                        st.caption("Mock mode: this game only means something against the real encrypted server.")
                    rng = random.Random(hashlib.sha256(q.encode()).digest())
                    options = rng.sample([d for d in DECOYS if d != q], 4) + [q]
                    rng.shuffle(options)
                    guess = st.radio("You hold the server's database and logs. Which was it?", options,
                                     index=None, key=f"guess-{q}")
                    if st.button("Check guess") and guess:
                        if guess == q:
                            st.success("Correct, by luck: a 1 in 5 guess. Nothing on the server pointed to it.")
                        else:
                            st.error("Wrong. Nothing on the server distinguishes these five questions.")
                        st.write(f"The question was: **{q}**")

# ---------------------------------------------------------------- evidence
with tab_evidence:
    st.markdown('<div class="br-h">What we measured</div><div class="br-sub">Every number names its file. '
                '“Target” is a goal from the spec, not a result.</div>', unsafe_allow_html=True)

    traces = [t["trace"] for t in ss.history if t["trace"]]
    if traces:
        tr = traces[-1]
        b, cl, _ = mode_text(tr["mode"])
        cards = (stat(fmt_bytes(tr["upload_bytes"]), "uploaded for your last question", f"this session · {esc(b)}")
                 + stat(fmt_bytes(tr["download_bytes"]), "downloaded for your last question",
                        "includes one-time downloads on a first question")
                 + stat(f'{tr["timings"].get("scoring", 0) + tr["timings"].get("encrypting", 0):.2f} s',
                        "encrypt + server scoring", "this session")
                 + stat(f'{tr["total_seconds"]:.2f} s', "end to end", f'{len(traces)} question(s) this session'))
        st.markdown('<div class="br-h">This session, live</div><div class="br-grid">' + cards + "</div>",
                    unsafe_allow_html=True)

    st.markdown('<div class="br-h">Privacy cost</div><div class="br-sub">From <code>make measure</code> on this '
                'machine (<code>data/measurements.md</code>).</div>', unsafe_allow_html=True)
    meas = load_measurements()
    if meas:
        body = "".join(f"<tr><td>{esc(a)}</td><td>{esc(b)}</td><td><b>{esc(m)}</b></td><td>{esc(ok)}</td></tr>"
                       for a, b, m, ok in meas)
        st.markdown('<table class="br-t"><tr><th>Metric</th><th>Target (spec)</th><th>Measured</th><th>Met</th></tr>'
                    + body + "</table>", unsafe_allow_html=True)
    else:
        st.markdown('<div class="br-grid">' + stat("—", "crypto latency, bytes and server CPU",
                    "Run <code>make measure</code> with the server and helper up. Targets: under 10 s end to end, "
                    "under 5 MB up, under 20 MB down.", "x") + "</div>", unsafe_allow_html=True)

    st.markdown('<div class="br-h">Retrieval and answer quality</div><div class="br-sub">Plaintext baseline over the '
                'same chunks. Encryption adds no error, so the int8 ranking is the ranking Blind RAG produces.</div>',
                unsafe_allow_html=True)
    ret, ans = load_retrieval(), load_answers()
    cards = ""
    if ret:
        n = ret["n"]
        cards += stat(f'{ret["int8"][10]}/{n}', "correct source in the top 10 (int8, what the server scores)",
                      f'top 5: {ret["int8"][5]}/{n} · top 1: {ret["int8"][1]}/{n} · <code>{ret["path"]}</code>')
        cards += stat(f'{ret["float"][10]}/{n}', "same, with unquantized float embeddings",
                      f'top 5: {ret["float"][5]}/{n} · top 1: {ret["float"][1]}/{n} · shows what int8 costs')
    else:
        cards += stat("—", "retrieval recall", "Run <code>python -m eval.run_eval</code>", "x")
    if ans:
        cards += stat(f'{ans["answered"]}/{ans["answerable"]}', "answerable questions answered",
                      f'{ans["gold_cited"]}/{ans["answerable"]} cited the expected source · <code>{ans["path"]}</code>')
        cards += stat(f'{ans["declined"]}/{ans["unanswerable"]}', "off-topic questions correctly declined",
                      "no answer is written when no reliable source is found")
        if ans["median_answer_s"]:
            cards += stat(f'{ans["median_answer_s"]:.1f} s', "median local answer time", "from B's eval run, warm model")
    else:
        cards += stat("—", "answer outcomes", "Run <code>python -m eval.run_eval --answers</code>", "x")
    st.markdown('<div class="br-grid">' + cards + "</div>", unsafe_allow_html=True)
    st.caption("Small evaluation set. These are not medically validated accuracy figures.")

# ---------------------------------------------------------------- who sees what
with tab_who:
    st.markdown("""
<div class="br-h">Who sees what</div>
<div class="br-sub">The claim is narrow on purpose: the document server never gets a readable question.</div>
<div class="br-who">
  <div><div class="k">Your device</div><h4>Sees everything</h4>
    <ul><li>Your question, in words</li><li>Every relevance score and the ranking</li>
    <li>The passages it read</li><li>The answer</li><li>The only secret key, in memory, new for each question</li></ul></div>
  <div><div class="k">The network</div><h4>Sees ciphertext</h4>
    <ul><li>Encrypted question and encrypted scores</li><li>How many bytes moved, and when</li>
    <li>Your IP address and the server's</li></ul></div>
  <div class="srv"><div class="k">The document server</div><h4>Computes without reading</h4>
    <ul><li>Receives the question as ciphertext it cannot open</li>
    <li>Scores every chunk, so it cannot tell which ones matter</li>
    <li>Returns scores it cannot read or compare</li>
    <li>Logs four fields: time, endpoint, response size, latency</li></ul></div>
</div>
<div class="br-h">What stays visible</div>
<table class="br-t">
<tr><th>Still observable</th><th>By whom</th><th>What we do about it</th></tr>
<tr><td>That a question was asked, and when</td><td>Server, network</td><td>Nothing in this version</td></tr>
<tr><td>Your IP address</td><td>Server, network</td><td>Use a VPN or Tor</td></tr>
<tr><td>Request and response sizes</td><td>Server, network</td><td>Sizes are the same for every question</td></tr>
<tr><td>The whole library</td><td>Every asker</td><td>Accepted: the library is public</td></tr>
</table>
<div class="br-h">How passages are fetched</div>
<div class="br-sub"><b>Default: download-all.</b> The device downloads the entire fetch store once and reads the
top 10 locally, so the server has no selection to observe. This is not PIR; it works because the library is small.
<b>Optional: PIR fetch</b> (<code>BLIND_RAG_FETCH=pir</code>) retrieves each passage with an encrypted selector.
Each answer above says which one was used.</div>
<div class="br-h">What we do not claim</div>
<div class="br-sub">Not zero leakage: timing, IP and sizes are visible. Not medically validated answers.
Not a security-reviewed implementation: the cryptography libraries are research prototypes.
Not the first private retrieval system: this builds on Tiptoe and SimplePIR.</div>
""", unsafe_allow_html=True)
