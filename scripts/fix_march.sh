#!/usr/bin/env bash
# Run only if the Go build fails with an error mentioning -march=native
# (some Apple Silicon compilers). Removes the flag from the two vendored libraries.
set -euo pipefail
cd "$(dirname "$0")/.."
for f in $(grep -rl --include='*.go' -- '-march=native' third_party); do
  sed -i.bak 's/ -march=native//g' "$f" && rm -f "$f.bak"
done
echo "Removed -march=native. Rebuild with: make test"
