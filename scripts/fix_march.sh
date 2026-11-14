#!/usr/bin/env bash
# Run only if the Go build fails with an error mentioning -march=native
# (some Apple Silicon compilers). Removes the flag from the two vendored libraries.
set -euo pipefail
cd "$(dirname "$0")/.."
sed -i.bak 's/ -march=native//' third_party/underhood/rlwe/rlwe.go third_party/simplepir/matrix/matrix.go
rm -f third_party/underhood/rlwe/rlwe.go.bak third_party/simplepir/matrix/matrix.go.bak
echo "Removed -march=native. Rebuild with: make test"
