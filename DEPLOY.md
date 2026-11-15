# Deploying the document server remotely (Render)

On Render the server runs hint-mode scoring plus real PIR fetch, with token mode off: ~210 MB RAM, about 3 s startup, and about 3 KB uploaded per question (171 KB with real PIR fetch). The asker's device still runs the crypto-helper and the UI locally. Keys never leave the device.

**Status:** the Dockerfile's build steps are the same ones verified on Linux and WSL (SEAL 4.1.1, a portable build without `-march=native`, offline Go build). The image itself has not been built yet, because the workspace it was written in can't reach Docker Hub. The first Render build is its first real test. If it fails, the build log shows exactly which step.

## 1. Get the code onto `main`

The image bakes in B's tables from `artifacts/`, which live on `main`. Merge `person-a/crypto` into `main` (a pull request on GitHub). It merges with no conflicts.

## 2. Create the service on Render

1. Sign in at render.com with GitHub and give it access to `IshanEdlabadkar/blindspot`.
2. **New > Blueprint**, pick the repo. Render reads `render.yaml` and proposes one web service, `blind-rag-server`, on the `0.5c-512mb` plan (paid; the free plan sleeps when idle and takes about a minute to wake). Click **Apply**.
3. The first build compiles SEAL and takes about 5 to 10 minutes. After that, every push to `main` redeploys automatically (`autoDeployTrigger: commit`).

Without the Blueprint, use **New > Web Service**, pick the repo, choose **Docker**, set the health check path to `/v1/manifest`, and add the environment variables `BLIND_RAG_TOKEN_MODE=0` and `BLIND_RAG_PUBLIC_LOG=1`.

## 3. Check it

```bash
curl https://blind-rag-server.onrender.com/v1/manifest      # use your service's URL
curl https://blind-rag-server.onrender.com/v1/server_log
```

The manifest's `scoring.hint_url` should start with `https://`.

## 4. Point the demo laptop at it

```bash
make helper                                                   # still local: holds the keys
BLIND_RAG_SERVER=https://blind-rag-server.onrender.com python3 scripts/measure.py --log /dev/null
```

The first question downloads the 17 MB scoring hint and the 4.3 MB fetch store once. Both are cached; the hint is cached on disk in `~/.cache/blind-rag/`. After that, each question is about 3 KB up and 17 KB down.

## What C needs to change for a remote server

1. **Server panel:** the UI reads `data/server.log`, a local file. With a remote server, read `GET <server>/v1/server_log?n=50` instead. It returns the same JSON lines (`ts`, `endpoint`, `response_bytes`, `latency_ms`) and is not itself logged. For example, in `ui/app.py`:
   ```python
   def log_lines(k=15):
       src = os.environ.get("BLIND_RAG_SERVER_LOG", "")
       if src.startswith("http"):
           return [json.loads(l) for l in requests.get(src, params={"n": k}, timeout=5).text.splitlines()]
       ...  # existing file path
   ```
   Then run with `BLIND_RAG_SERVER_LOG=https://<server>/v1/server_log`.
2. **`make demo`:** it starts a local server on :8080. With `BLIND_RAG_SERVER` set to a remote URL, it should skip that and start only the helper and the UI.

## Fallback on the day

If Render or the venue network misbehaves, run `make demo` with everything on the laptop. Nothing else changes.

## Other hosts

The same image runs anywhere with Docker:

```bash
docker build -t blind-rag-server .     # on a branch with artifacts/
docker run -p 8080:8080 blind-rag-server
```

Put HTTPS in front of it with any reverse proxy, such as Caddy. The server builds `hint_url` from the `Host` and `X-Forwarded-Proto` headers.
