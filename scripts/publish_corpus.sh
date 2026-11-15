#!/usr/bin/env bash
# Publish the provider's corpus (B's ingestion output) to a Databricks Unity
# Catalog volume, where the document server reads it.
#
#   export DATABRICKS_HOST=https://<workspace>.cloud.databricks.com
#   export DATABRICKS_TOKEN=<personal access token>
#   export BLIND_RAG_VOLUME=/Volumes/<catalog>/<schema>/<volume>/blindrag
#   ./scripts/publish_corpus.sh [artifacts]
#
# Data files go up first and manifest.json last, so the server never sees a new
# corpus_version before its files are complete. (It also checks every file's
# hash and keeps serving the old version if anything does not match.)
set -euo pipefail
DIR="${1:-artifacts}"
: "${DATABRICKS_HOST:?set DATABRICKS_HOST, e.g. https://<workspace>.cloud.databricks.com}"
: "${DATABRICKS_TOKEN:?set DATABRICKS_TOKEN (a personal access token)}"
: "${BLIND_RAG_VOLUME:?set BLIND_RAG_VOLUME, e.g. /Volumes/workspace/default/blindrag/corpus}"
HOST="${DATABRICKS_HOST%/}"
VOL="${BLIND_RAG_VOLUME%/}"

# 1. Check the files match their manifest before uploading anything.
python3 - "$DIR" <<'PY'
import hashlib, json, pathlib, sys
d = pathlib.Path(sys.argv[1]); m = json.loads((d / "manifest.json").read_text())
for key, name in (("score_table", "score_table.bin"), ("fetch_store", "fetch_store.bin")):
    got = "sha256:" + hashlib.sha256((d / name).read_bytes()).hexdigest()
    if got != m["hashes"][key]:
        sys.exit(f"{name} does not match manifest hashes.{key}; rebuild the artifacts")
q = m["quantization"]["scale"]
if q != 127:
    sys.exit(f"quantization.scale is {q}, must be 127 (the server refuses other scales)")
print(f"corpus {m['corpus_version']}: {m['num_chunks']} chunks, hashes OK")
PY

api() { curl -fsS --retry 3 -H "Authorization: Bearer ${DATABRICKS_TOKEN}" "$@"; }

# 2. Make sure the folder exists, then upload data files, then the manifest.
api -X PUT "${HOST}/api/2.0/fs/directories${VOL}/" >/dev/null
for f in score_table.bin fetch_store.bin manifest.json; do
  echo "uploading $f"
  api -X PUT --data-binary "@${DIR}/${f}" -H "Content-Type: application/octet-stream" \
      "${HOST}/api/2.0/fs/files${VOL}/${f}?overwrite=true" >/dev/null
done

echo
echo "Published. Set these on the document server (Render dashboard > Environment):"
echo "  BLIND_RAG_DATA_URL=${HOST}/api/2.0/fs/files${VOL}/"
echo "  BLIND_RAG_DATA_AUTH=Bearer <a token that can read this volume>"
echo "A running server picks up the new corpus_version within a minute."
