"""Self-contained HTML report for eval.bench: summary tiles, stage breakdown, per-question trace waterfall.

The page embeds the run's data as JSON and draws with plain SVG + JS (no network, opens from disk)."""
from __future__ import annotations

import html
import json

CSS = r"""
.viz-root{color-scheme:light;--surface-1:#fcfcfb;--surface-2:#f2f1ee;--border:#dddcd6;--text-primary:#0b0b0b;
--text-secondary:#52514e;--text-muted:#77766f;--good:#008300;--bad:#c42f2e;--warn:#9a6a00;
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s5:#e87ba4;--s6:#008300;--s7:#6250d6;--net:#bdbcb5;--srv:#52514e}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])) .viz-root{color-scheme:dark;--surface-1:#1a1a19;
--surface-2:#242422;--border:#3a3a37;--text-primary:#f0efec;--text-secondary:#c3c2b7;--text-muted:#9a998f;--good:#0ca30c;
--bad:#e66767;--warn:#c98500;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s6:#0ca30c;--s7:#9085e9;
--net:#55544f;--srv:#c3c2b7}}
*{box-sizing:border-box}body{margin:0}
.viz-root{background:var(--surface-1);color:var(--text-primary);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif;
padding:24px 28px;min-height:100vh}
h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;margin:28px 0 10px}.meta{color:var(--text-secondary);font-size:12.5px}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:10px;margin-top:16px}
.tile{background:var(--surface-2);border-radius:8px;padding:10px 12px}.tile .v{font-size:22px;font-weight:600}
.tile .l{font-size:12px;color:var(--text-secondary)}.tile .d{font-size:11.5px;color:var(--text-muted)}
table{border-collapse:collapse;width:100%;font-size:12.5px}th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--border)}
th{color:var(--text-secondary);font-weight:600;cursor:pointer;user-select:none;white-space:nowrap}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
td:not(:last-child){white-space:nowrap}tr.q{cursor:pointer}tr.q:hover{background:var(--surface-2)}tr.sel{background:var(--surface-2)}
.ok{color:var(--good)}.bad{color:var(--bad)}.muted{color:var(--text-muted)}
.legend{display:flex;flex-wrap:wrap;gap:12px;font-size:12px;color:var(--text-secondary);margin:6px 0}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.controls{display:flex;gap:10px;align-items:center;margin:8px 0;font-size:12.5px;color:var(--text-secondary)}
input[type=search]{background:var(--surface-2);border:1px solid var(--border);color:var(--text-primary);border-radius:6px;padding:5px 8px;width:260px}
.detail{background:var(--surface-2);border-radius:8px;padding:14px 16px;margin-top:12px}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:18px}@media(max-width:900px){.cols{grid-template-columns:1fr}}
.ans{white-space:pre-wrap;font-size:13px;background:var(--surface-1);border-radius:6px;padding:10px;max-height:260px;overflow:auto}
.gold{font-weight:600}.tag{font-size:11px;border:1px solid var(--border);border-radius:4px;padding:0 4px;margin-left:4px;color:var(--text-secondary)}
#tip{position:fixed;pointer-events:none;background:var(--text-primary);color:var(--surface-1);font-size:12px;padding:5px 8px;border-radius:5px;display:none;max-width:340px;z-index:9}
svg text{fill:var(--text-secondary);font-size:11px}details{margin-top:24px}pre.md{white-space:pre-wrap;font-size:12px}
"""

JS = r"""
const D=JSON.parse(document.getElementById('data').textContent);
const COLORS={embedding:'--s1',encrypting:'--s2',scoring:'--s3',fetching:'--s4',rerank:'--s5',model:'--s7',checks:'--s6',answering:'--s6'};
const css=v=>getComputedStyle(document.querySelector('.viz-root')).getPropertyValue(v).trim();
const col=n=>css(COLORS[n]||'--net');
const tip=document.getElementById('tip');
function showTip(e,t){tip.innerHTML=t;tip.style.display='block';tip.style.left=Math.min(e.clientX+12,innerWidth-350)+'px';tip.style.top=(e.clientY+12)+'px'}
function hideTip(){tip.style.display='none'}
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const ms=s=>s==null?'':(s<1?(s*1000).toFixed(s<0.01?1:0)+' ms':s.toFixed(2)+' s');
const kb=b=>b==null?'':(b<1048576?(b/1024).toFixed(1)+' KB':(b/1048576).toFixed(2)+' MB');
const NS='http://www.w3.org/2000/svg';
function el(tag,attrs,parent){const e=document.createElementNS(NS,tag);for(const k in attrs)e.setAttribute(k,attrs[k]);parent&&parent.appendChild(e);return e}
function hover(e,t){e.addEventListener('mousemove',ev=>showTip(ev,t));e.addEventListener('mouseleave',hideTip)}

// ---- stage breakdown: one stacked bar of p50 per stage (answering split into rerank / model / checks)
function stageBar(){
  const S=D.summary.speed, parts=[];
  for(const [k,v] of Object.entries(S.stages_seconds)){
    if(k==='answering'&&Object.keys(S.answer_parts_seconds).length){
      for(const [p,pv] of Object.entries(S.answer_parts_seconds)) if(pv) parts.push([p,pv.p50]);
    } else if(v) parts.push([k,v.p50]);
  }
  const svg=document.getElementById('stagebar'), tot=parts.reduce((a,p)=>a+p[1],0)||1, W=svg.clientWidth||900;
  svg.setAttribute('viewBox',`0 0 ${W} 34`);let x=0;const leg=document.getElementById('stageleg');
  parts.forEach(([k,v])=>{const w=Math.max(2,v/tot*W);const r=el('rect',{x:x,y:4,width:Math.max(1,w-2),height:22,rx:3,fill:col(k)},svg);
    hover(r,`<b>${k}</b><br>p50 ${ms(v)} · ${(100*v/tot).toFixed(1)}% of the median question`);x+=w;
    leg.insertAdjacentHTML('beforeend',`<span><i style="background:${col(k)}"></i>${k} ${ms(v)}</span>`)});
}

// ---- question table
let rows=D.rows.filter(r=>r.rep===0), sortKey=null, sortDir=1, filt='', missesOnly=false;
const COLS=[['id','id'],['category','category'],['expect','expect'],['status','status'],['behaved','behaved'],
 ['rank','gold rank','n'],['ctx','in sources'],['cited','cited'],['exact','exact'],['retr','retrieval','n'],['model','model','n'],['wall','total','n'],['up','up','n'],['down','down','n'],['question','question']];
function val(r,k){const a=r.accuracy,s=r.speed;switch(k){case 'rank':return a.gold_rank;case 'behaved':return a.behaved;case 'ctx':return a.gold_in_context;
 case 'cited':return a.gold_cited;case 'exact':return a.parity?a.parity.exact:null;case 'retr':return Object.entries(s.stages).filter(([k])=>k!=='answering').reduce((x,[,v])=>x+v,0);
 case 'model':return s.answer_parts.model;case 'wall':return s.wall_seconds;case 'up':return r.bytes.up;case 'down':return r.bytes.down;default:return r[k]}}
const yn=v=>v==null?'<span class="muted">–</span>':(v?'<span class="ok">✓ yes</span>':'<span class="bad">✗ no</span>');
function drawTable(){
  const t=document.getElementById('qt');let html='<tr>'+COLS.map(([k,l,c])=>`<th class="${c||''}" data-k="${k}">${l}${sortKey===k?(sortDir>0?' ▲':' ▼'):''}</th>`).join('')+'</tr>';
  let rs=rows.filter(r=>(!filt||(r.question+' '+r.id+' '+r.category).toLowerCase().includes(filt))&&(!missesOnly||r.accuracy.behaved===false||r.error||(r.accuracy.parity&&!r.accuracy.parity.exact)||(r.gold_url&&!r.accuracy.gold_in_topk)));
  if(sortKey)rs=[...rs].sort((a,b)=>{const x=val(a,sortKey),y=val(b,sortKey);return (x==null)-(y==null)||(x<y?-1:x>y?1:0)*sortDir});
  for(const r of rs){const a=r.accuracy;html+=`<tr class="q" data-id="${esc(r.id)}"><td>${esc(r.id)}</td><td>${esc(r.category)}</td><td>${esc(r.expect)}</td>
   <td>${r.error?'<span class="bad">error</span>':esc(r.status)}</td><td>${yn(a.behaved)}</td><td class="n">${a.gold_rank??(r.gold_url?'<span class="bad">miss</span>':'–')}</td>
   <td>${yn(a.gold_in_context)}</td><td>${yn(a.gold_cited)}</td><td>${yn(a.parity?a.parity.exact:null)}</td><td class="n">${ms(val(r,'retr'))}</td>
   <td class="n">${ms(val(r,'model'))}</td><td class="n">${ms(r.speed.wall_seconds)}</td><td class="n">${kb(r.bytes.up)}</td><td class="n">${kb(r.bytes.down)}</td><td>${esc(r.question)}</td></tr>`}
  t.innerHTML=html;document.getElementById('count').textContent=`${rs.length} of ${rows.length} questions`;
  t.querySelectorAll('th').forEach(th=>th.onclick=()=>{const k=th.dataset.k;sortDir=sortKey===k?-sortDir:1;sortKey=k;drawTable()});
  t.querySelectorAll('tr.q').forEach(tr=>tr.onclick=()=>{t.querySelectorAll('tr.sel').forEach(x=>x.classList.remove('sel'));tr.classList.add('sel');detail(tr.dataset.id)});
}

// ---- per-question trace: waterfall of stages, answer steps and HTTP requests (client vs server time)
function detail(id){
  const r=rows.find(x=>String(x.id)===id), box=document.getElementById('detail'), T=r.trace;
  const lanes=[];
  T.spans.forEach(s=>lanes.push({label:s.name,start:s.start,dur:s.seconds,color:col(s.name),tip:`<b>${s.name}</b> ${ms(s.seconds)}<br>starts at ${ms(s.start)}`}));
  (T.crypto_calls||[]).forEach(c=>{const host=(T.servers.length>1)?' @'+c.server.replace(/^https?:\/\//,''):'';
    lanes.push({label:'  ↳ key helper: '+c.name+host,start:c.start,dur:c.seconds,color:css('--s2'),
    tip:`<b>${c.name}</b> on this device (key helper)${host?'<br>'+esc(c.server):''}<br>${ms(c.seconds)}`})});
  const ans=T.spans.find(s=>s.name==='answering');
  (T.answer_events||[]).forEach(e=>lanes.push({label:'  ↳ '+e.name,start:e.start,dur:e.seconds,color:col(e.name),
    tip:`<b>${e.name}</b> ${ms(e.seconds)}${e.model?'<br>'+esc(e.model):''}${e.prompt_chars?`<br>prompt ${e.prompt_chars} chars → ${e.output_chars} chars`:''}`}));
  if(ans&&r.speed.answer_parts.checks!=null){const end=Math.max(0,...(T.answer_events||[]).map(e=>e.start+e.seconds));
    lanes.push({label:'  ↳ checks',start:end,dur:r.speed.answer_parts.checks,color:col('checks'),tip:`<b>citation + safety checks, formatting</b> ${ms(r.speed.answer_parts.checks)}`})}
  T.requests.forEach(q=>{const host=(T.servers.length>1)?' @'+q.server.replace(/^https?:\/\//,''):'';
    lanes.push({label:'HTTP '+q.endpoint+host,start:q.start,dur:q.client_ms/1000,srv:q.server_ms!=null?q.server_ms/1000:null,color:css('--net'),
    tip:`<b>${esc(q.endpoint)}</b>${host?'<br>'+esc(q.server):''}<br>client round trip ${q.client_ms} ms${q.server_ms!=null?`<br>server work ${q.server_ms} ms (its log)<br>network + I/O ${q.network_ms} ms`:'<br>server log: not matched'}<br>↑ ${kb(q.request_bytes)} ↓ ${kb(q.response_bytes)}${q.one_time?'<br><i>one-time download</i>':''}`})});
  const total=Math.max(r.speed.wall_seconds,...lanes.map(l=>l.start+l.dur))||1, LW=230, W=Math.max(700,document.getElementById('detail').clientWidth-32), RH=20, H=lanes.length*RH+24;
  const a=r.accuracy;
  box.innerHTML=`<div style="display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap"><div><b>${esc(r.id)}</b> · ${esc(r.category)} · expect <b>${esc(r.expect)}</b> → <b>${esc(r.status)}</b> ${yn(a.behaved)}</div>
   <div class="meta">${esc(T.started_utc)} · ${esc(T.servers.join(', '))} · ${esc(T.fetch_mode)} fetch · k=${T.top_k}</div></div>
   <p style="margin:8px 0 4px">${esc(r.question)}</p>${r.error?`<p class="bad"><b>${esc(r.error.type)}</b> at ${esc(r.error.stage)}: ${esc(r.error.message)}</p>`:''}
   <div class="legend"><span><i style="background:${css('--net')}"></i>client round trip</span><span><i style="background:${css('--srv')}"></i>server work (from its log)</span></div>
   <svg id="wf" viewBox="0 0 ${W} ${H}" width="100%"></svg>
   <div class="cols"><div><h2>Search order (what the encrypted top-k returned)</h2><table id="st"></table>
   ${T.reranked?'<h2>Model sources after local rerank</h2><table id="rt"></table>':''}
   ${a.parity?`<p class="meta">Exactness vs plaintext int8 on this machine: scores ${a.parity.exact?'<span class="ok">identical</span>':'<span class="bad">DIFFER</span>'}, top-k ${a.parity.top_ids_match?'<span class="ok">same</span>':'<span class="bad">different</span>'}</p>`:''}</div>
   <div><h2>Answer</h2><div class="ans">${esc(r.answer.text||'(no answer step)')}</div>
   <p class="meta">gold page: ${r.gold_url?`<a href="${esc(r.gold_url)}" target="_blank">${esc(r.gold_url)}</a> · rank ${a.gold_rank??'not in top-k'} · in sources ${a.gold_in_context??'–'} · cited ${a.gold_cited??'–'}`:'none (should decline)'}
   · urgent expected ${esc(a.urgent_expected??'none')}, got ${esc(a.urgent??'none')} · sentences removed ${a.removed_sentences??'–'}</p>
   <p class="meta">↑ ${kb(r.bytes.up)} ↓ ${kb(r.bytes.down)} this question${r.bytes.one_time_down?` (+ ${kb(r.bytes.one_time_down)} one-time)`:''} · ciphertext starts ${esc(T.ciphertext_sample)}…</p></div></div>`;
  const svg=document.getElementById('wf'), sx=t=>LW+t/total*(W-LW-10);
  for(let i=0;i<=4;i++){const t=total*i/4,x=sx(t);el('line',{x1:x,x2:x,y1:0,y2:H-18,stroke:css('--border'),'stroke-width':1},svg);
    const tx=el('text',{x:x,y:H-4,'text-anchor':i===0?'start':i===4?'end':'middle'},svg);tx.textContent=ms(t)}
  lanes.forEach((l,i)=>{const y=i*RH+2;const tl=el('text',{x:0,y:y+13},svg);tl.textContent=l.label.length>36?l.label.slice(0,35)+'…':l.label;
    const w=Math.max(2,sx(l.start+l.dur)-sx(l.start));const g=el('g',{},svg);
    el('rect',{x:sx(l.start),y:y+2,width:w,height:RH-6,rx:3,fill:l.color},g);
    if(l.srv!=null){const sw=Math.max(1.5,sx(l.start+Math.min(l.srv,l.dur))-sx(l.start));const off=(w-sw)/2;
      el('rect',{x:sx(l.start)+off,y:y+5,width:sw,height:RH-12,rx:2,fill:css('--srv')},g)}
    el('rect',{x:0,y:y,width:W,height:RH,fill:'transparent'},g);hover(g,l.tip+`<br><span style="opacity:.7">${ms(l.start)} → ${ms(l.start+l.dur)}</span>`)});
  const row=(c,i)=>`<tr class="${c.url===r.gold_url?'gold':''}"><td class="n">${i+1}</td><td class="n">${esc(c.id)}</td><td>${esc(c.title)}${c.url===r.gold_url?'<span class="tag">gold</span>':''}${c.server&&T.servers.length>1?`<span class="tag">${esc(c.server.replace(/^https?:\/\//,''))}</span>`:''}</td><td class="n">${c.score.toFixed(3)}</td><td class="n">${esc(c.raw_score)}</td></tr>`;
  const head='<tr><th class="n">#</th><th class="n">id</th><th>page</th><th class="n">cosine≈</th><th class="n">raw int</th></tr>';
  document.getElementById('st').innerHTML=head+T.search.map(row).join('');
  if(T.reranked)document.getElementById('rt').innerHTML=head+T.reranked.map(row).join('');
  box.scrollIntoView({behavior:'smooth',block:'nearest'});
}

stageBar();drawTable();
document.getElementById('flt').oninput=e=>{filt=e.target.value.toLowerCase();drawTable()};
document.getElementById('miss').onchange=e=>{missesOnly=e.target.checked;drawTable()};
if(rows.length)detail(String(rows[0].id));
"""


def _f(x):
    return "n/a" if not x or not x.get("of") else f"{x['pct']:.0f}%"


def _d(x):
    return "" if not x or not x.get("of") else f"{x['n']}/{x['of']}"


def render(rows: list[dict], summary: dict, md: str) -> str:
    m, a, s, b = summary["meta"], summary["accuracy"], summary["speed"], summary["bytes"]

    def ms(st, k="p50"):
        return "n/a" if not st else (f"{st[k] * 1000:.0f} ms" if st[k] < 1 else f"{st[k]:.2f} s")

    def kb(st):
        if not st:
            return "n/a"
        v = st["p50"]
        return f"{v / 1024:.1f} KB" if v < 1048576 else f"{v / 1048576:.2f} MB"

    tiles = [
        (_f(a["recall_at"]["10"]), "right page in encrypted top 10", _d(a["recall_at"]["10"])),
        (_f(a["gold_in_model_sources"]), "right page in the model's sources", _d(a["gold_in_model_sources"])),
    ]
    for key, label in (("answerable_answered", "answerable questions answered"),
                       ("answerable_cited_right_page", "answerable, cited the right page"),
                       ("wrong_answers", "wrong answers (should decline)"),
                       ("encrypted_scores_exact", "encrypted scores = plaintext, exactly")):
        if key in a:
            tiles.append((_f(a[key]), label, _d(a[key])))
    tiles += [
        (ms(s["wall_seconds"]), "whole question, p50", f"p95 {ms(s['wall_seconds'], 'p95')}"),
        (ms(s["retrieval_seconds"]), "private retrieval, p50", f"p95 {ms(s['retrieval_seconds'], 'p95')}"),
        (kb(b["up_per_question"]) + " / " + kb(b["down_per_question"]), "up / down per question", "median"),
    ]
    tiles_html = "".join(f'<div class="tile"><div class="v">{html.escape(v)}</div><div class="l">{html.escape(l)}</div>'
                         f'<div class="d">{html.escape(d)}</div></div>' for v, l, d in tiles)
    data = json.dumps({"rows": rows, "summary": summary}, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Blind RAG benchmark · {html.escape(m['name'])}</title><style>{CSS}</style></head><body><div class="viz-root">
<h1>Blind RAG benchmark</h1>
<div class="meta">{html.escape(m['name'])} · commit {html.escape(m['commit'])} ({html.escape(m['branch'])}) · {html.escape(m['started_utc'])} · {html.escape(m['host'])}<br>
servers {html.escape(', '.join(m['servers']))} · corpus {html.escape(m['corpus'])} · crypto {html.escape(m['crypto'])} · fetch {html.escape(m['fetch'])} ·
embed {html.escape(m['embed'])} · answers {html.escape(m['answer'])} · {a['questions']} questions × {m['repeat']} · {a['errors']} errors · setup {m['setup_seconds']:.2f} s</div>
<div class="tiles">{tiles_html}</div>
<h2>Where the time goes (median question)</h2><svg id="stagebar" width="100%" height="34"></svg><div class="legend" id="stageleg"></div>
<h2>Questions</h2><div class="controls"><input type="search" id="flt" placeholder="Filter by text, id or category">
<label><input type="checkbox" id="miss"> problems only</label><span id="count"></span><span class="muted">click a row for its trace · click a header to sort</span></div>
<div style="max-height:420px;overflow:auto"><table id="qt"></table></div>
<div class="detail" id="detail"></div>
<details><summary>Full report (markdown)</summary><pre class="md">{html.escape(md)}</pre></details>
<div id="tip"></div></div>
<script type="application/json" id="data">{data}</script><script>{JS}</script></body></html>"""
