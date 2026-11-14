# Setup

Maintained by A. Updated whenever a piece lands that changes what you need to install or run. **Check the changelog at the bottom after every pull.**

## Who needs what

| | A (Windows) | B (Mac) | C (Mac, demo laptop) |
| --- | --- | --- | --- |
| Git, Python 3.11+ | Yes | Yes | Yes |
| Go 1.22+ and Microsoft SEAL | Yes, inside WSL2 | **No** | Yes (runs the crypto-helper) |
| ML stack (sentence-transformers, Ollama) | No | Yes | Yes |

B never needs the crypto toolchain. B's whole contract with crypto is the three files in `data/` (format below).

## Mac (B and C)

```bash
xcode-select --install                  # C/C++ compiler, once
brew install go cmake python@3.12
git clone https://github.com/IshanEdlabadkar/blindspot && cd blindspot
```

C only, once, for the crypto parts:

```bash
make seal        # builds Microsoft SEAL 4.1.1 into /usr/local (~5 min, asks for sudo)
make test        # should print "ok" twice
```

If the build fails with an error mentioning `-march=native`, run `./scripts/fix_march.sh`, then `make test` again.

## Windows (A): use WSL2

The crypto code wraps a C++ library through cgo, which does not build cleanly on native Windows. Run it in WSL2. Servers started there are reachable from Windows at `http://localhost:8080`.

In PowerShell as administrator, once: `wsl --install -d Ubuntu`. Then in the Ubuntu terminal:

```bash
sudo apt update && sudo apt install -y build-essential cmake git golang-go python3 python3-pip python3-numpy python3-requests
go version       # needs 1.22 or newer
git clone https://github.com/IshanEdlabadkar/blindspot ~/blindspot && cd ~/blindspot
make seal && make test
```

Keep the repo inside the WSL filesystem (`~/blindspot`), not under `/mnt/c/`. Builds there are much slower.

**If WSL says "Catastrophic failure, Error code: Wsl/Service/E_UNEXPECTED"** (seen on A's laptop):

1. PowerShell as admin: `wsl --shutdown`, `wsl --update`, then `wsl -d Ubuntu`.
2. If Ubuntu opens as `root` or the username prompt keeps failing, create the user by hand. Usernames must be lowercase.
   ```bash
   adduser --gecos "" ishan && usermod -aG sudo ishan
   printf '[user]\ndefault=ishan\n' > /etc/wsl.conf
   exit
   ```
   Then `wsl --shutdown` and `wsl -d Ubuntu` in PowerShell.
3. "Failed to detect nested virtualization support" is a harmless warning; ignore it.

Verified on A's Windows laptop (WSL2, Ubuntu): `make test` passes.

## Data files (B writes, the server reads)

The server reads these three files from `data/` (B's real ones, or `tools/make_dummy_tables.py` output):

| File | Format |
| --- | --- |
| `manifest.json` | Spec schema. Must have `corpus_version`, `num_chunks`, `embedding.dim`, `pir.record_bytes`. |
| `score_table.bin` | N x 384 int8, row by row. **Rows L2-normalized before `round(x * 127)`**, or encrypted scores can wrap. The server prints a WARNING at startup if they aren't. |
| `fetch_store.bin` | N x 2048 bytes; use `contracts.pack_record()`. |

## Switching C's pipeline to real crypto

Three processes, each in its own terminal:

```bash
make server      # A's document server :8080, ~5 s to start, log at data/server.log
make helper      # asker-side key holder :8090 (on the demo laptop)
BLIND_RAG_CRYPTO=real BLIND_RAG_FETCH=download streamlit run ui/app.py
```

- **`BLIND_RAG_FETCH=download` is required with real crypto.** Fetch is trivial PIR: the client downloads the whole 10 MB store once and reads chunks locally.
- The UI reads `data/server.log` by default, which is where the real server writes too.
- To check everything at once after merging: `make integration`. It runs C's pipeline with real crypto and with the mock, and checks that both return the same top 10 chunks. Last run: ALL PASS, about 4 s per question.

## What to expect (measured, N = 5,000, 2-vCPU cloud VM)

| | Value |
| --- | --- |
| Server startup precompute | ~5 s |
| Per question: encrypt on device | ~1.1 s |
| Per question: `/v1/score` round trip | ~3.0 s |
| Upload per question | ~34 MB |
| Download per question | ~0.8 MB, plus 10 MB fetch store once per corpus version |

## Changelog

- **Nov 14, 17:20:** `make test` verified on A's Windows laptop (WSL2). Added the WSL "Catastrophic failure" fix.
- **Nov 14, 17:10:** aligned with C's `contracts.py`: `X-Corpus-Version` header, log to `data/server.log` with the four agreed fields. Added the crypto-helper and real `client/crypto_client`, plus `make helper` and `make integration`.
- **Nov 14, 17:00:** document server with `/v1/manifest`, `/v1/score`, `/v1/fetch_store`. Fetch is trivial PIR. `make seal`, `make test`, `make server`.
