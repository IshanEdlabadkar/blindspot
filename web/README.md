# Blindspot web UI ("Vault")

The demo front end: ask anything, get a cited answer written on this laptop, then open
"See what left this laptop" to watch what happened to the question and see the traffic proof.

## Run the demo

```bash
./web/demo.sh            # hosted document servers (servers.remote.json), local backups if one is asleep
LOCAL=1 ./web/demo.sh    # all local (servers.json), offline
```

Open http://localhost:8600 .

Needs: Node 20+ (the first run builds `web/dist`), a Python with `numpy requests sentence-transformers
fastapi uvicorn`, Ollama with `llama3.2:3b`, and A's crypto toolchain (`make seal`). On a Mac whose SEAL is
installed outside `/usr/local`, export `CGO_CXXFLAGS`/`CGO_LDFLAGS` first.

## Develop

```bash
uv run uvicorn api.app:app --port 8600   # the API (needs the servers and relays from web/demo.sh)
cd web && npm run dev                     # Vite on :5173, proxies /api to :8600
```

## Pieces

| Path | What |
|---|---|
| `src/App.tsx` | Shell, status, streams each question's events |
| `src/Chat.tsx` | Landing, composer, answers with sources and safety notices |
| `src/Simulation.tsx`, `src/sim.ts` | The "100 people" tab: a hundred made-up patrons, a typical library ledger beside a Blindspot ledger |
| `src/XRay.tsx` | The five-step view of one question and the traffic proof |
| `src/api.ts` | Typed client for `api/app.py` (Server-Sent Events over POST) |
| `../api/app.py` | Thin FastAPI wrapper over C's pipeline, B's wiretap search and the plaintext server |

Design notes: `docs/superpowers/specs/2026-11-15-web-ui-design.md`. Colours and type are tokens in `src/index.css`.

## Node.js on WSL or Linux

The page is built with Vite 8, which needs Node.js 20.19 or newer **installed inside WSL** (a Windows npm on the
PATH fails with "UNC paths are not supported"). Without sudo:

```
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
source ~/.nvm/nvm.sh && nvm install 22
which npm      # should be under ~/.nvm, not /mnt/c
```
