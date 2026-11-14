"""Blind RAG client UI.

    streamlit run ui/app.py

Env: BLIND_RAG_SERVER, BLIND_RAG_CRYPTO, BLIND_RAG_ANSWER, BLIND_RAG_FETCH,
BLIND_RAG_EMBED (see client/pipeline.py) and BLIND_RAG_SERVER_LOG (path to the
server's log file, default data/server.log).
"""
import hashlib
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
from client.pipeline import STAGES, Pipeline  # noqa: E402

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

st.set_page_config(page_title="Blind RAG", page_icon="🔒", layout="wide")
ss = st.session_state
ss.setdefault("history", [])   # list of (question, result, trace)


def fmt_bytes(n):
    for unit in ("B", "KB", "MB"):
        if n < 1024 or unit == "MB":
            return f"{n:,.0f} {unit}" if unit == "B" else f"{n:,.1f} {unit}"
        n /= 1024


def log_tail(k=15):
    if not LOG_PATH.exists():
        return []
    out = []
    for line in LOG_PATH.read_text().splitlines()[-k:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            out.append({"raw": line})
    return out


def get_pipeline(server):
    if ss.get("pipeline_server") != server:
        ss.pipeline, ss.pipeline_server = Pipeline(server=server), server
    return ss.pipeline


# ---------------- sidebar ----------------
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

st.title("🔒 Blind RAG")
st.caption("Ask a sensitive question. The server never sees it, the scores, or what you read.")
if is_mock:
    st.warning("MOCK MODE: no encryption. This build is for development and is not private.", icon="⚠️")

tab_ask, tab_attack = st.tabs(["Ask", "Attacker console"])

# ---------------- ask ----------------
with tab_ask:
    left, right = st.columns([3, 2], gap="large")
    with left:
        with st.form("ask", clear_on_submit=True):
            question = st.text_input("Your question", placeholder="What are early signs of a miscarriage?")
            go = st.form_submit_button("Ask privately", type="primary")
        if go and question.strip():
            question = question.strip()
            try:
                if canned_mode:
                    result, trace = canned.ask(question), None
                else:
                    with st.status("Working…", expanded=True) as status:
                        def on_stage(name, secs):
                            st.write(f"✓ {STAGE_LABEL[name]} · {secs:.2f} s")
                        result, trace = get_pipeline(server).ask_traced(question, on_stage)
                        status.update(label=f"Done in {trace['total_seconds']:.2f} s", state="complete",
                                      expanded=False)
                ss.history.append((question, result, trace))
            except Exception as e:  # noqa: BLE001
                st.error(f"Query failed: {e}")

        for q, result, trace in reversed(ss.history):
            with st.chat_message("user"):
                st.write(q)
            with st.chat_message("assistant"):
                if result["declined"]:
                    st.info(result["answer"])
                else:
                    st.write(result["answer"])
                if trace:
                    st.caption(" → ".join(f"{s} {trace['timings'][s]:.2f}s" for s in STAGES))
                label = "Closest passages" if result["declined"] else "Sources"
                st.markdown(f"**{label}**")
                for i, cit in enumerate(result["citations"], 1):
                    with st.expander(f"[{i}] {cit['title']}"):
                        st.write(cit["text"])
                        st.markdown(f"[{cit['url']}]({cit['url']})")
                st.caption(c.DISCLAIMER)

    with right:
        st.subheader("What the server saw")
        last = next((h for h in reversed(ss.history) if h[2]), None)
        if not last:
            st.caption("Ask a question to see exactly what crossed the network.")
        else:
            q, _, trace = last
            a, b, d = st.columns(3)
            a.metric("Uploaded", fmt_bytes(trace["upload_bytes"]))
            b.metric("Downloaded", fmt_bytes(trace["download_bytes"]))
            d.metric("Total time", f"{trace['total_seconds']:.2f} s")
            st.markdown("**The question as the server received it**")
            st.code(trace["ciphertext_sample"] + "…", language=None)
            st.markdown("**Requests**")
            rows = {}
            for r in trace["requests"]:
                row = rows.setdefault(r["endpoint"], {"endpoint": r["endpoint"], "calls": 0,
                                                      "bytes sent": 0, "bytes received": 0})
                row["calls"] += 1
                row["bytes sent"] += r["request_bytes"]
                row["bytes received"] += r["response_bytes"]
            st.dataframe(list(rows.values()), hide_index=True)
            st.caption(f"All {trace['num_chunks']:,} chunks scored; exactly {trace['top_k']} fetched, "
                       "every response the same size.")
            with st.expander("What only your device knows"):
                st.write(f"Question: {q}")
                st.write(f"Top chunk ids: {trace['top_ids']}")

        st.markdown("**Server log** (everything the server keeps)")
        tail = log_tail()
        if tail:
            st.dataframe(tail[::-1], hide_index=True)
        else:
            st.caption(f"No log at `{LOG_PATH}`. Set BLIND_RAG_SERVER_LOG.")

# ---------------- attacker console ----------------
with tab_attack:
    st.subheader("You have the server's database and logs. Which question was asked?")
    real = next((h for h in reversed(ss.history) if h[2]), None)
    if not real:
        st.caption("Ask a question in the Ask tab first.")
    else:
        q, _, trace = real
        if trace["mock"]:
            st.warning("Mock server: this game is only meaningful against the real crypto server.", icon="⚠️")
        rng = random.Random(hashlib.sha256(q.encode()).digest())
        options = rng.sample([d for d in DECOYS if d != q], 4) + [q]
        rng.shuffle(options)

        l, r = st.columns(2, gap="large")
        with l:
            st.markdown("**Everything the server holds about this query**")
            st.code(trace["ciphertext_sample"] + "…", language=None)
            st.dataframe(log_tail(12)[::-1], hide_index=True)
            st.caption(f"Sent {fmt_bytes(trace['upload_bytes'])}, received {fmt_bytes(trace['download_bytes'])}. "
                       "Any other question produces the same sizes.")
        with r:
            guess = st.radio("Candidate questions", options, index=None, key=f"guess-{q}")
            if st.button("Check guess") and guess:
                if guess == q:
                    st.success("Correct, by luck: a 1 in 5 guess. Nothing on the server pointed to it.")
                else:
                    st.error("Wrong. Nothing on the server distinguishes these five questions.")
                st.write(f"The question was: **{q}**")
