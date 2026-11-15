#!/usr/bin/env bash
# Start the whole real system in ONE terminal: A's server, the crypto-helper, then the UI.
#   make demo            (Ctrl+C stops everything this script started)
#   (B's plaintext "normal RAG" server on :8001 always starts too, for the log contrast;
#    PLAIN=0 make demo skips it)
#   Document servers: the hosted ones in servers.remote.json (corpora on Databricks) first; any that
#   doesn't answer falls back to a local server from its repo backup in artifacts/<id>/.
#   LOCAL=1 make demo: all local from servers.json (offline). BLIND_RAG_SERVER=<url>: just that one.
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
# Which document servers: BLIND_RAG_SERVER (one), DATA=<folder> (one local), else a server list.
# Default: the hosted servers in servers.remote.json (Databricks-backed). A hosted server that does not
# answer is replaced by a local server from its backup in artifacts/<id>/, if the repo has one.
# LOCAL=1: everything local from servers.json (offline).
servers=()   # each: url|backup_dir|local_url
if [ -n "${WIRETAP_SERVERS:-}" ]; then
  # ./web/demo.sh or ./wiretap/demo.sh already chose the document servers (hosted, or local backups)
  # and put the recording relays in front of them; start none here.
  servers=()
elif [ -n "${BLIND_RAG_SERVER:-}" ]; then
  servers=("${BLIND_RAG_SERVER%/}|$DATA|http://127.0.0.1:8080")
elif [ "$DATA" != artifacts ]; then
  servers=("http://127.0.0.1:8080|$DATA|http://127.0.0.1:8080")
else
  if [ "${LOCAL:-0}" = 1 ]; then LIST="${BLIND_RAG_SERVERS_FILE:-servers.json}"
  else LIST="${BLIND_RAG_SERVERS_FILE:-servers.remote.json}"; fi
  echo "Document servers from $LIST:"
  while IFS= read -r line; do servers+=("$line"); done < <("$PY" - "$LIST" <<'PY'
import json, os, sys
for i, e in enumerate(json.load(open(sys.argv[1]))):
    d = os.path.join("artifacts", e["id"])
    print(f"{e['url'].rstrip('/')}|{d if os.path.isfile(os.path.join(d, 'manifest.json')) else ''}|http://127.0.0.1:{8080 + i}")
PY
)
fi
is_local() { case "$1" in http://127.0.0.1:*|http://localhost:*) return 0 ;; esac; return 1; }

# Wake every hosted server at once (a sleeping free Render service takes up to ~1 min), then check each.
wake=()
for s in ${servers[@]+"${servers[@]}"}; do
  url=${s%%|*}; is_local "$url" || { curl -s -o /dev/null --max-time 90 "$url/v1/manifest" & wake+=($!); }
done
if [ ${#wake[@]} -gt 0 ]; then
  echo "  waking ${#wake[@]} hosted server(s) (up to ~1 min if they were asleep)..."
  wait "${wake[@]}" 2>/dev/null || true
fi
urls=()
for s in ${servers[@]+"${servers[@]}"}; do
  IFS='|' read -r url dir lurl <<< "$s"
  if is_local "$url"; then
    start_local "$url" "${dir:-artifacts}"; urls+=("$url")
  elif [ "$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 "$url/v1/manifest" 2>/dev/null || true)" = 200 ]; then
    echo "  using hosted server $url"; urls+=("$url")
  elif [ -n "$dir" ]; then
    echo "  WARNING: $url did not answer; using the repo backup $dir on $lurl instead"
    start_local "$lurl" "$dir"; urls+=("$lurl")
  else
    echo "  WARNING: $url did not answer and the repo has no backup for it; leaving it out"
  fi
done
[ ${#urls[@]} -gt 0 ] || [ -n "${WIRETAP_SERVERS:-}" ] || { echo "ERROR: no document server available."; exit 1; }
BLIND_RAG_SERVERS=$(IFS=,; echo "${urls[*]:-}"); export BLIND_RAG_SERVERS
[ -z "${WIRETAP_SERVERS:-}" ] || BLIND_RAG_SERVERS="$WIRETAP_SERVERS"   # keep the UI on the recording relays
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
