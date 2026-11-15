#!/usr/bin/env bash
# Start the whole real system in ONE terminal: A's server, the crypto-helper, then the UI.
#   make demo            (Ctrl+C stops everything this script started)
#   make demo-compare    same, plus B's plaintext server for the log contrast
#   BLIND_RAG_SERVER=https://host make demo   use a remote document server
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
need="streamlit, numpy, requests"
[ "${BLIND_RAG_EMBED:-real}" = fake ] || need="$need, sentence_transformers"
PY=""
for cand in "${PYTHON:-}" python3.12 /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
            /opt/homebrew/opt/python@3.12/bin/python3.12 python3 python; do
  [ -n "$cand" ] || continue
  if "$cand" -c "import $need" >/dev/null 2>&1; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then
  echo "ERROR: no Python found with: $need"
  echo "Fix:   python3.12 -m pip install streamlit numpy requests sentence-transformers"
  exit 1
fi
echo "Using $("$PY" -c 'import sys; print(sys.executable)')"

if [ "${1:-}" = "--preflight" ]; then shift; exec "$PY" demo/preflight.py "$@"; fi

echo "Building crypto binaries..."
(cd crypto-server && go build -o crypto-server . && go build -o crypto-helper ./cmd/crypto-helper)

SERVER="${BLIND_RAG_SERVER:-http://127.0.0.1:8080}"
case "$SERVER" in
  http://127.0.0.1:8080*|http://localhost:8080*)
    if up http://127.0.0.1:8080/v1/manifest; then
      echo "  server already running, reusing it (just pulled new code? run: make stop, then make demo)"
    else ./crypto-server/crypto-server -data "$DATA" -log data/server.log > data/server.out 2>&1 & pids+=($!)
         wait_for "document server (:8080)" http://127.0.0.1:8080/v1/manifest data/server.out; fi ;;
  *)
    # A hosted server may be asleep: the first request can take about a minute to wake it.
    echo "  checking remote document server $SERVER (can take ~1 min if it was asleep)..."
    code=000
    for _ in $(seq 1 12); do
      code=$(curl -sS -o /dev/null -w "%{http_code}" --max-time 15 "$SERVER/v1/manifest" 2>/dev/null || true)
      [ "$code" = 200 ] && break
      sleep 3
    done
    if [ "$code" = 200 ]; then echo "  using remote document server $SERVER"
    else
      echo "ERROR: document server $SERVER did not answer (last HTTP status: $code)."
      echo "       Open $SERVER/v1/manifest in a browser: if it loads, run make demo again."
      exit 1
    fi ;;
esac

if up http://127.0.0.1:8090/health; then echo "  helper already running, reusing it"
else ./crypto-server/crypto-helper > data/helper.out 2>&1 & pids+=($!)
     wait_for "crypto-helper (:8090)" http://127.0.0.1:8090/health data/helper.out; fi

export BLIND_RAG_CRYPTO=real
export BLIND_RAG_ANSWER="${BLIND_RAG_ANSWER:-real}"
if [ "$BLIND_RAG_ANSWER" = real ] && ! up http://127.0.0.1:11434/api/tags; then
  echo "WARNING: Ollama is not answering on :11434. Run: brew services start ollama"
fi
# PLAIN=1 also starts B's plaintext "normal RAG server" for the side-by-side log contrast.
if [ "${PLAIN:-0}" = 1 ]; then
  if up http://127.0.0.1:8001/health; then echo "  plaintext demo server already running, reusing it"
  else "$PY" -m baseline.server > data/plain.out 2>&1 & pids+=($!)
       wait_for "plaintext demo server (:8001, warming the model)" http://127.0.0.1:8001/health data/plain.out; fi
fi
echo "Starting the UI..."
"$PY" -m streamlit run ui/app.py "$@"
