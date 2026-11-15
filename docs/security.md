# Security layers

Blind RAG's core promise is that the document servers never see the question or which passages were
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
- **Rate limiting** in front of the servers.
- **Laptop**: full-disk encryption; clear `data/wire/` and caches per session; the plaintext comparison
  server is the one place a question goes in the clear and is labelled as such.
- **Supply chain**: the crypto libraries are research code (Tiptoe, SimplePIR), vendored and patched; document
  parameters with a lattice-estimator security level, pin the Docker base image by digest, run tests in CI.
