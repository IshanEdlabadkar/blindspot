#!/usr/bin/env bash
# The Vault web UI with everything behind it, in one terminal:
#   ./web/demo.sh            hosted document servers (servers.remote.json); any that doesn't wake falls
#                            back to a local server on its repo backup in artifacts/<id>/
#   LOCAL=1 ./web/demo.sh    all local (servers.json), offline
# Open http://localhost:8600 . C's Streamlit UI still runs on :8501 as the fallback.
# Every byte the app sends to a document server goes through a recording relay (:9080+, plain :9001), so the
# X-ray view can search that traffic for the asker's words. Ctrl+C stops everything this script started.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data
PY=$(./scripts/find_python.sh sentence_transformers) || exit 1
export PYTHON="$PY"
"$PY" -c "import fastapi, uvicorn" 2>/dev/null || { echo "ERROR: $PY needs FastAPI: $PY -m pip install fastapi uvicorn"; exit 1; }
pids=()
cleanup() { for p in ${pids[@]+"${pids[@]}"}; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT
up() { curl -fsS -o /dev/null --max-time "${2:-3}" "$1" 2>/dev/null; }
wait_up() { for _ in $(seq 1 "${3:-120}"); do up "$1" && return 0; sleep 0.5; done; echo "ERROR: $2 did not start"; return 1; }

LIST=servers.remote.json; [ "${LOCAL:-0}" = 1 ] && LIST=servers.json
ENTRIES=()   # macOS bash 3.2 has no mapfile
while IFS= read -r line; do ENTRIES+=("$line"); done < <("$PY" -c 'import json,sys; [print(s["id"], s["url"]) for s in json.load(open(sys.argv[1]))]' "$LIST")
echo "Document servers from $LIST:"

built=0
local_server() {  # id port -> starts a local document server on artifacts/<id>
  [ -f "artifacts/$1/manifest.json" ] || { echo "ERROR: artifacts/$1/ missing"; exit 1; }
  [ $built = 1 ] || { (cd crypto-server && go build -o crypto-server .) && built=1; }
  ./crypto-server/crypto-server -data "artifacts/$1" -addr "127.0.0.1:$2" -log "data/server-$1.log" \
    > "data/server-$1.out" 2>&1 & pids+=($!)
  wait_up "http://127.0.0.1:$2/v1/manifest" "local $1 server"
}

# Wake every hosted server at once (a sleeping free Render service takes up to ~1 min), then check each.
for e in "${ENTRIES[@]}"; do
  url=${e#* }
  [[ $url == http://127.0.0.1:* || $url == http://localhost:* ]] || { curl -s -o /dev/null --max-time 90 "$url/v1/manifest" & }
done
echo "  waking the hosted servers together (up to ~1 min if they were asleep)..."
wait

routes=(--route "plain:9001=http://127.0.0.1:8001")
relays=()
i=0
for e in "${ENTRIES[@]}"; do
  id=${e%% *}; url=${e#* }
  if [[ $url == http://127.0.0.1:* || $url == http://localhost:* ]]; then
    up "$url/v1/manifest" || local_server "$id" "${url##*:}"
  else
    printf "  %s ... " "$id"
    ok=0; for _ in 1 2 3; do up "$url/v1/manifest" 15 && { ok=1; break; }; sleep 2; done
    if [ $ok = 1 ]; then echo "hosted"; else
      url="http://127.0.0.1:$((8080 + i))"; echo "asleep, using local backup on $url"; local_server "$id" "${url##*:}"; fi
  fi
  routes+=(--route "$id:$((9080 + i))=$url"); relays+=("http://127.0.0.1:$((9080 + i))")
  i=$((i + 1))
done
WIRE=$(IFS=,; echo "${relays[*]}")

"$PY" -m wiretap.proxy --fresh "${routes[@]}" > data/wiretap.out 2>&1 & pids+=($!)
wait_up "http://127.0.0.1:9080/v1/manifest" "recording relay" 40
cat data/wiretap.out

# Key helper, plaintext "normal" server and C's Streamlit UI (fallback, :8501); servers come from the relays.
WIRETAP_SERVERS="$WIRE" BLIND_RAG_SERVERS="$WIRE" BLIND_RAG_PLAIN_SERVER=http://127.0.0.1:9001 \
  make demo > data/streamlit-demo.out 2>&1 & pids+=($!)
wait_up http://127.0.0.1:8090/health "key helper" 240
wait_up http://127.0.0.1:8001/health "plaintext demo server" 240

if [ ! -f web/dist/index.html ] || [ -n "$(find web/src web/index.html -newer web/dist/index.html 2>/dev/null | head -1)" ]; then
  echo "Building the web UI..."; (cd web && npm install --silent && npm run build --silent) >/dev/null
fi
echo
echo "  Blind RAG is ready:  http://localhost:8600     (fallback UI: http://localhost:8501)"
echo
BLIND_RAG_SERVERS="$WIRE" BLIND_RAG_PLAIN_SERVER=http://127.0.0.1:9001 BLIND_RAG_CRYPTO=real BLIND_RAG_ANSWER=real \
  BLIND_RAG_FETCH="${BLIND_RAG_FETCH:-download}" \
  "$PY" -m uvicorn api.app:app --host 127.0.0.1 --port 8600 --log-level warning
