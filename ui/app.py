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
import datetime
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
from client.multi import MultiPipeline, configured_servers  # noqa: E402
from wiretap.proxy import read_records as wire_records  # noqa: E402
from wiretap.search import question_words, search_traffic  # noqa: E402

PLAIN_DEFAULT = os.environ.get("BLIND_RAG_PLAIN_SERVER", "http://127.0.0.1:8001")
# B's wiretap (wiretap/proxy.py) records every byte the app sends to the servers; the traffic search
# panel appears only when that recording exists.
WIRE_LOG = pathlib.Path(os.environ.get("BLIND_RAG_WIRE_LOG", ROOT / "data" / "wire" / "wire.jsonl"))
DECOYS = [
    "Can I take FMLA leave for a pregnancy complication?",
    "What are the symptoms of depression?",
    "How is chlamydia treated and can I get it again?",
    "What is LDL and why is it called the bad kind?",
    "How much salt should I eat in a day?",
    "What is MRSA and how do people catch it?",
]
MASCOT = "Burrow"
try:   # B's wording covers the FMLA (legal) server too
    from client.answer import DISCLAIMER as FOOT_DISCLAIMER
except Exception:  # noqa: BLE001
    FOOT_DISCLAIMER = c.DISCLAIMER
STAGE_LABEL = {"embedding": "Reading your question on this laptop", "encrypting": "Locking it on this laptop",
               "scoring": "The server is searching without reading it", "fetching": "Fetching the best passages privately",
               "answering": "Writing your answer on this laptop"}

st.set_page_config(page_title="Blind RAG", page_icon=":badger:", layout="wide",
                   initial_sidebar_state="collapsed")
ss = st.session_state
ss.setdefault("history", [])     # list of {"q", "result", "trace", "plain"}
ss.setdefault("error", None)
ss.setdefault("dark", False)

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Red+Hat+Text:wght@400;500;600&family=Red+Hat+Display:wght@500;700;900&family=JetBrains+Mono:wght@400;500&display=swap');
html, body, .stApp, .stApp p, .stApp label, .stApp input, .stApp button {font-family: 'Red Hat Text', system-ui, sans-serif;}
.stApp {background: var(--bg); color: var(--ink);}
.block-container {max-width: MAXWpx; padding-top: 4rem; padding-bottom: 3rem;}
header[data-testid="stHeader"] {background: transparent;}
.br-brand {font-family: 'Red Hat Display', system-ui, sans-serif; font-weight: 700; font-size: 24px; line-height: 1.2;}
.br-tag {font-size: 12px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: var(--brand-text); margin-top: 2px;}
.br-mode {display: inline-block; font-size: 12px; font-weight: 600; letter-spacing: .04em; padding: 4px 10px; border-radius: 6px;}
.br-mode.ok {background: var(--ok-bg); color: var(--ok-ink);}
.br-mode.warn {background: var(--warn-bg); color: var(--warn-ink);}
.br-modeline {font-size: 13px; color: var(--muted); margin: 6px 0 2px;}
.br-health {display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 13px; color: var(--ink-2); margin: 8px 0 4px;}
.br-health .dot {display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 6px;}
.br-health .up {background: var(--ok-dot);} .br-health .down {background: #B42318;}
.br-health code {background: var(--line-2); padding: 1px 6px; border-radius: 4px; font-size: 12px;}
.br-err {background: var(--bad-bg); border: 1px solid var(--bad-line); color: var(--bad-ink); border-radius: 12px; padding: 14px 16px; margin: 12px 0;}
.br-err b {display: block; margin-bottom: 4px;}
.br-err code {background: var(--card); padding: 2px 6px; border-radius: 4px; color: var(--ink); font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 13px;}
.br-empty {color: var(--muted); font-size: 16px; padding: 30px 0 12px;}
.br-turn {display: flex; flex-direction: column; gap: 12px; margin: 18px 0 26px;}
.br-q {align-self: flex-end; max-width: 80%; background: var(--brand); color: #fff; padding: 14px 18px;
       border-radius: 16px 16px 4px 16px; font-size: 17px; line-height: 1.4;}
.br-chips {display: flex; flex-wrap: wrap; gap: 8px; font-size: 12px; color: var(--muted); align-items: center;}
.br-chips span.chip {background: var(--line-2); padding: 5px 10px; border-radius: 999px;}
.br-card {background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 22px 24px;
          display: flex; flex-direction: column; gap: 14px;}
.br-card.declined {border-color: var(--warn-line); background: var(--warn-soft);}
.br-urgent {background: #B42318; color: #fff; border-radius: 10px; padding: 12px 16px; margin-bottom: 14px;
            font-weight: 600; line-height: 1.45;}
.br-label {font-family: 'Red Hat Display', system-ui, sans-serif; font-weight: 500; font-size: 13px;
           letter-spacing: .06em; text-transform: uppercase; color: var(--muted);}
.br-answer {font-size: 17px; line-height: 1.6; white-space: pre-wrap; margin: 0;}
.br-answer sup {background: var(--brand); color: #fff; border-radius: 4px; padding: 0 5px; font-size: 11px; font-weight: 600; margin-left: 2px;}
.br-src {border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; font-size: 14px; display: flex; flex-direction: column; gap: 8px;}
.br-src .ttl {display: flex; gap: 10px; align-items: baseline; font-size: 15px;}
.br-src .ttl b {background: var(--brand); color: #fff; border-radius: 4px; padding: 0 6px; font-size: 12px;}
.br-src .meta {font-size: 12px; color: var(--muted);}
.br-src a {color: var(--brand-text); word-break: break-all;}
.br-src blockquote {margin: 0; padding: 8px 12px; background: var(--brand-tint); border-radius: 6px; color: var(--ink); line-height: 1.5;}
.br-src .cap {font-size: 11px; letter-spacing: .05em; text-transform: uppercase; color: var(--muted);}
.br-src details summary {cursor: pointer; color: var(--brand-text); font-size: 13px;}
.br-src details div {margin-top: 6px; color: var(--ink-2); line-height: 1.55;}
.br-note {font-size: 13px; color: var(--muted);}
.stTextInput div[data-baseweb="input"], .stTextInput div[data-baseweb="base-input"] {min-height: 52px; border-radius: 12px; background: var(--card);}
.stTextInput input {font-size: 16px; background: var(--card); min-height: 50px;}
.stFormSubmitButton button {height: 52px; border-radius: 12px; font-weight: 600; font-size: 16px; width: 100%; white-space: nowrap;}
[data-testid="stForm"] {border: 0; padding: 0;}
.st-key-server_pane {background: #0B0E14; border-radius: 16px; padding: 28px 30px;}
.br-s {color: #C9D3E3; font-family: 'JetBrains Mono', ui-monospace, monospace; display: flex; flex-direction: column; gap: 20px;}
.br-s .tag {font-family: 'Red Hat Text', system-ui, sans-serif; font-size: 12px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: #F2A33A;}
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
.br-s .punch {font-family: 'Red Hat Display', system-ui, sans-serif; font-weight: 700; font-size: 22px; line-height: 1.25; color: #fff; margin-top: 4px;}
.br-grid {display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 14px; margin: 10px 0 22px;}
.br-stat {background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 18px 20px;}
.br-stat .n {font-family: 'Red Hat Display', system-ui, sans-serif; font-weight: 700; font-size: 34px; line-height: 1.1;}
.br-stat .l {font-size: 14px; margin-top: 6px;}
.br-stat .s {font-size: 12px; color: var(--muted); margin-top: 8px;}
.br-pill {display: inline-block; font-size: 11px; font-weight: 600; letter-spacing: .05em; text-transform: uppercase; padding: 2px 8px; border-radius: 999px; margin-bottom: 8px;}
.br-pill.m {background: var(--ok-bg); color: var(--ok-ink);} .br-pill.t {background: var(--line-2); color: var(--ink-2);} .br-pill.x {background: var(--warn-bg); color: var(--warn-ink);}
.br-h {font-family: 'Red Hat Display', system-ui, sans-serif; font-weight: 700; font-size: 20px; margin: 18px 0 2px;}
.br-sub {color: var(--muted); font-size: 14px; margin-bottom: 6px;}
.br-who {display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 14px; margin: 12px 0 20px;}
.br-who > div {border-radius: 14px; padding: 20px 22px; background: var(--card); border: 1px solid var(--line);}
.br-who > div.srv {background: #0B0E14; color: #C9D3E3; border-color: #0B0E14;}
.br-who h4 {margin: 0 0 4px; font-family: 'Red Hat Display', system-ui, sans-serif; font-size: 18px;}
.br-who .srv h4 {color: #fff;}
.br-who ul {margin: 10px 0 0; padding-left: 18px; line-height: 1.7; font-size: 14px;}
.br-who .k {font-size: 12px; letter-spacing: .06em; text-transform: uppercase; font-weight: 600; color: var(--brand-text);}
.br-who .srv .k {color: #F2A33A;}
table.br-t {border-collapse: collapse; width: 100%; font-size: 14px; background: var(--card); border: 1px solid var(--line);}
table.br-t th, table.br-t td {text-align: left; padding: 9px 12px; border-bottom: 1px solid var(--line-2); vertical-align: top;}
table.br-t th {font-size: 12px; letter-spacing: .05em; text-transform: uppercase; color: var(--muted);}

/* ---- redesign: header, status pill, Burrow, receipts ---- */
.br-head {display: flex; align-items: center; gap: 12px;}
.br-head .sub {font-size: 12px; color: var(--muted); margin-top: 2px;}
.br-pillbar {display: flex; justify-content: flex-end;}
.br-status {white-space: nowrap; display: inline-flex; align-items: center; gap: 8px; min-height: 36px; padding: 0 14px; border-radius: 999px;
            font-size: 13px; font-weight: 600; border: 1px solid;}
.br-status .d {width: 8px; height: 8px; border-radius: 50%;}
.br-status.ok {background: var(--ok-bg); color: var(--ok-ink); border-color: var(--ok-line);} .br-status.ok .d {background: var(--ok-dot);}
.br-status.warn {background: var(--warn-bg); color: var(--warn-ink); border-color: var(--warn-line);} .br-status.warn .d {background: #C2620B;}
.br-status.bad {background: var(--bad-bg); color: var(--bad-ink); border-color: var(--bad-line);} .br-status.bad .d {background: #B42318;}
.br-problems {background: var(--bad-bg); border: 1px solid var(--bad-line); border-radius: 12px; padding: 12px 16px; margin: 10px 0 4px;
              font-size: 14px; color: var(--bad-ink); display: flex; flex-direction: column; gap: 6px;}
.br-problems code {background: var(--card); color: var(--ink); padding: 2px 6px; border-radius: 4px; font-size: 12px;}
.st-key-welcome {background: transparent; border: 0; padding: 0; margin: 18px 0 10px;}
.br-say {display: flex; gap: 12px; align-items: flex-start;}
.br-say .av {flex: 0 0 44px; width: 44px; margin-top: 2px;}
.br-say .av.big {flex-basis: 72px; width: 72px;}
.br-say .msg {flex: 1; min-width: 0;}
.br-say .nm {font-size: 12px; font-weight: 600; color: var(--muted); margin: 0 0 4px 2px;}
.br-say .br-card2 {border-radius: 4px 16px 16px 16px;}
.br-bubble {background: var(--card); border: 1px solid var(--line); border-radius: 4px 18px 18px 18px; padding: 16px 20px;
  font-size: 16px; line-height: 1.6; color: var(--ink-2); max-width: 620px;}
.br-bubble b {font-family: 'Red Hat Display', system-ui, sans-serif; font-size: 19px; color: var(--ink); display: block; margin-bottom: 4px;}
.st-key-welcome .br-try, .st-key-welcome .stButton {margin-left: 84px;}
.st-key-welcome .stButton {width: calc(100% - 84px); max-width: 620px;}
.br-welcome {display: flex; gap: 22px; align-items: center; flex-wrap: wrap;}
.br-welcome h3 {margin: 0 0 6px; font-family: 'Red Hat Display', system-ui, sans-serif; font-size: 22px;}
.br-welcome p {margin: 0; font-size: 15px; line-height: 1.55; color: var(--ink-2); max-width: 520px;}
.br-try {font-size: 12px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); margin: 16px 0 2px;}
.st-key-welcome .stButton button {justify-content: flex-start; text-align: left; min-height: 44px; border-radius: 10px;
            background: var(--bg); border: 1px solid var(--line); font-size: 14px;}
.st-key-welcome .stButton button:hover {border-color: var(--brand); color: var(--brand-text);}
.st-key-welcome .stButton button > div, .st-key-welcome .stButton button p {justify-content: flex-start; text-align: left; width: 100%;}
.br-card2 {background: var(--card); border: 1px solid var(--line); border-radius: 16px; overflow: hidden;}
.br-card2.declined {border-color: var(--warn-line); background: var(--warn-soft);}
.br-card2 .hd {display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px;
               padding: 11px 20px; border-bottom: 1px solid var(--line-2); font-size: 12px; color: var(--muted);}
.br-card2 .hd .b {font-weight: 600; letter-spacing: .06em; text-transform: uppercase;}
.br-card2 .hd .b.ok {color: var(--ok-ink);} .br-card2 .hd .b.warn {color: var(--warn-ink);}
.br-card2 .bd {padding: 18px 20px 20px; display: flex; flex-direction: column; gap: 14px;}
.br-srcs {display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 10px;}
.br-card2 .ft {font-size: 12px; color: var(--muted); line-height: 1.5;}
[data-testid="stForm"] {background: var(--card); border: 1.5px solid var(--line) !important; border-radius: 16px; padding: 6px 6px 6px 12px !important;}
[data-testid="stForm"] .stTextInput div[data-baseweb="input"], [data-testid="stForm"] .stTextInput div[data-baseweb="base-input"]
   {border-color: transparent !important; background: transparent; min-height: 48px;}
[data-testid="stForm"] .stTextInput input {background: var(--card) !important; min-height: 46px;}
[data-testid="stForm"] div[data-baseweb="base-input"], [data-testid="stForm"] div[data-baseweb="input"] > div {background: var(--card) !important;}
[data-testid="stForm"] .stFormSubmitButton button {height: 48px;}
[data-testid="stForm"] [data-testid="stTextInputRootElement"], [data-testid="stForm"] [data-testid="stTextInputRootElement"] > div
   {border-color: transparent !important; box-shadow: none !important;}
.br-mirror-h {font-family: 'Red Hat Display', system-ui, sans-serif; font-weight: 700; font-size: 22px; margin: 6px 0 2px;}
.br-mirror-sub {font-size: 14px; color: var(--muted); margin-bottom: 12px;}
.br-mirror {display: grid; grid-template-columns: repeat(auto-fit, minmax(min(400px, 100%), 1fr)); gap: 22px; margin-bottom: 14px;}
.br-rc {background: #FFFEFB; border-radius: 4px; box-shadow: 0 14px 34px rgba(20, 24, 40, .14); padding: 22px 24px 24px;
        font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 13.5px; line-height: 1.75; color: #16140F;}
.br-rc .who {font-family: 'Red Hat Text', system-ui, sans-serif; font-weight: 700; font-size: 15px; letter-spacing: .02em;
             display: flex; justify-content: space-between; gap: 10px; flex-wrap: wrap;}
.br-rc .who span {font-size: 11px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; padding: 3px 8px; border-radius: 999px;}
.br-rc.normal .who span {background: #FBE3DF; color: #8A1C12;} .br-rc.blind .who span {background: #DDF3E4; color: #0B5A2A;}
.br-rc.mock .who span {background: #FDE7C8; color: #7A3A08;}
.br-rc .cut {border-top: 2px dashed #CFC8B8; margin: 12px 0;}
.br-rc .row {display: flex; justify-content: space-between; gap: 14px;}
.br-rc .row span:first-child {color: #6F6858;}
.br-rc .k {color: #6F6858; margin-top: 8px;}
.br-rc .hl {background: #FBE3DF; color: #8A1C12; padding: 6px 10px; margin-top: 4px; word-break: break-word;}
.br-rc .bars {display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px;}
.br-rc .bars i {display: block; height: 16px; background: #16140F;}
.br-rc .hex {color: #6F6858; word-break: break-all; font-size: 12px;}
.br-rc .end {text-align: center; font-weight: 500; letter-spacing: .04em;}
.br-rc.normal .end {color: #8A1C12;} .br-rc.blind .end {color: #0B5A2A;} .br-rc.mock .end {color: #7A3A08;}
.br-rc .empty {font-family: 'Red Hat Text', system-ui, sans-serif; color: #4F4A40; font-size: 14px; line-height: 1.55;}
.br-rc .log {font-size: 12.5px;}
/* ---- v3: top bar, landing page, stepper, demo view ---- */
.block-container {padding-top: 2.2rem;}
.br-brand {font-weight: 900; white-space: nowrap;}
[data-testid="stBottomBlockContainer"] {max-width: MAXWpx;}
.st-key-topbar {border-bottom: 3px solid var(--brand); padding-bottom: 10px; margin-bottom: 14px;}
.st-key-topbar [data-testid="stPopover"] button {min-height: 36px; border-radius: 999px;}
.br-hero {display: flex; gap: 44px; align-items: center; flex-wrap: wrap; color: #fff; border-radius: 28px;
  background: linear-gradient(135deg, var(--brand) 0%, var(--brand-dark) 100%); padding: 52px 56px; margin: 8px 0 20px;}
.br-hero .art {flex: 0 0 270px; width: 270px; height: 270px; background: #fff; border-radius: 50%; display: flex;
  align-items: center; justify-content: center; box-shadow: 0 18px 44px rgba(0, 0, 0, .28);}
.br-hero .txt {flex: 1; min-width: 300px;}
.br-hero .eyebrow {font-size: 13px; font-weight: 600; letter-spacing: .1em; text-transform: uppercase; opacity: .9;}
.br-hero .big {font-family: 'Red Hat Display', system-ui, sans-serif; font-weight: 900; font-size: 48px; line-height: 1.06;
  margin: 10px 0 16px; color: #fff;}
.br-hero .lede {font-size: 18px; line-height: 1.55; max-width: 580px; margin: 0; color: #fff;}
.br-hero .hi {display: inline-block; background: #fff; color: #C5050C; font-weight: 700; border-radius: 999px;
  padding: 4px 14px; font-size: 14px; margin-bottom: 4px;}
.st-key-home_cta .stButton button {min-height: 54px; border-radius: 12px; font-size: 17px; font-weight: 600;}
.br-how {display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px; margin: 22px 0 8px;}
.br-how > div {background: var(--card); border: 1px solid var(--line); border-top: 4px solid var(--brand); border-radius: 14px; padding: 20px 22px;}
.br-how .n {font-family: 'Red Hat Display', system-ui, sans-serif; font-weight: 900; font-size: 15px; color: var(--brand-text); letter-spacing: .08em;}
.br-how h4 {margin: 4px 0 6px; padding: 0; font-family: 'Red Hat Display', system-ui, sans-serif; font-size: 19px; color: var(--ink);}
.br-how p {margin: 0; font-size: 14.5px; line-height: 1.55; color: var(--muted);}
.st-key-home_try .stButton button, .st-key-demo_try .stButton button {justify-content: flex-start; text-align: left;
  min-height: 46px; border-radius: 10px; background: var(--card); border: 1px solid var(--line); font-size: 14px;}
.st-key-home_try .stButton button:hover, .st-key-demo_try .stButton button:hover {border-color: var(--brand); color: var(--brand-text);}
.br-fine {font-size: 12px; color: var(--muted); margin-top: 18px;}
.br-steps {display: flex; flex-wrap: wrap; gap: 8px; margin-top: 2px;}
.br-steps .st {flex: 1 1 130px; display: flex; gap: 10px; align-items: center; background: var(--bg); border: 1px solid var(--line-2);
  border-radius: 10px; padding: 8px 12px;}
.br-steps .st .n {flex: 0 0 24px; height: 24px; border-radius: 50%; background: var(--chip-dark); color: #fff; font-size: 12px;
  font-weight: 700; display: flex; align-items: center; justify-content: center;}
.br-steps .st.server .n {background: var(--brand);}
.br-steps .st b {display: block; font-size: 13px; line-height: 1.2;}
.br-steps .st small {display: block; font-size: 11.5px; color: var(--muted);}
.br-src .ttl a {color: var(--ink); text-decoration: underline; text-decoration-color: var(--brand); word-break: normal;}
.st-key-attacker {background: #282728; border-radius: 16px; padding: 22px 26px; margin: 4px 0 18px;}
.st-key-attacker, .st-key-attacker p, .st-key-attacker label, .st-key-attacker label p {color: #fff !important;}
.st-key-attacker .stButton button, .st-key-attacker .stButton button p {color: #282728 !important; background: #fff;}
.br-atk-h {font-family: 'Red Hat Display', system-ui, sans-serif; font-weight: 700; font-size: 20px; color: #fff;}
.br-atk-s {font-size: 14px; color: #D5D8DE; margin-top: 2px;}
.br-kicker {font-size: 12px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: var(--brand-text); margin: 14px 0 4px;}
[data-testid="stChatInput"] {border-radius: 16px;}

/* ---- v4: design tokens (light), native widgets on tokens, polish ---- */
:root {--bg: #F8F6F4; --card: #FFFFFF; --ink: #231F20; --ink-2: #3A3536; --muted: #5E5759; --line: #E4DFDC; --line-2: #EFEBE8;
  --brand: #C5050C; --brand-dark: #9B0000; --brand-text: #C5050C; --brand-tint: #FBEDED; --ok-bg: #E3F5E9; --ok-ink: #0B5A2A;
  --ok-line: #CFE8D7; --ok-dot: #17803D; --warn-bg: #FDEBD0; --warn-ink: #7A3A08; --warn-line: #F1D2A6; --warn-soft: #FFFBF2;
  --bad-bg: #FDECEA; --bad-ink: #7A1810; --bad-line: #F3B8B1; --chip-dark: #282728; --chip: #FFFFFF; --info-ink: #163A96;
  --shadow: rgba(35, 31, 32, .10);}
.stApp, [data-testid="stAppViewContainer"], [data-testid="stBottom"], [data-testid="stBottom"] > div {background: var(--bg) !important;}
.stApp, [data-testid="stMarkdownContainer"], [data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] p {color: var(--ink);}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {color: var(--muted) !important;}
.stButton button, [data-testid="stPopover"] button {background: var(--card); color: var(--ink); border: 1px solid var(--line);
  transition: border-color .15s, transform .15s, box-shadow .15s;}
.stButton button:hover, [data-testid="stPopover"] button:hover {border-color: var(--brand); color: var(--brand-text);}
.stButton button[kind="primary"], button[data-testid="stBaseButton-primary"] {background: var(--brand); color: #fff; border-color: var(--brand);
  box-shadow: 0 8px 20px -8px rgba(197, 5, 12, .6);}
.stButton button[kind="primary"]:hover {background: var(--brand-dark); color: #fff; transform: translateY(-1px);}
.stButton button[kind="primary"] p {color: #fff;}
button:focus-visible, [data-testid="stChatInput"] textarea:focus-visible {outline: 3px solid var(--brand-text); outline-offset: 2px;}
[data-testid="stButtonGroup"] button {background: var(--card); color: var(--ink); border-color: var(--line); min-height: 38px; font-weight: 500;}
[data-testid="stButtonGroup"] button p {color: inherit;}
[data-testid="stButtonGroup"] button:hover {color: var(--brand-text); border-color: var(--brand);}
[data-testid="stButtonGroup"] button[aria-checked="true"], [data-testid="stButtonGroup"] button[aria-pressed="true"] {background: var(--brand) !important;
  color: #fff !important; border-color: var(--brand) !important;}
[data-testid="stTooltipContent"], [data-testid="stTooltipContent"] * {color: #231F20 !important;}
[data-testid="stExpander"] details {background: var(--card); border-color: var(--line); border-radius: 12px;}
[data-testid="stExpander"] summary, [data-testid="stExpander"] summary p, [data-testid="stExpander"] summary svg {color: var(--ink); fill: var(--ink);}
[data-testid="stChatInput"] {border: 1.5px solid var(--line); background: var(--card); box-shadow: 0 10px 30px -14px var(--shadow);}
[data-testid="stChatInput"] > div, [data-testid="stChatInput"] div, [data-testid="stChatInput"] textarea {background: var(--card) !important; color: var(--ink) !important;}
[data-testid="stChatInput"] textarea::placeholder {color: var(--muted) !important;}
[data-testid="stChatInput"] button {background: var(--brand) !important; color: #fff !important; border-radius: 10px;}
[data-testid="stPopoverBody"] {background: var(--card); color: var(--ink); border: 1px solid var(--line);}
[data-baseweb="input"], [data-baseweb="base-input"], [data-baseweb="select"] > div, .stTextInput input {background: var(--bg) !important;
  color: var(--ink) !important; border-color: var(--line) !important;}
.st-key-theme_btn button, .st-key-topbar [data-testid="stPopover"] button {min-height: 38px; border-radius: 999px; padding: 0 10px;}
.br-card2, .br-stat, .br-how > div, .br-who > div, .br-bubble, table.br-t {box-shadow: 0 1px 2px var(--shadow), 0 14px 30px -18px var(--shadow);}
.br-card2, .br-stat, .br-how > div, .br-who > div {border-radius: 16px;}
.br-how > div {transition: transform .2s;} .br-how > div:hover {transform: translateY(-3px);}
.br-q {box-shadow: 0 10px 24px -12px rgba(197, 5, 12, .7);}
.br-head svg, .br-say .av svg {background: var(--chip); border-radius: 50%; padding: 3px; border: 1px solid var(--line); box-sizing: border-box;}
.br-brand {font-size: 22px; letter-spacing: -.01em;}
.br-hero {position: relative; overflow: hidden; box-shadow: 0 30px 60px -30px rgba(155, 0, 0, .65);
  background: radial-gradient(circle at 16% 28%, rgba(255, 255, 255, .20), transparent 42%),
              radial-gradient(circle at 92% 110%, rgba(0, 0, 0, .28), transparent 50%),
              linear-gradient(135deg, #D10A12 0%, #9B0000 100%);}
.br-hero .art {animation: br-float 5s ease-in-out infinite;}
.br-hero .art svg {margin-top: 6px;}
.br-hero .chips {display: flex; flex-wrap: wrap; gap: 8px; margin-top: 22px;}
.br-hero .chips span {border: 1px solid rgba(255, 255, 255, .5); background: rgba(255, 255, 255, .10); border-radius: 999px;
  padding: 6px 14px; font-size: 13px; font-weight: 500; color: #fff;}
.br-hero, .br-how, .br-turn, .br-mirror {animation: br-rise .45s ease-out both;}
.st-key-attacker {border: 1px solid #3A3536; box-shadow: 0 20px 40px -24px rgba(0, 0, 0, .7);}
.br-rc {border-radius: 6px;}
@keyframes br-float {0%, 100% {transform: translateY(0);} 50% {transform: translateY(-8px);}}
@keyframes br-rise {from {opacity: 0; transform: translateY(10px);} to {opacity: 1; transform: none;}}
@media (prefers-reduced-motion: reduce) {.br-hero .art, .br-hero, .br-how, .br-turn, .br-mirror {animation: none;}
  .stButton button, .br-how > div {transition: none;}}

/* ---- v5: editorial landing page, redaction-bar motif ---- */
.st-key-topbar {border-bottom: 1px solid var(--line); padding-bottom: 12px; margin-bottom: 26px;}
[data-testid="stButtonGroup"] button[aria-checked="true"] *, [data-testid="stButtonGroup"] button[aria-pressed="true"] * {color: #fff !important;}
[data-testid="stButtonGroup"] button {border-radius: 0;}
.br-home {padding: 18px 0 6px;}
.br-home .eyebrow {font-size: 13px; font-weight: 600; letter-spacing: .12em; text-transform: uppercase; color: var(--brand-text);}
.br-h1 {font-family: 'Red Hat Display', system-ui, sans-serif; font-weight: 900; font-size: clamp(40px, 4.6vw, 66px); line-height: 1.02;
  letter-spacing: -.025em; color: var(--ink); margin: 16px 0 20px;}
.br-h1 em {font-style: normal; color: var(--brand-text);}
.br-home .lede {font-size: 19px; line-height: 1.55; color: var(--muted); max-width: 540px; margin: 0 0 26px;}
.br-seen {display: inline-flex; flex-direction: column; gap: 10px; padding: 14px 18px; border: 1px dashed var(--line);
  border-radius: 12px; background: var(--card); margin-bottom: 26px;}
.br-seen span {font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 11.5px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted);}
.br-seen .bars, .br-art .slip .bars {display: flex; flex-wrap: wrap; gap: 7px;}
.br-seen .bars i {display: block; height: 20px; border-radius: 2px; background: var(--ink); transform-origin: left;
  animation: br-redact .6s cubic-bezier(.2, .8, .2, 1) both;}
.br-seen .bars i:nth-child(2) {animation-delay: .08s;} .br-seen .bars i:nth-child(3) {animation-delay: .16s;}
.br-seen .bars i:nth-child(4) {animation-delay: .24s;} .br-seen .bars i:nth-child(5) {animation-delay: .32s;}
.st-key-home_cta .stButton button {min-height: 58px; border-radius: 14px; font-size: 17px; font-weight: 600;}
.br-art {position: relative; min-height: 470px; border-radius: 36px; overflow: hidden; animation: br-rise .5s ease-out both;
  background: radial-gradient(circle at 30% 18%, rgba(255, 255, 255, .22), transparent 46%),
              radial-gradient(circle at 100% 100%, rgba(0, 0, 0, .30), transparent 55%),
              linear-gradient(150deg, #D10A12 0%, #9B0000 100%);
  box-shadow: 0 34px 70px -34px rgba(155, 0, 0, .75);}
.br-art::before {content: ""; position: absolute; left: -60px; bottom: -170px; width: 440px; height: 440px;
  border-radius: 50%; background: #FBF9F6;}
.br-art .pet {position: absolute; left: 20px; bottom: 14px; animation: br-float 5s ease-in-out infinite;
  filter: drop-shadow(0 16px 18px rgba(0, 0, 0, .28));}
.br-art .say {position: absolute; top: 28px; right: 28px; background: #fff; color: #231F20; border-radius: 18px 18px 4px 18px;
  padding: 12px 16px; font-size: 14.5px; line-height: 1.4; box-shadow: 0 12px 26px -12px rgba(0, 0, 0, .5); max-width: 220px;}
.br-art .say b {display: block; font-family: 'Red Hat Display', system-ui, sans-serif; font-size: 17px;}
.br-art .slip {position: absolute; right: 18px; bottom: 30px; width: 176px; background: #FFFEFB; color: #16140F; padding: 14px 16px;
  border-radius: 4px; transform: rotate(4deg); box-shadow: 0 18px 34px -12px rgba(0, 0, 0, .55);
  font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 11px; line-height: 1.7;}
.br-art .slip .t {font-weight: 500; border-bottom: 2px dashed #CFC8B8; padding-bottom: 6px; margin-bottom: 6px;}
.br-art .slip .k {color: #6F6858;}
.br-art .slip .bars i {display: block; height: 13px; background: #16140F;}
.br-how {margin: 44px 0 10px; gap: 18px;}
.br-how > div {border-top: 1px solid var(--line); padding: 24px 24px 26px;}
.br-how .n {width: 34px; height: 34px; border-radius: 50%; background: var(--brand); color: #fff; display: flex; align-items: center;
  justify-content: center; font-size: 16px; letter-spacing: 0; margin-bottom: 14px;}
.br-how .w {font-size: 11.5px; font-weight: 600; letter-spacing: .1em; text-transform: uppercase; color: var(--muted);}
.br-how h4 {font-size: 20px; color: var(--ink);}
.br-how p {color: var(--muted);}
@keyframes br-redact {from {transform: scaleX(0);} to {transform: scaleX(1);}}
@media (prefers-reduced-motion: reduce) {.br-seen .bars i, .br-art, .br-art .pet {animation: none;}}
.st-key-home_try .stButton button, .st-key-demo_try .stButton button {height: auto; padding: 10px 14px;}
.st-key-home_try .stButton button p, .st-key-demo_try .stButton button p {white-space: normal; text-align: left;}
.br-wire-h {font-size: 14px; color: var(--ink-2); margin-bottom: 10px;}
.br-wire-h .chips, .br-wire .chips {display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px;}
.br-wire-h code, .br-wire code {font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: 12px; padding: 2px 7px;
  border-radius: 5px; background: var(--line-2); color: var(--ink-2);}
.br-wire {border: 1px solid var(--line); border-left: 4px solid #1F4FC9; border-radius: 8px; background: var(--card);
  padding: 12px 14px; margin: 8px 0;}
.br-wire.bad {border-left-color: #B3261E; background: var(--bad-bg);}
.br-wire.bad code {background: var(--bad-line); color: var(--bad-ink);}
.br-wire .top {display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 14px; font-size: 14px;}
.br-wire .top span {color: var(--muted); font-size: 13px;}
.br-wire .top em {margin-left: auto; font-style: normal; font-weight: 700; font-size: 12px; letter-spacing: .06em;
  text-transform: uppercase; color: var(--info-ink);}
.br-wire.bad .top em {color: var(--bad-ink);}
.br-wire .raw {font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: 12px; color: var(--muted); margin-top: 8px;
  word-break: break-all;}
.br-wire.bad .raw {color: var(--bad-ink);}
.br-wire.slim {padding: 8px 14px; margin: 6px 0;}
.br-wire-n {font-size: 12px; color: var(--muted); line-height: 1.5; margin: 10px 0 6px;}
/*THEME*/
</style>
"""


DARK_VARS = """:root {--bg: #131112; --card: #1D1A1B; --ink: #F4F0EE; --ink-2: #DAD4D2; --muted: #A69FA1; --line: #383334;
  --line-2: #2A2627; --brand-dark: #8E0007; --brand-text: #FF6A6F; --brand-tint: #2E1416; --ok-bg: #12301F; --ok-ink: #7FDCA0;
  --ok-line: #1F4A31; --ok-dot: #3CCB74; --warn-bg: #3A2710; --warn-ink: #F5C27A; --warn-line: #5A3F1C; --warn-soft: #241C10;
  --bad-bg: #3A1614; --bad-ink: #FFB0A8; --bad-line: #6A2620; --chip-dark: #4A4446; --chip: #F4F0EE; --info-ink: #9DB8FF;
  --shadow: rgba(0, 0, 0, .55); color-scheme: dark;}"""

# ---------------------------------------------------------------- helpers
def esc(x):
    return html.escape(str(x))


def fmt_bytes(n):
    for unit in ("B", "KB", "MB"):
        if n < 1024 or unit == "MB":
            return f"{n:,.0f} {unit}" if unit == "B" else f"{n:,.1f} {unit}"
        n /= 1024


def local_hms(ts):
    """Server logs are stamped in UTC; show them in this laptop's time."""
    try:
        d = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=datetime.timezone.utc)
        return d.astimezone().strftime("%H:%M:%S")
    except ValueError:
        return str(ts)[11:19]


STEPS = [("embedding", "Read", "laptop"), ("encrypting", "Lock", "laptop"), ("scoring", "Blind search", "server"),
         ("fetching", "Fetch", "server"), ("answering", "Write", "laptop")]


def stepper_html(trace):
    """The five stages of a question with the time each really took."""
    tm = (trace or {}).get("timings") or {}
    cells = "".join(f'<div class="st {where}"><span class="n">{i}</span><div><b>{name}</b>'
                    f'<small>{where} · {tm[k]:.2f} s</small></div></div>'
                    for i, (k, name, where) in enumerate(STEPS, 1) if k in tm)
    return f'<div class="br-steps">{cells}</div>' if cells else ""


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


def get_pipeline(servers):
    servers = tuple(servers)
    if ss.get("pipeline_server") != servers:
        if "pipeline" in ss:
            ss.pipeline.close()
        ss.pipeline = Pipeline(server=servers[0]) if len(servers) == 1 else MultiPipeline(list(servers))
        ss.pipeline_server = servers
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


def locket(px=40, wave=False):
    """Burrow, Blind RAG's own mascot: a cartoon badger in a red scarf with a padlock charm. Original art, inline SVG."""
    o = "#1F1B1C"   # outline
    return (f'<svg width="{px}" height="{px}" viewBox="0 0 200 206" role="img" '
            f'aria-label="{MASCOT}, the Blind RAG badger" stroke-linejoin="round" stroke-linecap="round">'
            # scarf, tail and padlock charm (behind the chin)
            f'<path d="M124 176 C134 175 144 171 151 166 L162 196 L151 192 L145 203 L135 190 Z" fill="#A8040A" stroke="{o}" stroke-width="5"/>'
            f'<path d="M46 150 C64 172 136 172 154 150 L160 172 C138 196 62 196 40 172 Z" fill="#C5050C" stroke="{o}" stroke-width="5"/>'
            '<path d="M56 174 C78 188 122 188 144 174" fill="none" stroke="#8E0007" stroke-width="3"/>'
            f'<path d="M80 184 v-4 a6 6 0 0 1 12 0 v4" fill="none" stroke="{o}" stroke-width="3"/>'
            f'<rect x="76" y="183" width="20" height="15" rx="4" fill="#F5B93C" stroke="{o}" stroke-width="3"/>'
            f'<circle cx="86" cy="190.5" r="2.2" fill="{o}"/>'
            # ears
            f'<circle cx="40" cy="46" r="20" fill="#3B3638" stroke="{o}" stroke-width="5"/>'
            f'<circle cx="160" cy="46" r="20" fill="#3B3638" stroke="{o}" stroke-width="5"/>'
            '<circle cx="42" cy="49" r="10" fill="#241F21"/><circle cx="158" cy="49" r="10" fill="#241F21"/>'
            '<path d="M25 37 a20 20 0 0 1 22 -10" fill="none" stroke="#FBF9F6" stroke-width="4.5"/>'
            '<path d="M175 37 a20 20 0 0 0 -22 -10" fill="none" stroke="#FBF9F6" stroke-width="4.5"/>'
            # tuft + head with fluffy cheeks
            f'<path d="M90 36 L95 17 L102 28 L110 18 L112 36 Z" fill="#FBF9F6" stroke="{o}" stroke-width="5"/>'
            '<path d="M100 30 C128 30 150 40 163 58 C172 72 176 88 176 100 L190 108 L180 116 L192 128 L174 132 '
            'C166 152 138 170 100 170 C62 170 34 152 26 132 L8 128 L20 116 L10 108 L24 100 C24 88 28 72 37 58 '
            f'C50 40 72 30 100 30 Z" fill="#FBF9F6" stroke="{o}" stroke-width="5"/>'
            '<path d="M30 136 C44 154 66 165 100 166 C134 165 156 154 170 136 C160 158 134 170 100 170 C66 170 40 158 30 136 Z" fill="#E6DFE8"/>'
            # mask bands
            '<path d="M80 32 C84 60 88 90 90 114 C76 112 58 116 38 126 C30 112 28 92 34 74 C40 58 52 44 66 36 C70 34 75 32 80 32 Z" fill="#3B3638"/>'
            '<path d="M120 32 C116 60 112 90 110 114 C124 112 142 116 162 126 C170 112 172 92 166 74 C160 58 148 44 134 36 C130 34 125 32 120 32 Z" fill="#3B3638"/>'
            '<path d="M80 32 C81 42 82 50 83 58 C68 58 52 64 40 78 C44 62 54 46 66 36 C70 34 75 32 80 32 Z" fill="#575052"/>'
            '<path d="M120 32 C119 42 118 50 117 58 C132 58 148 64 160 78 C156 62 146 46 134 36 C130 34 125 32 120 32 Z" fill="#575052"/>'
            # eyes
            f'<ellipse cx="66" cy="94" rx="15" ry="16" fill="#fff" stroke="{o}" stroke-width="3.5"/>'
            f'<ellipse cx="134" cy="94" rx="15" ry="16" fill="#fff" stroke="{o}" stroke-width="3.5"/>'
            '<circle cx="68" cy="96" r="10.5" fill="#2B2D33"/><circle cx="132" cy="96" r="10.5" fill="#2B2D33"/>'
            '<circle cx="72" cy="91" r="4" fill="#fff"/><circle cx="136" cy="91" r="4" fill="#fff"/>'
            '<circle cx="64" cy="101" r="2" fill="#fff"/><circle cx="128" cy="101" r="2" fill="#fff"/>'
            f'<path d="M50 73 Q62 65 78 71" fill="none" stroke="{o}" stroke-width="5"/>'
            f'<path d="M122 71 Q138 65 150 73" fill="none" stroke="{o}" stroke-width="5"/>'
            # smile, tongue, nose
            f'<path d="M74 129 C83 140 94 140 100 133 C106 140 117 140 126 129" fill="none" stroke="{o}" stroke-width="4"/>'
            f'<path d="M83 138 C90 141 96 140 100 136 C104 140 110 141 117 138 C115 152 108 158 100 158 C92 158 85 152 83 138 Z" fill="#2A1A1C" stroke="{o}" stroke-width="3.5"/>'
            '<path d="M91 150 C95 145 105 145 109 150 C106 155 94 155 91 150 Z" fill="#E8707A"/>'
            f'<path d="M87 112 C87 104 113 104 113 112 C113 121 106 126 100 126 C94 126 87 121 87 112 Z" fill="#2A2224" stroke="{o}" stroke-width="3.5"/>'
            f'<path d="M100 126 V134" stroke="{o}" stroke-width="3.5"/>'
            '<ellipse cx="100" cy="110" rx="7" ry="2.2" fill="#fff" opacity=".75"/>'
            '</svg>')


def turn_html(t):
    q, result, trace = t["q"], t["result"], t["trace"]
    mode = trace["mode"] if trace else None
    badge, cls, detail = mode_text(mode)
    if mode and mode["crypto"] == "real" and mode["answer"] == "real":
        badge_txt = "Encrypted search · answered on this laptop"
    else:
        badge_txt = badge
    right = (f'{trace["num_chunks"]:,} passages scored · {trace["total_seconds"]:.2f} s' if trace else "")

    answer = result["answer"]
    # B's answer() appends its own disclaimer (wording has changed over time); the card footer shows it once.
    answer = re.sub(r"This is general (?:health )?information, not medical(?: or legal)? advice\.", "", answer)
    answer = answer.replace(c.DISCLAIMER, "").strip()
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
        host = urlparse(url).hostname or ""
        ok_url = url.startswith(("http://", "https://"))
        link = esc(host) if ok_url else ""
        title = (f'<a href="{esc(url)}" target="_blank" rel="noopener">{esc(cit.get("title"))}</a>'
                 if ok_url else esc(cit.get("title")))
        meta = []
        if cit.get("updated"):
            meta.append(f'updated {esc(cit["updated"])}')
        if isinstance(cit.get("score"), float) and 0 < cit["score"] <= 1:
            meta.append(f'similarity {cit["score"]:.2f}')
        # B's answer() verifies each cited sentence and returns the matching source sentence; use it.
        # Otherwise (stub answer) fall back to a word-overlap pointer.
        exc = "" if result["declined"] else (cit.get("excerpt") or supporting_excerpt(answer, i, cit.get("text", "")))
        exc_html = f'<blockquote>{esc(exc)}</blockquote>' if exc else ""
        srcs += (f'<div class="br-src"><div class="ttl"><b>{i}</b><span>{title}</span></div>{exc_html}'
                 f'<div class="meta">{link}{" · " if link and meta else ""}{" · ".join(meta)}</div>'
                 f'<details><summary>Full passage</summary><div>{esc(cit.get("text"))}</div></details></div>')
    if result["declined"]:
        body = ('<div class="br-label">No reliable source found</div>'
                '<p class="br-answer">I couldn\'t find a passage in my library that answers this, so I won\'t guess. '
                'These are the closest passages I have.</p>')
        card = "br-card2 declined"
    else:
        body = f'<p class="br-answer">{answer_html(answer)}</p>'
        card = "br-card2"
    return (f'<div class="br-turn"><div class="br-q">{esc(q)}</div>'
            f'<div class="br-say"><div class="av">{locket(44)}</div><div class="msg"><div class="nm">{MASCOT}</div>'
            f'<div class="{card}"><div class="hd"><span class="b {cls}">{esc(badge_txt)}</span><span>{esc(right)}</span></div>'
            f'<div class="bd">{urgent_html}{body}<div class="br-srcs">{srcs}</div>{stepper_html(trace)}'
            f'<div class="ft">{esc(FOOT_DISCLAIMER)}<br>How this ran: {esc(detail)}</div></div></div></div></div></div>')


def _bars(text):
    """Redaction bars roughly the shape of the words, so the receipt shows a question existed."""
    return "".join(f'<i style="width:{min(140, 9 * len(w) + 10)}px"></i>' for w in text.split()[:9])


def mirror_html(t, src):
    """Two receipts: what a normal RAG server kept vs. what Blind RAG's server kept. Both from real logs."""
    trace, plain, q = t["trace"], t.get("plain"), t["q"]
    real = trace["mode"]["crypto"] == "real"

    # -- left: the normal server
    if plain is None:
        left = ('<div class="br-rc normal"><div class="who">A normal AI health service<span>Reads your question</span></div>'
                '<div class="cut"></div><div class="empty">Turn on <b>Also send it to a normal server</b> above '
                'and ask again to see what a typical service stores. That really sends the question unencrypted '
                'to the plaintext demo server.</div></div>')
    elif plain.get("error"):
        left = ('<div class="br-rc normal"><div class="who">A normal AI health service<span>Reads your question</span></div>'
                f'<div class="cut"></div><div class="empty">{esc(plain["error"])}</div></div>')
    else:
        e = plain["entry"]
        docs = "".join(f'<div>· {esc(x)}</div>' for x in list(dict.fromkeys(
            y.get("title") for y in e.get("returned", [])))[:4]) or "<div>(none)</div>"
        left = ('<div class="br-rc normal"><div class="who">A normal AI health service<span>Reads your question</span></div>'
                '<div class="cut"></div>'
                f'<div class="row"><span>TIME</span><span>{esc(local_hms(e.get("time", "")))}</span></div>'
                f'<div class="row"><span>FROM</span><span>{esc(e.get("client", ""))}</span></div>'
                f'<div class="k">QUESTION</div><div class="hl">{esc(e.get("question", ""))}</div>'
                f'<div class="k">DOCUMENTS READ</div>{docs}'
                '<div class="cut"></div><div class="end">KEPT UNTIL DELETED, BREACHED OR SUBPOENAED</div></div>')

    # -- right: Blind RAG's server, from its own log
    rows = question_log(src, trace)
    lines = "".join(f'<div class="row log"><span>{esc(local_hms(r.get("ts", "")))} {esc(r.get("endpoint", ""))}</span>'
                    f'<span>{r.get("latency_ms", "")} ms</span></div>' for r in rows[:6])
    if len(rows) > 6:
        lines += f'<div class="k">… {len(rows) - 6} more lines, same four fields</div>'
    lines = lines or f'<div class="k">no log available at {esc(src)}</div>'
    hx = trace["ciphertext_sample"][:64]
    if real:
        who = 'Blind RAG<span>Computes on a locked question</span>'
        qrow = f'<div class="bars" role="img" aria-label="No question recorded">{_bars(q)}</div><div class="k">never received in readable form · arrived as</div><div class="hex">{esc(hx)}…</div>'
        end, kind = "NOTHING HERE ANYONE COULD READ", "blind"
    else:
        who = 'Development mock<span>Not blind</span>'
        qrow = f'<div class="k">arrived UNENCRYPTED (mock mode)</div><div class="hex">{esc(hx)}…</div>'
        end, kind = "MOCK MODE PROVES NOTHING ABOUT PRIVACY", "mock"
    right = (f'<div class="br-rc {kind}"><div class="who">{who}</div><div class="cut"></div>{lines}'
             f'<div class="k">QUESTION</div>{qrow}<div class="cut"></div>'
             f'<div class="row"><span>READABLE BY THE SERVER</span><span>NO</span></div>'
             f'<div class="cut"></div><div class="end">{end}</div></div>')
    return ('<div class="br-mirror-h">What each server kept from your last question</div>'
            '<div class="br-mirror-sub">Read from each server\'s own log just now. Same question, same library.</div>'
            f'<div class="br-mirror">{left}{right}</div>')


def utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def wire_panel(turn):
    """Search every byte this laptop sent for the question's words. Recorded by B's wiretap relay, between
    the app and the servers, so the result does not depend on any server's own log."""
    records = wire_records(WIRE_LOG)
    hits = search_traffic(records, turn["q"], turn.get("since"))
    if not hits:
        st.caption("No traffic recorded for this question. Start the recorder (python -m wiretap.proxy) and "
                   "point BLIND_RAG_SERVERS at its ports.")
        return
    words = question_words(turn["q"])
    chips = "".join(f"<code>{esc(w)}</code>" for w in words)
    rows = ""
    for h in sorted(hits, key=lambda h: h["route"] == "plain"):
        n = len(h["found"])
        plain = h["route"] == "plain"
        label = "A normal AI health service" if plain else f"Blind RAG · {h['route']} server"
        sent = f"{h['requests']} requests"
        if n == 0:
            body = esc(h["sample_hex"][:96] or "(no request body)") + " …"
            rows += (f'<div class="br-wire ok"><div class="top"><b>{esc(label)}</b><span>{esc(sent)}</span>'
                     f'<em>0 of {h["words"]} words found</em></div><div class="raw">{body}</div></div>')
        else:
            found = "".join(f"<code>{esc(w)}</code>" for w in h["found"])
            rows += (f'<div class="br-wire bad"><div class="top"><b>{esc(label)}</b><span>{esc(sent)}</span>'
                     f'<em>{n} of {h["words"]} words found</em></div><div class="chips">{found}</div>'
                     f'<div class="raw">{esc(h["matches"][0]["context"])}</div></div>')
    luck = max(h["chance_by_luck"] for h in hits)
    st.markdown(
        f'<div class="br-wire-h">Every byte this laptop sent for your question, searched for its '
        f'<b>{len(words)} words</b> of 4+ letters<div class="chips">{chips}</div></div>{rows}'
        f'<div class="br-wire-n">Recorded on this laptop by a relay between the app and each server '
        f'({esc(WIRE_LOG.name)}), not taken from the servers\' logs. Chance of any word appearing in random '
        f'bytes by luck: about {luck:.0e}.</div>', unsafe_allow_html=True)
    word = st.text_input("Search the same traffic for any word, such as a secret word you put in your question",
                         key=f"wire-{turn.get('since')}")
    if word.strip():
        found = search_traffic(records, word, turn.get("since"))
        if not question_words(word):
            st.caption("Use words of 4 letters or more.")
        out = ""
        for h in found:
            hit = bool(h["found"])
            who = "normal AI health service" if h["route"] == "plain" else f"Blind RAG · {h['route']}"
            out += (f'<div class="br-wire {"bad" if hit else "ok"} slim"><div class="top"><b>{esc(who)}</b>'
                    f'<span>searched</span><em>{"found" if hit else "not found"}</em></div></div>')
        st.markdown(out, unsafe_allow_html=True)


def ask_plain_server(url, question):
    """Send the question to B's plaintext demo server and read back what it logged. Real data only."""
    try:
        requests.post(url + "/ask", json={"question": question}, timeout=180).raise_for_status()
        entries = requests.get(url + "/log", timeout=10).json()
        mine = [e for e in entries if e.get("question") == question]
        if not mine:
            return {"error": "The plaintext server answered but its log has no entry for this question."}
        return {"entry": mine[-1]}
    except requests.HTTPError as e:
        return {"error": f"The plaintext demo server at {url} returned an error ({e.response.status_code}). "
                         "Its terminal window shows why."}
    except requests.Timeout:
        return {"error": f"The plaintext demo server at {url} took longer than 3 minutes to answer."}
    except requests.RequestException as e:
        return {"error": f"Plaintext demo server problem at {url}: {type(e).__name__}. If it is not running, "
                         "start it: python3.12 -m baseline.server"}


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
        p = ROOT / "eval" / "results" / "answers_plaintext.jsonl"
    if not p.exists():
        return None
    rows = [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()]
    ans = [r for r in rows if r.get("source_url")]
    un = [r for r in rows if not r.get("source_url")]
    ms = sorted(r["timings"]["answer_ms"] for r in rows if r.get("timings", {}).get("answer_ms"))
    return {"answerable": len(ans), "answered": sum(r["status"] == "answered" for r in ans),
            "gold_cited": sum(bool(r.get("gold_cited")) for r in ans),
            "unanswerable": len(un), "declined": sum(r["status"] == "declined" for r in un),
            "median_answer_s": ms[len(ms) // 2] / 1000 if ms else None, "path": "eval/results/" + p.name}


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


# ---------------------------------------------------------------- navigation
VIEWS = ["Home", "Chat", "Live demo", "Evidence", "Who sees what"]
if ss.get("view") not in VIEWS:          # first visit lands on Home; a deselected control goes back
    ss.view = ss.get("last_view", "Home")
ss.last_view = ss.view


def go(view, q=None):
    """Button callback: switch view, optionally queue a question to ask there."""
    ss.view = view
    if q:
        ss.pending_q = q


SUGGESTIONS = ["How is chlamydia treated and can I get it again?",
               "Can high blood pressure while I'm pregnant hurt my baby?",
               "What is LDL and why is it called the bad kind?"]

# ---------------------------------------------------------------- top bar (settings live in the popover)
with st.container(key="topbar"):
    bar_l, bar_m, bar_r = st.columns([4, 11, 6], vertical_alignment="center")
    with bar_l:
        st.markdown(f'<div class="br-head">{locket(44)}<div><div class="br-brand">Blind RAG</div></div></div>',
                    unsafe_allow_html=True)
    with bar_m:
        view = st.segmented_control("View", VIEWS, key="view", label_visibility="collapsed") or ss.last_view
    with bar_r:
        pill_slot, theme_slot, gear = st.columns([6, 2, 2], vertical_alignment="center", gap="small")
        theme_slot.button("", icon=":material/light_mode:" if ss.dark else ":material/dark_mode:", key="theme_btn",
                          help="Switch to light mode" if ss.dark else "Switch to dark mode",
                          on_click=lambda: ss.update(dark=not ss.dark))
        with gear, st.popover("", icon=":material/settings:", help="Developer settings"):
            st.markdown("**Developer settings**")
            backend = st.radio("Backend", ["Pipeline", "Canned (layout only)"], key="backend")
            # Document servers: the user chooses which to search. Configure the list with BLIND_RAG_SERVERS
            # (comma-separated) or BLIND_RAG_SERVER; more can be added here.
            extra = [u.strip().rstrip("/") for u in st.text_input(
                "Add document servers", "", placeholder="https://… (comma-separated)").split(",") if u.strip()]
            offered = list(dict.fromkeys(configured_servers() + extra))
            selected = st.multiselect("Search these document servers", offered, default=offered, key="servers")
            if len(offered) > 1:
                st.caption("Each selected server gets the same encrypted question and returns exactly 10 records, "
                           "so it learns only that you asked, not what. Unselected servers learn nothing. Someone "
                           "watching every server could see which ones you selected.")
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

if not selected:
    st.warning("Select at least one document server (gear icon, top right).")
    st.stop()
server = selected[0]   # primary: its log feeds the server panel
canned_mode = backend.startswith("Canned")
want_mock = os.environ["BLIND_RAG_CRYPTO"] != "real"
want_stub = os.environ["BLIND_RAG_ANSWER"] != "real"

if canned_mode:
    cur = None
else:
    cur = {"crypto": "mock" if want_mock else "real", "fetch": os.environ.get("BLIND_RAG_FETCH", "download"),
           "answer": "stub" if want_stub else "real", "embed": os.environ.get("BLIND_RAG_EMBED", "real"), "score": ""}
badge, cls, detail = mode_text(cur, planned=True)
items = []
if not canned_mode:
    items = cached_health(server, "mock" if want_mock else "real", "stub" if want_stub else "real")
    for extra_server in selected[1:]:   # one "Document server" row per additional selected server
        items += [i for i in cached_health(extra_server, "mock" if want_mock else "real", "stub")
                  if i["name"] == "Document server"]
down = [h for h in items if not h["ok"]]
if canned_mode:
    pill = ("warn", "Canned · layout only")
elif down:
    pill = ("bad", f"{len(down)} of {len(items)} systems down")
elif want_mock:
    pill = ("warn", "Mock mode · NOT private")
else:
    pill = ("ok", f"Private mode · {len(items)}/{len(items)} ready")
pill_slot.markdown(f'<div class="br-pillbar"><span class="br-status {pill[0]}"><span class="d"></span>{esc(pill[1])}</span></div>',
                   unsafe_allow_html=True)
st.markdown(CSS.replace("MAXW", {"Home": "1300", "Live demo": "1400"}.get(view, "1180"))
            .replace("/*THEME*/", DARK_VARS if ss.dark else ""), unsafe_allow_html=True)

if down:   # problems are never hidden: name each one and its fix
    st.markdown('<div class="br-problems">' + "".join(
        f'<div><b>{esc(h["name"])}</b>: {esc(h["detail"])}' + (f' · fix: <code>{esc(h["fix"])}</code>' if h["fix"] else "")
        + "</div>" for h in down) + "</div>", unsafe_allow_html=True)


def system_details():
    with st.expander("System details"):
        st.markdown(f'<span class="br-mode {cls}">Next question runs as: {esc(badge)}</span>'
                    f'<div class="br-modeline">{esc(detail)}</div>', unsafe_allow_html=True)
        if items:
            st.markdown('<div class="br-health">' + "".join(
                f'<span><span class="dot {"up" if h["ok"] else "down"}"></span><b>{esc(h["name"])}</b>: {esc(h["detail"])}'
                + (f' &nbsp;fix: <code>{esc(h["fix"])}</code>' if h["fix"] else "") + "</span>" for h in items)
                + "</div>", unsafe_allow_html=True)


def run_question(question, compare, status_box):
    """Ask the pipeline (and, if compare, the plaintext demo server). Appends to history or sets ss.error."""
    ss.error = None
    since = utc_now()  # the traffic search covers only this question's requests
    try:
        if canned_mode:
            turn = {"q": question, "result": c.normalize_result(canned.ask(question)), "trace": None}
        else:
            with status_box.status(f"{MASCOT} is locking your question and searching…", expanded=True) as status:
                def on_stage(name, secs):
                    st.write(f"{STAGE_LABEL.get(name, name)} · {secs:.2f} s")
                try:
                    result, trace = get_pipeline(selected).ask_traced(question, on_stage)
                except Exception:
                    status.update(label="Stopped: no answer", state="error", expanded=False)
                    raise
                turn = {"q": question, "result": result, "trace": trace, "since": since}
                if compare:
                    st.write("Sending the same question to the normal (plaintext) server…")
                    turn["plain"] = ask_plain_server(plain_url, question)
                status.update(label=f"Done in {trace['total_seconds']:.2f} s", state="complete", expanded=False)
        ss.history.append(turn)
    except PipelineError as e:
        ss.error = {"stage": e.stage, "message": e.message, "fix": e.fix, "q": question}
    except Exception as e:  # noqa: BLE001
        ss.error = {"stage": "unexpected", "message": f"{type(e).__name__}: {e}", "fix": "", "q": question}


def show_error():
    if ss.error:
        e = ss.error
        fix = f'<br>Fix: <code>{esc(e["fix"])}</code>' if e["fix"] else ""
        st.markdown(f'<div class="br-err"><b>Sorry, I could not answer “{esc(e["q"])}” (failed at: {esc(e["stage"])})</b>'
                    f'{esc(e["message"])}{fix}<br><span style="font-size:13px">Nothing was retried in a '
                    f'weaker mode.</span></div>', unsafe_allow_html=True)


# ---------------------------------------------------------------- home (landing page)
if view == "Home":
    bars = "".join(f'<i style="width:{w}px"></i>' for w in (96, 44, 132, 70, 108))
    left, right = st.columns([11, 9], gap="large", vertical_alignment="center")
    with left:
        st.markdown(
            '<div class="br-home"><div class="eyebrow">Private health search · built at MadHacks</div>'
            '<div class="br-h1">Ask the question you\'d rather keep to <em>yourself.</em></div>'
            f'<p class="lede">{MASCOT} locks your question on this laptop before it leaves. The library\'s server '
            'searches without ever reading it, and the answer is written right here, with sources.</p>'
            f'<div class="br-seen"><span>What the server sees of your question</span><div class="bars">{bars}</div></div></div>',
            unsafe_allow_html=True)
        with st.container(key="home_cta"):
            c1, c2 = st.columns(2)
            c1.button(f"Chat with {MASCOT}", type="primary", width="stretch", icon=":material/lock:",
                      on_click=go, args=("Chat",))
            c2.button("See the live demo", width="stretch", icon=":material/compare_arrows:",
                      on_click=go, args=("Live demo",))
    with right:
        st.markdown(
            f'<div class="br-art"><div class="say"><b>Hi, I\'m {MASCOT}.</b>Your question stays between us.</div>'
            f'<div class="pet">{locket(280)}</div>'
            '<div class="slip"><div class="t">SERVER LOG · /v1/score</div><div class="k">QUESTION</div>'
            '<div class="bars"><i style="width:54px"></i><i style="width:26px"></i><i style="width:70px"></i>'
            '<i style="width:40px"></i></div><div class="k">never received in readable form</div></div></div>',
            unsafe_allow_html=True)
    st.markdown(
        '<div class="br-how">'
        '<div><div class="n">1</div><div class="w">On your laptop</div><h4>Your question is locked</h4><p>It is encrypted '
        'with a key that exists only in this laptop\'s memory and is never sent anywhere.</p></div>'
        '<div><div class="n">2</div><div class="w">On the server</div><h4>Searched without being read</h4><p>The server '
        'scores every passage in its library against the locked question. It cannot read the question or the scores.</p></div>'
        '<div><div class="n">3</div><div class="w">On your laptop</div><h4>Answered right here</h4><p>The best passages are '
        'unlocked and a local model writes the answer with citations, or says it found no reliable source.</p></div>'
        '</div><div class="br-kicker">Try asking</div>', unsafe_allow_html=True)
    with st.container(key="home_try"):
        for col, sq in zip(st.columns(len(SUGGESTIONS)), SUGGESTIONS):
            col.button(sq, key=f"home-{sq}", width="stretch", on_click=go, args=("Chat", sq))
    st.markdown(f'<div class="br-fine">{esc(FOOT_DISCLAIMER)} A MadHacks student project; not affiliated with or '
                'endorsed by the University of Wisconsin–Madison.</div>', unsafe_allow_html=True)

# ---------------------------------------------------------------- chat (the product: one clean conversation)
if view == "Chat":
    history_box = st.container()
    status_box = st.container()
    typed = st.chat_input(f"Ask {MASCOT} a sensitive question", key="chat_in")
    pending = ss.pop("pending_q", None)
    asked = typed.strip() if typed and typed.strip() else pending
    if asked:
        run_question(asked, False, status_box)
    with history_box:
        if not ss.history and not ss.error:
            with st.container(key="welcome"):
                st.markdown(
                    f'<div class="br-say"><div class="av big">{locket(72)}</div><div class="msg">'
                    f'<div class="nm">{MASCOT}</div><div class="br-bubble"><b>Hi, I\'m {MASCOT}.</b> Ask me a health '
                    'question you\'d rather keep to yourself. I lock it before it leaves this laptop, the '
                    'library\'s server searches without ever reading it, and I write your answer right here, '
                    'with sources.</div></div></div><div class="br-try">You could ask me</div>',
                    unsafe_allow_html=True)
                for i, sq in enumerate(SUGGESTIONS):
                    st.button(sq, key=f"sugg{i}", width="stretch", on_click=go, args=("Chat", sq))
        st.markdown("".join(turn_html(t) for t in ss.history), unsafe_allow_html=True)
        show_error()

# ---------------------------------------------------------------- live demo (for judges: two servers side by side)
if view == "Live demo":
    st.markdown('<div class="br-h" style="font-size:26px">Same question, two servers</div>'
                '<div class="br-sub">Ask once. See what a normal AI health service keeps next to what the '
                'Blind RAG server keeps, read from each server\'s own log.</div>', unsafe_allow_html=True)
    system_details()
    with st.container():
        typed = st.chat_input("Ask a sensitive question to compare both servers", key="demo_in")
    compare = False
    if not canned_mode:
        compare = st.toggle("Also send it to a normal server", value=True, key="compare",
                            help="When on, the question really is sent unencrypted to the plaintext demo server, "
                                 "so its log can be shown next to Blind RAG's.")
    status_box = st.container()
    pending = ss.pop("pending_q", None)
    asked = typed.strip() if typed and typed.strip() else pending
    if asked:
        run_question(asked, compare, status_box)
    show_error()

    last = next((t for t in reversed(ss.history) if t["trace"]), None)
    if last:
        q, trace = last["q"], last["trace"]
        st.markdown(mirror_html(last, log_source(server)), unsafe_allow_html=True)
        with st.container(key="attacker"):
            st.markdown('<div class="br-atk-h">Attacker console: you hold the server\'s logs</div>'
                        '<div class="br-atk-s">Everything the Blind RAG server kept is in the receipt above. '
                        'Which of these five questions was asked?</div>', unsafe_allow_html=True)
            if trace["mock"]:
                st.caption("Mock mode: this game only means something against the real encrypted server.")
            rng = random.Random(hashlib.sha256(q.encode()).digest())
            options = rng.sample([d for d in DECOYS if d != q], 4) + [q]
            rng.shuffle(options)
            guess = st.radio("Pick one", options, index=None, key=f"guess-{q}", label_visibility="collapsed")
            if st.button("Check guess") and guess:
                if guess == q:
                    st.success("Correct, by luck: a 1 in 5 guess. Nothing on the server pointed to it.")
                else:
                    st.error("Wrong. Nothing on the server distinguishes these five questions.")
                st.write(f"The question was: **{q}**")
        if WIRE_LOG.exists():
            with st.expander("🔍 Search the traffic for your words", expanded=True):
                wire_panel(last)
        st.markdown('<div class="br-kicker">What the user saw</div>' + turn_html(last), unsafe_allow_html=True)
    elif ss.history:
        st.markdown('<div class="br-kicker">What the user saw</div>' + turn_html(ss.history[-1]), unsafe_allow_html=True)
    elif not ss.error:
        st.markdown('<div class="br-kicker">Pick a question to run the comparison</div>', unsafe_allow_html=True)
        with st.container(key="demo_try"):
            for col, sq in zip(st.columns(len(SUGGESTIONS)), SUGGESTIONS):
                col.button(sq, key=f"demo-{sq}", width="stretch", on_click=go, args=("Live demo", sq))

# ---------------------------------------------------------------- evidence
if view == "Evidence":
    st.markdown('<div class="br-h">What we measured</div><div class="br-sub">Every number names its file. '
                '“Target” is a goal from the spec, not a result.</div>', unsafe_allow_html=True)

    traces = [t["trace"] for t in ss.history if t["trace"]]
    if traces:
        tr = traces[-1]
        b, cl, _ = mode_text(tr["mode"])
        cards = (stat(f'{tr["timings"].get("scoring", 0) + tr["timings"].get("encrypting", 0):.2f} s',
                        "encrypt + server scoring", f"this session · {esc(b)}")
                 + stat(f'{tr["total_seconds"]:.2f} s', "end to end", f'{len(traces)} question(s) this session'))
        st.markdown('<div class="br-h">This session, live</div><div class="br-grid">' + cards + "</div>",
                    unsafe_allow_html=True)

    ret0, ans0 = load_retrieval(), load_answers()
    if ret0 and ans0:
        n0 = ret0["n"]
        rows0 = [
            ("Right source in the top 10", f'{ret0["float"][10]}/{n0}', f'{ret0["int8"][10]}/{n0}',
             "Blind RAG scores 8-bit numbers; the normal service uses full floats"),
            ("Answerable questions answered", f'{ans0["answered"]}/{ans0["answerable"]}', f'{ans0["answered"]}/{ans0["answerable"]}',
             "Same retrieval, same local answer step"),
            ("Answers citing the expected source", f'{ans0["gold_cited"]}/{ans0["answerable"]}', f'{ans0["gold_cited"]}/{ans0["answerable"]}', "Same"),
            ("Off-topic questions declined", f'{ans0["declined"]}/{ans0["unanswerable"]}', f'{ans0["declined"]}/{ans0["unanswerable"]}',
             "No answer is written without a reliable source"),
            ("Server can read your question", "Yes", "No", "Shown live in the Live demo tab"),
            ("Server keeps your question in its log", "Yes", "No", "Its log keeps four fields, none of them the question"),
            ("Words from your question found in the traffic", "Found in the clear", "Not found", "Searched live on the wire in the Live demo tab"),
        ]
        body0 = "".join(f"<tr><td>{esc(a)}</td><td>{esc(b)}</td><td><b>{esc(c_)}</b></td><td>{esc(d)}</td></tr>" for a, b, c_, d in rows0)
        st.markdown('<div class="br-h">Blind RAG vs a normal AI service</div><div class="br-sub">Same questions, same library. '
                    'Quality is the plaintext evaluation (<code>' + esc(ans0["path"]) + '</code>): the encrypted ranking matches the '
                    'plaintext int8 ranking, so privacy does not cost answer quality. End-to-end encrypted runs: <code>make bench</code>.</div>'
                    '<table class="br-t"><tr><th>Measure</th><th>Normal AI service</th><th>Blind RAG</th><th>Note</th></tr>'
                    + body0 + "</table>", unsafe_allow_html=True)

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
    st.markdown('<div class="br-h">Speed</div><div class="br-sub">From <code>make measure</code> on this '
                'machine (<code>data/measurements.md</code>).</div>', unsafe_allow_html=True)
    meas = [m for m in (load_measurements() or []) if not re.search(r"byte|\b[KM]B\b|upload|download|\bup\b|\bdown\b", " ".join(m[:2]), re.I)] or None
    if meas:
        body = "".join(f"<tr><td>{esc(a)}</td><td>{esc(b)}</td><td><b>{esc(m)}</b></td><td>{esc(ok)}</td></tr>"
                       for a, b, m, ok in meas)
        st.markdown('<table class="br-t"><tr><th>Metric</th><th>Target (spec)</th><th>Measured</th><th>Met</th></tr>'
                    + body + "</table>", unsafe_allow_html=True)
    else:
        st.markdown('<div class="br-grid">' + stat("—", "crypto latency and server CPU",
                    "Run <code>make measure</code> with the server and helper up. Target: under 10 s end to end.", "x") + "</div>", unsafe_allow_html=True)

    st.caption("Small evaluation set. These are not medically validated accuracy figures.")

# ---------------------------------------------------------------- who sees what
if view == "Who sees what":
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
