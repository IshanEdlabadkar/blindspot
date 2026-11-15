#!/usr/bin/env bash
# The demo with the wiretap: every byte the app sends to a server goes through a recorder on this
# laptop, so the UI can search that traffic for the asker's words ("🔍 Search the traffic for your words",
# shown when "Show what the server saw" is on).
#
#   ./wiretap/demo.sh            every document server in servers.remote.json (hosted, corpora on Databricks);
#                                one that doesn't answer falls back to a local server on its backup in artifacts/<id>/
#   LOCAL=1 ./wiretap/demo.sh    every server in servers.json, all local (offline)
#
# Relays: :9080, :9081, ... -> the document servers in list order (MedlinePlus, FMLA, Genetics, MyHealthfinder),
# :9001 -> the plaintext "normal RAG" server. Recording: data/wire/wire.jsonl (emptied at every start).
# Ctrl+C stops everything this script started. (./web/demo.sh does the same for the Vault web UI.)
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data
PY=$(./scripts/find_python.sh) || exit 1
export PYTHON="$PY"
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

# Wake every hosted server at once (a sleeping free Render service takes up to ~1 min).
for e in "${ENTRIES[@]}"; do
  url=${e#* }
  [[ $url == http://127.0.0.1:* || $url == http://localhost:* ]] || { curl -s -o /dev/null --max-time 90 "$url/v1/manifest" & }
done
wait

routes=(--route "plain:9001=${PLAIN_URL:-http://127.0.0.1:8001}")
relays=()
i=0
for e in "${ENTRIES[@]}"; do
  id=${e%% *}; url=${e#* }
  if [[ $url == http://127.0.0.1:* || $url == http://localhost:* ]]; then
    up "$url/v1/manifest" || local_server "$id" "${url##*:}"
    echo "  $id: local $url"
  elif up "$url/v1/manifest" 15; then
    echo "  $id: hosted $url"
  else
    url="http://127.0.0.1:$((8080 + i))"; echo "  $id: hosted server did not answer, using the local backup on $url"
    up "$url/v1/manifest" || local_server "$id" "${url##*:}"
  fi
  routes+=(--route "$id:$((9080 + i))=$url"); relays+=("http://127.0.0.1:$((9080 + i))")
  i=$((i + 1))
done
servers=$(IFS=,; echo "${relays[*]}")

"$PY" -m wiretap.proxy --fresh "${routes[@]}" > data/wiretap.out 2>&1 & pids+=($!)
wait_up "http://127.0.0.1:9080/v1/manifest" "recording relay" 40
cat data/wiretap.out

# start_demo.sh starts the key helper, the plaintext server and the UI; with WIRETAP_SERVERS set it starts
# no document servers of its own, and the UI talks to the servers above only through the relays.
export BLIND_RAG_SERVERS="$servers" WIRETAP_SERVERS="$servers" BLIND_RAG_PLAIN_SERVER=http://127.0.0.1:9001
./scripts/start_demo.sh
