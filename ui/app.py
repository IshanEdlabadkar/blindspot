"""Blind RAG client UI (design A: your device, with the server's view behind a toggle).

    streamlit run ui/app.py

Env: BLIND_RAG_SERVER, BLIND_RAG_CRYPTO, BLIND_RAG_ANSWER, BLIND_RAG_FETCH,
BLIND_RAG_EMBED (see client/pipeline.py) and BLIND_RAG_SERVER_LOG (path to the
server's log file, default data/server.log).
"""
import hashlib
import html
import json
import os
import pathlib
import random
import sys

import streamlit as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import contracts as c  # noqa: E402
from client import canned  # noqa: E402
from client.pipeline import Pipeline  # noqa: E402

LOG_PATH = pathlib.Path(os.environ.get("BLIND_RAG_SERVER_LOG", ROOT / "data" / "server.log"))
DECOYS = [
    "Can I take FMLA leave for a pregnancy complication?",
    "What are the symptoms of depression?",
    "How is chlamydia treated?",
    "What does a high A1C result mean?",
    "How do I lower my blood pressure?",
    "What are the side effects of chemotherapy?",
]
STAGE_LABEL = {"embedding": "Embedding question on device", "encrypting": "Encrypting",
               "scoring": "Scoring every chunk (encrypted)", "fetching": "Private fetch of top chunks",
               "answering": "Writing answer on device"}

st.set_page_config(page_title="Blind RAG", page_icon=":lock:", layout="wide",
                   initial_sidebar_state="collapsed")
ss = st.session_state
ss.setdefault("history", [])   # list of (question, result, trace)

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Space+Grotesk:wght@500;700&family=JetBrains+Mono:wght@400;500&display=swap');
html, body, .stApp, .stApp p, .stApp label, .stApp input, .stApp button {font-family: Inter, system-ui, sans-serif;}
.stApp {background: #F6F7F9; color: #12151C;}
.block-container {max-width: MAXWpx; padding-top: 4rem; padding-bottom: 3rem;}
header[data-testid="stHeader"] {background: transparent;}
.br-brand {font-family: 'Space Grotesk', system-ui, sans-serif; font-weight: 700; font-size: 24px; line-height: 1.2;}
.br-tag {font-size: 12px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: #1F4FC9; margin-top: 2px;}
.br-mock {font-size: 13px; color: #7A3A08; background: #FDF1E3; border-radius: 8px; padding: 8px 12px; margin: 6px 0 2px;}
.br-empty {color: #4A5362; font-size: 16px; padding: 36px 0 12px;}
.br-turn {display: flex; flex-direction: column; gap: 14px; margin: 18px 0 26px;}
.br-q {align-self: flex-end; max-width: 80%; background: #1F4FC9; color: #fff; padding: 14px 18px;
       border-radius: 16px 16px 4px 16px; font-size: 17px; line-height: 1.4;}
.br-chips {display: flex; flex-wrap: wrap; gap: 8px; font-size: 12px; color: #4A5362;}
.br-chips span {background: #E6E9EF; padding: 5px 10px; border-radius: 999px;}
.br-card {background: #fff; border: 1px solid #DDE1E8; border-radius: 14px; padding: 22px 24px;
          display: flex; flex-direction: column; gap: 14px;}
.br-label {font-family: 'Space Grotesk', system-ui, sans-serif; font-weight: 500; font-size: 13px;
           letter-spacing: .06em; text-transform: uppercase; color: #4A5362;}
.br-answer {font-size: 17px; line-height: 1.55; white-space: pre-wrap; margin: 0;}
.br-src {border: 1px solid #DDE1E8; border-radius: 10px; font-size: 15px;}
.br-src summary {cursor: pointer; padding: 12px 14px; min-height: 20px; list-style: none; display: flex; gap: 10px;}
.br-src summary::-webkit-details-marker {display: none;}
.br-src summary b {font-weight: 600;}
.br-src div {padding: 0 14px 14px; color: #2B313C; font-size: 14px; line-height: 1.55;}
.br-src a {color: #1F4FC9; word-break: break-all;}
.br-note {font-size: 13px; color: #4A5362;}
.stTextInput div[data-baseweb="input"] {height: 52px; border-radius: 12px; background: #fff;}
.stTextInput input {font-size: 16px; background: #fff;}
.stFormSubmitButton button {height: 52px; border-radius: 12px; font-weight: 600; font-size: 16px; width: 100%; white-space: nowrap;}
[data-testid="stForm"] {border: 0; padding: 0;}
.st-key-server_pane {background: #0B0E14; border-radius: 16px; padding: 28px 30px;}
.br-s {color: #C9D3E3; font-family: 'JetBrains Mono', ui-monospace, monospace; display: flex; flex-direction: column; gap: 20px;}
.br-s .tag {font-family: Inter, system-ui, sans-serif; font-size: 12px; font-weight: 600; letter-spacing: .08em;
            text-transform: uppercase; color: #F2A33A;}
.br-s .lbl {font-size: 12px; color: #8A96A8; margin-bottom: 8px;}
.br-s .box {background: #121722; border: 1px solid #222A38; border-radius: 10px; padding: 16px;}
.br-s .hex {font-size: 14px; line-height: 1.7; word-break: break-all;}
.br-s .nums {display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 12px;}
.br-s .nums .v {font-size: 22px; color: #fff; white-space: nowrap;}
.br-s .log {font-size: 13px; line-height: 1.9; overflow-x: auto; white-space: pre;}
.br-s .log i {color: #F2A33A; font-style: normal;}
.br-s .dim {color: #8A96A8;}
.br-s .punch {font-family: 'Space Grotesk', system-ui, sans-serif; font-weight: 700; font-size: 24px;
              line-height: 1.25; color: #fff; margin-top: 6px;}
</style>
"""


def esc(x):
    return html.escape(str(x))


def fmt_bytes(n):
    for unit in ("B", "KB", "MB"):
        if n < 1024 or unit == "MB":
            return f"{n:,.0f} {unit}" if unit == "B" else f"{n:,.1f} {unit}"
        n /= 1024


def log_tail(k):
    if not LOG_PATH.exists():
        return []
    out = []
    for line in LOG_PATH.read_text().splitlines()[-k:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def get_pipeline(server):
    if ss.get("pipeline_server") != server:
        ss.pipeline, ss.pipeline_server = Pipeline(server=server), server
    return ss.pipeline


def turn_html(q, result, trace):
    chips = ""
    if trace:
        chips = ('<div class="br-chips"><span>Encrypted on device</span>'
                 f'<span>{trace["num_chunks"]:,} chunks scored blind</span>'
                 f'<span>{trace["top_k"]} fetched privately</span>'
                 f'<span>Answered on device · {trace["total_seconds"]:.2f} s</span></div>')
    srcs = ""
    for i, cit in enumerate(result["citations"], 1):
        url = str(cit.get("url") or "")
        link = f'<a href="{esc(url)}" target="_blank" rel="noopener">{esc(url)}</a>' \
            if url.startswith(("http://", "https://")) else ""
        srcs += (f'<details class="br-src"><summary><b>{i}</b><span>{esc(cit.get("title"))}</span></summary>'
                 f'<div>{esc(cit.get("text"))}<br>{link}</div></details>')
    label = "Closest passages" if result["declined"] else "Answer"
    return (f'<div class="br-turn"><div class="br-q">{esc(q)}</div>{chips}'
            f'<div class="br-card"><div class="br-label">{label}</div>'
            f'<p class="br-answer">{esc(result["answer"])}</p>{srcs}'
            f'<div class="br-note">{esc(c.DISCLAIMER)}</div></div></div>')


def server_html(trace):
    n = len(trace["requests"])
    rows = log_tail(n)
    lines = [f'{esc(r["ts"][11:])}  {esc(r["endpoint"]):<11} <i>{r["response_bytes"]:>6} B</i>  {r["latency_ms"]} ms'
             for r in rows[:4]]
    if len(rows) > 4:
        lines.append(f'<span class="dim">… {len(rows) - 4} more, all the same size</span>')
    log = "\n".join(lines) or f'<span class="dim">no log at {esc(LOG_PATH)}</span>'
    hx = trace["ciphertext_sample"]
    hx = " ".join(hx[i:i + 32] for i in range(0, len(hx), 32))
    return f"""<div class="br-s">
<div class="tag">The server · sees only this</div>
<div><div class="lbl">question, as received</div><div class="box hex">{hx} …</div></div>
<div class="nums">
<div class="box"><div class="lbl">sent</div><div class="v">{fmt_bytes(trace["upload_bytes"])}</div></div>
<div class="box"><div class="lbl">received</div><div class="v">{fmt_bytes(trace["download_bytes"])}</div></div>
<div class="box"><div class="lbl">total</div><div class="v">{trace["total_seconds"]:.2f} s</div></div>
</div>
<div><div class="lbl">server.log · everything it keeps</div><div class="box log">{log}</div></div>
<div class="punch">No question. No scores.<br>No record of what you read.</div>
</div>"""


# ---------------- sidebar (dev settings) ----------------
with st.sidebar:
    st.header("Settings")
    backend = st.radio("Backend", ["Pipeline", "Canned (layout only)"], key="backend")
    server = st.text_input("Document server", os.environ.get("BLIND_RAG_SERVER", "http://127.0.0.1:8080"))
    st.caption(f"crypto: `{os.environ.get('BLIND_RAG_CRYPTO', 'mock')}`  ·  "
               f"answer: `{os.environ.get('BLIND_RAG_ANSWER', 'stub')}`  ·  "
               f"fetch: `{os.environ.get('BLIND_RAG_FETCH', 'pir')}`")
    if st.button("New session (wipe key and history)"):
        if "pipeline" in ss:
            ss.pipeline.close()
        for k in ("pipeline", "pipeline_server"):
            ss.pop(k, None)
        ss.history = []
        st.rerun()

canned_mode = backend.startswith("Canned")
is_mock = canned_mode or os.environ.get("BLIND_RAG_CRYPTO", "mock") != "real"

# ---------------- header ----------------
head_l, head_r = st.columns([3, 2], vertical_alignment="center")
with head_r:
    show_server = st.toggle("Show what the server saw", key="show_server")
st.markdown(CSS.replace("MAXW", "1240" if show_server else "780"), unsafe_allow_html=True)
with head_l:
    st.markdown('<div class="br-brand">Blind RAG</div>'
                '<div class="br-tag">Your device · holds the only key</div>', unsafe_allow_html=True)
if is_mock:
    st.markdown('<div class="br-mock">Mock mode: no encryption yet. Development build, not private.</div>',
                unsafe_allow_html=True)

if show_server:
    left, right = st.columns([11, 9], gap="large")
else:
    left, right = st.container(), None

# ---------------- your device ----------------
with left:
    history_box = st.container()
    status_box = st.container()
    with st.form("ask", clear_on_submit=True):
        f1, f2 = st.columns([7, 3], vertical_alignment="bottom")
        question = f1.text_input("Your question", placeholder="Ask a sensitive question",
                                 label_visibility="collapsed")
        go = f2.form_submit_button("Ask privately", type="primary")
    if go and question.strip():
        question = question.strip()
        try:
            if canned_mode:
                result, trace = canned.ask(question), None
            else:
                with status_box.status("Working…", expanded=True) as status:
                    def on_stage(name, secs):
                        st.write(f"{STAGE_LABEL[name]} · {secs:.2f} s")
                    result, trace = get_pipeline(server).ask_traced(question, on_stage)
                    status.update(label=f"Done in {trace['total_seconds']:.2f} s", state="complete",
                                  expanded=False)
            ss.history.append((question, result, trace))
        except Exception as e:  # noqa: BLE001
            status_box.error(f"Query failed: {e}")
    with history_box:
        if not ss.history:
            st.markdown('<div class="br-empty">Ask a sensitive question. The server never sees it, '
                        'the scores, or what you read.</div>', unsafe_allow_html=True)
        st.markdown("".join(turn_html(*h) for h in ss.history), unsafe_allow_html=True)

# ---------------- the server (hidden unless toggled) ----------------
last = next((h for h in reversed(ss.history) if h[2]), None)
if right is not None:
    with right:
        with st.container(key="server_pane"):
            if last:
                st.markdown(server_html(last[2]), unsafe_allow_html=True)
            else:
                st.markdown('<div class="br-s"><div class="tag">The server · sees only this</div>'
                            '<div class="dim">Ask a question to see what crosses the network.</div></div>',
                            unsafe_allow_html=True)
        if last:
            q, _, trace = last
            with st.expander("Attacker console: guess which question was asked"):
                if trace["mock"]:
                    st.caption("Only meaningful against the real crypto server.")
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
