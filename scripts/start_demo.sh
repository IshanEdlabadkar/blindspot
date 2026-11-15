#!/usr/bin/env bash
# Start the whole real system in ONE terminal: A's server, the crypto-helper, then the UI.
#   make demo            (Ctrl+C stops everything this script started)
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

echo "Building crypto binaries..."
(cd crypto-server && go build -o crypto-server . && go build -o crypto-helper ./cmd/crypto-helper)

if up http://127.0.0.1:8080/v1/manifest; then echo "  server already running, reusing it"
else ./crypto-server/crypto-server -data "$DATA" -log data/server.log > data/server.out 2>&1 & pids+=($!)
     wait_for "document server (:8080)" http://127.0.0.1:8080/v1/manifest data/server.out; fi

if up http://127.0.0.1:8090/health; then echo "  helper already running, reusing it"
else ./crypto-server/crypto-helper > data/helper.out 2>&1 & pids+=($!)
     wait_for "crypto-helper (:8090)" http://127.0.0.1:8090/health data/helper.out; fi

export BLIND_RAG_CRYPTO=real
export BLIND_RAG_ANSWER="${BLIND_RAG_ANSWER:-real}"
if [ "$BLIND_RAG_ANSWER" = real ] && ! up http://127.0.0.1:11434/api/tags; then
  echo "WARNING: Ollama is not answering on :11434. Run: brew services start ollama"
fi
echo "Starting the UI..."
python3 -m streamlit run ui/app.py "$@"
