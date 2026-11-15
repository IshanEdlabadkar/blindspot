# Deploying the document server remotely

The `Dockerfile` and `render.yaml` in this repository are what Render builds from.

Three separate pieces, owned the way a real provider would own them:

| Piece | Where | Who |
| --- | --- | --- |
| Corpus files (manifest, score table, fetch store) | A Databricks Unity Catalog volume: the provider's storage | B publishes with `scripts/publish_corpus.sh` |
| Document server (code only, no data) | Render, built from this repo's `Dockerfile` | A |
| crypto-helper + UI (holds the only keys) | The asker's laptop | C |

The server loads the corpus from the volume at startup and checks every sha256 hash in the manifest. Every minute it checks for a new `corpus_version` and swaps it in without a restart. If an upload is incomplete or corrupt, it keeps serving the old version. Clients holding the old version get HTTP 409 and reload the manifest.

**Status:** the server code, URL loading, hash checks, live swap, and the publish script are tested, including end to end against a stand-in for Databricks' file API. Not yet tested against real Databricks or real Render: the Docker image has never been built, because this workspace can't reach Docker Hub.

## 1. Databricks: create the volume and a token (once)

On Databricks Free Edition:

1. **Catalog** > pick a catalog (Free Edition has one called `workspace`) and schema (`default`) > **Create > Volume**, named `blindrag` (managed).
2. **Settings > Developer > Access tokens > Generate new token**. Copy it; it's shown once.
3. Note your workspace URL, such as `https://<something>.cloud.databricks.com`.

## 2. B: publish the corpus (every time the corpus changes)

```bash
export DATABRICKS_HOST=https://<workspace>.cloud.databricks.com
export DATABRICKS_TOKEN=<token>
export BLIND_RAG_VOLUME=/Volumes/workspace/default/blindrag/corpus
./scripts/publish_corpus.sh artifacts
```

The script checks the hashes and scale locally first, uploads the data files and then the manifest, and prints the two values for step 3. Bump `corpus_version` whenever the files change; that's what the server watches.

Optional next step: run B's ingestion as a scheduled Databricks job that writes straight to the volume. Note that Free Edition limits outbound internet to trusted domains unless the account is verified, so downloading MedlinePlus pages and the embedding model from a job may be blocked.

## 3. Render: the server (once)

1. Sign in at render.com **with GitHub** and give it access to `IshanEdlabadkar/blindspot`.
2. **New > Blueprint**, pick the repo, **Apply**. Render reads `render.yaml`: one web service, `blind-rag-server`, plan `0.5c-512mb` (paid; the free plan sleeps when idle).
3. In the service's **Environment** tab, set the two secrets the publish script printed:
   - `BLIND_RAG_DATA_URL` = `https://<workspace>.cloud.databricks.com/api/2.0/fs/files/Volumes/workspace/default/blindrag/corpus/`
   - `BLIND_RAG_DATA_AUTH` = `Bearer <token>`
4. Deploy. The first build compiles SEAL (about 5 to 10 minutes). On startup the server logs `corpus source: ...` (without the token) and `serving corpus <version>`.

Check it:

```bash
curl https://<your-service>.onrender.com/v1/manifest      # corpus_version, scoring.hint_url starts with https://
curl https://<your-service>.onrender.com/v1/server_log
```

If the build or startup fails, the last lines of the Render log say which step.

## 3b. More providers: one server per corpus

Each corpus is its own provider with its own server, in its own folder of the volume
(`/Volumes/workspace/default/blindrag/<source_id>/`). Same image and code, different data:

| source_id | corpus | chunks | Render service |
|---|---|---|---|
| `medlineplus` | MedlinePlus health topics | 2,101 | `blindspot` (existing) |
| `fmla` | FMLA regulations, 29 CFR Part 825 | 310 | `blindspot-fmla` |
| `genetics` | MedlinePlus Genetics | 2,067 | `blindspot-genetics` |
| `myhealthfinder` | MyHealthfinder (health.gov) | 524 | `blindspot-myhealthfinder` |

1. Verify B's handoff folder, then publish each corpus to its own folder (token only in your shell):
   ```
   (cd blindrag-corpus && sha256sum -c SHA256SUMS)
   for s in medlineplus fmla genetics myhealthfinder; do
     BLIND_RAG_VOLUME=/Volumes/workspace/default/blindrag/$s ./scripts/publish_corpus.sh blindrag-corpus/$s
   done
   ```
2. Render, for each new service: **New > Web Service**, this repo, branch `deploy/render`, runtime Docker, region Oregon, plan Free. Environment:
   - `BLIND_RAG_DATA_URL` = `https://<workspace>.cloud.databricks.com/api/2.0/fs/files/Volumes/workspace/default/blindrag/<source_id>/`
   - `BLIND_RAG_DATA_AUTH` = `Bearer <token>` (the same read token)

   The Dockerfile already sets hint mode, the public log and `/data`; nothing else is needed. (Created by hand rather than
   as `render.yaml` entries: the existing service was not made from the Blueprint, so applying it would create a duplicate,
   paid `blind-rag-server`.)
3. Check: `curl https://<service>.onrender.com/v1/manifest` shows its `source_id`, `corpus_version`, `num_chunks`;
   `/v1/server_log` shows only `ts, endpoint, response_bytes, latency_ms`.
4. Put the URLs in `servers.remote.json`. `make demo` searches every hosted server (waking them in parallel); one that
   doesn't answer is replaced by a local server from its backup in `artifacts/<id>/`. `LOCAL=1 make demo` is fully offline.
   Databricks is always the first source; the copies in the repo are the backup.

Moving a service to a folder that holds the **same `corpus_version`** (a rename) needs **Manual Deploy > Restart service**:
the server only swaps live when the version changes. A new `corpus_version` is picked up within a minute, no restart.

## 4. The demo laptop

```bash
make helper                                    # local: holds the keys
BLIND_RAG_SERVER=https://<your-service>.onrender.com python3 scripts/measure.py --log /dev/null
```

The first question downloads the 17 MB scoring hint and the 4.3 MB fetch store once; both are cached. Each question after that is about 3 KB up and 17 KB down.

### What C needs to change for a remote server

1. **Server panel:** read `GET <server>/v1/server_log?n=50` instead of the local `data/server.log`. It returns the same JSON lines and isn't itself logged. For example, in `ui/app.py`:
   ```python
   def log_lines(k=15):
       src = os.environ.get("BLIND_RAG_SERVER_LOG", "")
       if src.startswith("http"):
           return [json.loads(l) for l in requests.get(src, params={"n": k}, timeout=5).text.splitlines()]
       ...  # existing file path
   ```
   Then run with `BLIND_RAG_SERVER_LOG=https://<server>/v1/server_log`.
2. **`make demo`:** when `BLIND_RAG_SERVER` points at a remote URL, skip starting the local server and start only the helper and the UI.

## Server settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `BLIND_RAG_DATA_URL` | (none) | Base URL of the corpus files. Overrides `BLIND_RAG_DATA_DIR`. A query string (a signed-URL token) is kept on every request. |
| `BLIND_RAG_DATA_AUTH` | (none) | `Authorization` header for that URL, such as `Bearer <token>`. Never logged. |
| `BLIND_RAG_DATA_DIR` | `../artifacts` (`/data` in Docker) | A local or mounted folder, used when no URL is set. |
| `BLIND_RAG_DATA_POLL` | `1m` | How often to check for a new `corpus_version` (`0` = never). |
| `BLIND_RAG_TOKEN_MODE` | on (off in Docker) | 33 MB-per-question fallback. Costs about 650 MB RAM, so it's off on Render. |
| `BLIND_RAG_PIR` | on | Real PIR fetch at `/v1/fetch` (about 50 MB RAM). |
| `BLIND_RAG_PUBLIC_LOG` | off (on in Docker) | `GET /v1/server_log`. |
| `PORT` | Render sets it | The server binds `0.0.0.0:$PORT`. |

## Fallback on the day

If Render, Databricks or the venue network misbehaves, run `make demo` with everything on the laptop. It reads `artifacts/` locally.

## Other hosts and storage

The same image runs anywhere with Docker. Point `BLIND_RAG_DATA_URL` at any HTTPS storage (S3 or R2 signed URLs, a private web server), or mount a folder:

```bash
docker build -t blind-rag-server .
docker run -p 8080:8080 -e BLIND_RAG_DATA_URL=https://<storage>/<corpus>/ blind-rag-server
docker run -p 8080:8080 -v /srv/corpus:/data:ro blind-rag-server
```
