#!/usr/bin/env bash
# Builds Microsoft SEAL 4.1.1 the way underhood needs it (~5 min).
# macOS: brew install cmake first. Linux: apt install cmake g++.
set -euo pipefail
tmp=$(mktemp -d)
git clone --depth 1 --branch v4.1.1 https://github.com/microsoft/SEAL.git "$tmp/SEAL"
cmake -S "$tmp/SEAL" -B "$tmp/SEAL/build" \
  -DSEAL_THROW_ON_TRANSPARENT_CIPHERTEXT=OFF \
  -DSEAL_USE_MSGSL=OFF -DSEAL_USE_ZLIB=OFF -DSEAL_USE_ZSTD=OFF \
  -DSEAL_BUILD_DEPS=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build "$tmp/SEAL/build" -j
sudo cmake --install "$tmp/SEAL/build"
echo "SEAL installed to /usr/local"
