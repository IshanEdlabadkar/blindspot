# Security layers

Blindspot's core promise is that the document servers never see the question or which passages were
fetched. These are the layers around that promise, what each protects against, and what is still open.

## In place

| Layer | Protects against | Where |
|---|---|---|
| Question encrypted with a fresh one-time key (LWE, hint mode) | servers reading the question | `crypto-server/blindcrypto`, key helper |
| Exactly k fetches per server, by PIR or full-store download | servers learning which passages were used | `client/pipeline.py`, `/v1/fetch_batch` |
| Server log has 4 fields only (time, endpoint, bytes, latency) | logs leaking content | `crypto-server/main.go` |
| Corpus hashes verified when a server loads (Databricks -> server) | a tampered corpus being served | `crypto-server/corpus.go` |
| **Corpus pins**: each hosted server's version + hashes are pinned in `servers.remote.json`; the client refuses a manifest that differs (also through the wiretap relay or a local backup, by `source_id`) | a compromised or swapped server feeding wrong passages | `client/pins.py`, `client/pipeline.py` |
| **Fetch store checked** against the manifest hash after download | a server altering passages in transit or at rest | `client/pipeline.py` |
| **Key helper locked**: random session token per run (file mode 0600), loopback Host only, browser requests refused | other programs or web pages (incl. DNS rebinding) using the keys | `crypto-server/cmd/crypto-helper` |
| **HTTP timeouts** on the server and helper; request size limits | slow or stalled connections tying up a server (slowloris) | `crypto-server/main.go` |
| **Rate limiting with a penalty box** (public servers only): per-client budgets for questions (1,200/min, burst 200) and the big one-time downloads (20/min, burst 12); 20 refusals in a minute put a client in the penalty box for 5 minutes; at most 16 requests in flight. Clients are told apart by a keyed hash of their address, in memory only, forgotten after 10 idle minutes, never logged. All `BLIND_RAG_RATE_*` / `BLIND_RAG_PENALTY*` settable. | floods, bandwidth exhaustion from repeated multi-MB downloads | `crypto-server/ratelimit.go` |
| **Uniform client headers**: every asker sends the same minimal headers (no library name or version, no machine-dependent compression list) | servers telling askers apart by their software | `client/net.py` |
| **Content-Security-Policy** on the web UI: code only from this app, network only to its own API, no framing, no referrer | an injected script in a displayed passage sending the question or answer elsewhere | `api/app.py` |
| **No telemetry**: Hugging Face, Streamlit usage stats off; models load offline once downloaded | the app announcing itself or phoning home | `scripts/privacy_env.sh`, `.streamlit/config.toml` |
| Four independent servers, Databricks primary, repo backups, `LOCAL=1` offline | outages | `servers.remote.json`, demo scripts |

After publishing a new corpus version on purpose, update the pins: `python3 scripts/check_servers.py --pin`, then commit.

## Still open (next layers)

- **Metadata**: servers still see the IP address, time and number of questions, and which servers were chosen
  (a topic hint). Next: always query every server; route through an Oblivious HTTP relay or Tor; dummy queries.
- **Per-record integrity under real PIR** with uniform failure (no observable retry), against selective-failure
  attacks by a malicious server. Provider-signed manifests instead of hashes alone.
- **Least privilege on Databricks**: a read-only service principal per server instead of a personal token;
  short expiry, rotation, audit logs. Turn `/v1/server_log` off on public servers after the demo.
- **Rate-limit identity behind Render**: the server trusts `CF-Connecting-IP`, else the left-most
  `X-Forwarded-For`; a client that reaches the server directly could forge them. The in-flight cap protects
  the server regardless.
- **Laptop**: full-disk encryption; clear `data/wire/` and caches per session; the plaintext comparison
  server is the one place a question goes in the clear and is labelled as such.
- **Supply chain**: the crypto libraries are research code (Tiptoe, SimplePIR), vendored and patched; document
  parameters with a lattice-estimator security level, pin the Docker base image by digest, run tests in CI.

The rate limiting, header and CSP layers apply ideas from the MadHacks 2026 TDS workshop (penalty box,
response-header policy, stripping client data) at the layer where they protect Blindspot. Its WAF demo
(request inspection) adds little here: the servers take fixed-format encrypted bytes and never turn
request data into file paths, and the size limits already cap requests.
