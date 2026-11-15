#!/usr/bin/env bash
# Start the whole real system in ONE terminal: A's server, the crypto-helper, then the UI.
#   make demo            (Ctrl+C stops everything this script started)
#   (B's plaintext "normal RAG" server on :8001 always starts too, for the log contrast;
#    PLAIN=0 make demo skips it)
#   Document servers come from servers.json: one local server per entry, from artifacts/<id>/
#   (MedlinePlus on :8080, FMLA on :8081). REMOTE=1 make demo uses servers.remote.json instead
#   (the hosted servers on Render). BLIND_RAG_SERVER=https://host make demo   just that one server
# Reuses a server or helper that is already running. Logs: data/server.out, data/helper.out
set -euo pipefail
cd "$(dirname "$0")/.."
DATA="${DATA:-artifacts}"
mkdir -p data
pids=()
cleanup() { for p in ${pids[@]+"${pids[@]}"}; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT
up() { curl -fsS -o /dev/null --max-time 2 "$1" 2>/dev/null; }
wait_for() {  # name url logfile
  for _ in $(seq 1 120); do up "$2" && { echo "  $1 ready"; return 0; }; sleep 0.5; done
  echo "ERROR: $1 did not start. Last lines of $3:"; tail -n 15 "$3" || true; exit 1
}

# Pick a Python that actually has the packages (Homebrew can repoint python3 at a bare install).
extra=""
[ "${BLIND_RAG_EMBED:-real}" = fake ] || extra="sentence_transformers"
PY=$(./scripts/find_python.sh "$extra") || exit 1
echo "Using $("$PY" -c 'import sys; print(sys.executable)')"

if [ "${1:-}" = "--preflight" ]; then shift; exec "$PY" demo/preflight.py "$@"; fi

echo "Building crypto binaries..."
(cd crypto-server && go build -o crypto-server . && go build -o crypto-helper ./cmd/crypto-helper)

start_local() {  # url data_dir
  local port=${1##*:}; port=${port%%/*}
  local log=data/server.log; [ "$port" = 8080 ] || log="data/server-$port.log"
  if up "$1/v1/manifest"; then
    echo "  server on :$port already running, reusing it (just pulled new code? run: make stop, then make demo)"
  else ./crypto-server/crypto-server -data "$2" -addr "127.0.0.1:$port" -log "$log" > "data/server-$port.out" 2>&1 & pids+=($!)
       wait_for "document server (:$port, $2)" "$1/v1/manifest" "data/server-$port.out"; fi
}
check_remote() {  # url   (a free Render server may be asleep: the first request can take ~1 min)
  echo "  checking remote document server $1 (can take ~1 min if it was asleep)..."
  local code=000
  for _ in $(seq 1 12); do
    code=$(curl -sS -o /dev/null -w "%{http_code}" --max-time 15 "$1/v1/manifest" 2>/dev/null || true)
    [ "$code" = 200 ] && { echo "  using remote document server $1"; return 0; }
    sleep 3
  done
  echo "ERROR: document server $1 did not answer (last HTTP status: $code)."
  echo "       Open $1/v1/manifest in a browser: if it loads, run make demo again."
  exit 1
}

# Which document servers: BLIND_RAG_SERVER (one), DATA=<folder> (one local), else the server list:
# servers.json (local, one server per artifacts/<id>/) or, with REMOTE=1, servers.remote.json.
servers=()
if [ -n "${BLIND_RAG_SERVER:-}" ]; then
  servers=("${BLIND_RAG_SERVER%/}|$DATA")
elif [ "$DATA" != artifacts ]; then
  servers=("http://127.0.0.1:8080|$DATA")
else
  [ "${REMOTE:-0}" = 1 ] && export BLIND_RAG_SERVERS_FILE="${BLIND_RAG_SERVERS_FILE:-servers.remote.json}"
  LIST="${BLIND_RAG_SERVERS_FILE:-servers.json}"
  echo "Document servers from $LIST:"
  while IFS= read -r line; do servers+=("$line"); done < <("$PY" - "$LIST" <<'PY'
import json, os, sys
for e in json.load(open(sys.argv[1])):
    d = os.path.join("artifacts", e["id"])
    print(f"{e['url'].rstrip('/')}|{d if os.path.isdir(d) else 'artifacts'}")
PY
)
fi
urls=()
for s in "${servers[@]}"; do
  url=${s%%|*}; dir=${s#*|}; urls+=("$url")
  case "$url" in
    http://127.0.0.1:*|http://localhost:*) start_local "$url" "$dir" ;;
    *) check_remote "$url" ;;
  esac
done
BLIND_RAG_SERVERS=$(IFS=,; echo "${urls[*]}"); export BLIND_RAG_SERVERS
unset BLIND_RAG_SERVER
echo "  the UI offers: $BLIND_RAG_SERVERS"

if up http://127.0.0.1:8090/health; then echo "  helper already running, reusing it"
else ./crypto-server/crypto-helper > data/helper.out 2>&1 & pids+=($!)
     wait_for "crypto-helper (:8090)" http://127.0.0.1:8090/health data/helper.out; fi

export BLIND_RAG_CRYPTO=real
export BLIND_RAG_ANSWER="${BLIND_RAG_ANSWER:-real}"
if [ "$BLIND_RAG_ANSWER" = real ] && ! up http://127.0.0.1:11434/api/tags; then
  echo "WARNING: Ollama is not answering on :11434. Run: brew services start ollama"
fi
# B's plaintext "normal RAG server" for the side-by-side log contrast: on by default (PLAIN=0 skips it).
if [ "${PLAIN:-1}" = 1 ]; then
  if up http://127.0.0.1:8001/health; then echo "  plaintext demo server already running, reusing it"
  else "$PY" -m baseline.server > data/plain.out 2>&1 & pids+=($!)
       wait_for "plaintext demo server (:8001, warming the model)" http://127.0.0.1:8001/health data/plain.out; fi
fi
echo "Starting the UI..."
"$PY" -m streamlit run ui/app.py "$@"
