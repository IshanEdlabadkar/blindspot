#!/usr/bin/env bash
# The demo with the wiretap: every byte the app sends to a server goes through a recorder on this
# laptop, so the UI can search that traffic for the asker's words ("🔍 Search the traffic for your words",
# shown when "Show what the server saw" is on).
#
#   ./wiretap/demo.sh                      # local MedlinePlus (:8080) + local FMLA (:8081) + plain (:8001)
#   MEDLINEPLUS_URL=https://a.onrender.com FMLA_URL=https://b.onrender.com ./wiretap/demo.sh   # remote servers
#   FMLA=0 ./wiretap/demo.sh               # MedlinePlus only
#
# Relays: :9080 -> MedlinePlus, :9081 -> FMLA, :9001 -> the plaintext "normal RAG" server.
# Recording: data/wire/wire.jsonl (emptied at every start). Ctrl+C stops everything this script started.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data
PY=$(./scripts/find_python.sh) || exit 1
export PYTHON="$PY"
pids=()
cleanup() { for p in ${pids[@]+"${pids[@]}"}; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT
up() { curl -fsS -o /dev/null --max-time 2 "$1" 2>/dev/null; }

MEDLINEPLUS_URL="${MEDLINEPLUS_URL:-http://127.0.0.1:8080}"
routes=(--route "medlineplus:9080=$MEDLINEPLUS_URL" --route "plain:9001=${PLAIN_URL:-http://127.0.0.1:8001}")
servers="http://127.0.0.1:9080"

if [ "${FMLA:-1}" != 0 ]; then
  if [ -z "${FMLA_URL:-}" ]; then
    FMLA_URL=http://127.0.0.1:8081
    if ! up "$FMLA_URL/v1/manifest"; then
      [ -f artifacts/fmla/manifest.json ] || { echo "ERROR: artifacts/fmla/ missing: uv run python -m ingest.build --source fmla"; exit 1; }
      (cd crypto-server && go build -o crypto-server .)
      ./crypto-server/crypto-server -data artifacts/fmla -addr 127.0.0.1:8081 -log data/server-fmla.log \
        > data/server-fmla.out 2>&1 & pids+=($!)
      for _ in $(seq 1 60); do up "$FMLA_URL/v1/manifest" && break; sleep 0.5; done
      up "$FMLA_URL/v1/manifest" || { echo "ERROR: FMLA server did not start; see data/server-fmla.out"; exit 1; }
      echo "  FMLA document server (:8081) ready"
    fi
  fi
  routes+=(--route "fmla:9081=$FMLA_URL")
  servers="$servers,http://127.0.0.1:9081"
fi

"$PY" -m wiretap.proxy --fresh "${routes[@]}" > data/wiretap.out 2>&1 & pids+=($!)
for _ in $(seq 1 20); do grep -q "recording to" data/wiretap.out 2>/dev/null && break; sleep 0.25; done
cat data/wiretap.out

# make demo starts the local MedlinePlus server, the key helper, the plaintext server and the UI;
# the UI talks to the servers only through the relays.
case "$MEDLINEPLUS_URL" in http://127.0.0.1:8080*) ;; *) export BLIND_RAG_SERVER="$MEDLINEPLUS_URL" ;; esac
export BLIND_RAG_SERVERS="$servers" BLIND_RAG_PLAIN_SERVER=http://127.0.0.1:9001
make demo
