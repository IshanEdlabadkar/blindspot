# Setup

Maintained by A. Updated whenever a piece lands that changes what you need to install or run. Check the changelog at the bottom after every pull.

## Who needs what

| | A (Windows) | B (Mac) | C (Mac) |
| --- | --- | --- | --- |
| Git, Python 3.11+ | Yes | Yes | Yes |
| Go 1.22+ and Microsoft SEAL | Yes (inside WSL2) | **No** | Yes (runs the client helper on the demo laptop) |
| ML stack (sentence-transformers, Ollama) | Optional | Yes | Yes (for the live demo) |

B never needs the crypto toolchain. B's only contract with crypto is the three files in `data/` (format below).

## Mac (B and C)

```bash
xcode-select --install                  # C/C++ compiler, once
brew install go cmake python@3.12
git clone https://github.com/IshanEdlabadkar/blindspot && cd blindspot
```

C only, for the crypto parts:

```bash
make seal        # builds Microsoft SEAL 4.1.1 into /usr/local (~5 min, asks for sudo)
make test        # should end with PASS twice
```

If `make test` fails with an error mentioning `-march=native`, run `./scripts/fix_march.sh` and then `make test` again.

## Windows (A): use WSL2

The crypto code wraps a C++ library through cgo, which does not build cleanly on native Windows. Run it in WSL2. Servers started there are reachable from Windows at `http://localhost:8080`.

In PowerShell as administrator, once:

```powershell
wsl --install -d Ubuntu
```

Then in the Ubuntu terminal:

```bash
sudo apt update && sudo apt install -y build-essential cmake git golang-go python3 python3-pip
go version       # needs 1.22 or newer
git clone https://github.com/IshanEdlabadkar/blindspot && cd blindspot
make seal && make test
```

Keep the repo inside the WSL filesystem (`~/blindspot`), not under `/mnt/c/`. Builds there are much slower.

## Running the document server

Needs these three files in `data/` (B's real ones, or C's dummy ones):

| File | Format |
| --- | --- |
| `manifest.json` | Spec schema. Must have `corpus_version`, `num_chunks`, `embedding.dim`, `pir.record_bytes`. |
| `score_table.bin` | N x d int8, row by row, no header. Rows must be L2-normalized before `round(x * 127)`. |
| `fetch_store.bin` | N x L bytes. Each record: u16 little-endian length, chunk JSON, zero padding. |

```bash
make server      # http://127.0.0.1:8080; takes ~5 s to precompute before it accepts requests
```

The server checks the file sizes against the manifest and refuses to start with a clear message if they don't match.

## Server API (for C)

| Endpoint | What it does |
| --- | --- |
| `GET /v1/manifest` | B's manifest plus `scoring.seed` (hex), `scoring.modulus`, `pir.mode = "trivial"` |
| `POST /v1/score` | Binary body, see `crypto-server/blindcrypto/wire.go`. 409 if `corpus_version` is stale. |
| `GET /v1/fetch_store` | The whole fetch store (~10 MB). Download once per corpus version and read chunks locally. |

Log format, one JSON object per line on stdout (no request bodies, ever):

```json
{"ts": "2026-11-14T22:55:45Z", "endpoint": "/v1/score", "status": 200, "response_bytes": 829288, "latency_ms": 3061.4}
```

## Coming next (not usable yet)

- **Client helper (`crypto-helper`):** a local Go process on the asker's device that holds keys in memory. C's Python `crypto_client` functions will call it on localhost. Same signatures as `client/crypto_client/__init__.py`.

## Changelog

- **Nov 14, 17:00:** document server with `/v1/manifest`, `/v1/score`, `/v1/fetch_store`. Fetch is trivial PIR (decided by A). `make seal`, `make test`, `make server`.
