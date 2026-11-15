# Blind RAG document server, with B's tables (artifacts/) baked in.
# Build from the repo root on a branch that has artifacts/ (e.g. main):
#   docker build -t blind-rag-server .
#   docker run -p 8080:8080 blind-rag-server
# Render builds this automatically from render.yaml. See DEPLOY.md.

FROM golang:1.24-bookworm AS build
RUN apt-get update && apt-get install -y --no-install-recommends cmake g++ git && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch v4.1.1 https://github.com/microsoft/SEAL.git /seal \
 && cmake -S /seal -B /seal/build -DSEAL_THROW_ON_TRANSPARENT_CIPHERTEXT=OFF \
      -DSEAL_USE_MSGSL=OFF -DSEAL_USE_ZLIB=OFF -DSEAL_USE_ZSTD=OFF -DSEAL_BUILD_DEPS=OFF \
      -DCMAKE_BUILD_TYPE=Release \
 && cmake --build /seal/build -j"$(nproc)" && cmake --install /seal/build && rm -rf /seal
WORKDIR /src
COPY third_party third_party
COPY crypto-server crypto-server
# Portable binary: the image may run on a different CPU than the one that built it.
RUN sed -i 's/ -march=native//' third_party/underhood/rlwe/rlwe.go third_party/simplepir/matrix/matrix.go
RUN cd crypto-server && GOFLAGS=-mod=mod GOPROXY=off go build -o /out/crypto-server .

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl libstdc++6 && rm -rf /var/lib/apt/lists/* \
 && useradd -r -u 10001 blindrag && mkdir -p /data /logs && chown blindrag /logs
COPY --from=build /out/crypto-server /usr/local/bin/crypto-server
COPY artifacts/manifest.json artifacts/score_table.bin artifacts/fetch_store.bin /data/
USER blindrag
# The server binds 0.0.0.0:$PORT. Render sets PORT (default 10000).
# Hint-mode scoring + real PIR fetch (~210 MB RAM). BLIND_RAG_TOKEN_MODE=1 adds the 33 MB-per-question
# fallback (~650 MB more); BLIND_RAG_PIR=0 turns off real PIR fetch.
ENV PORT=8080 BLIND_RAG_TOKEN_MODE=0 BLIND_RAG_PUBLIC_LOG=1
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=30s CMD curl -fsS "http://127.0.0.1:${PORT}/v1/manifest" >/dev/null || exit 1
ENTRYPOINT ["crypto-server", "-data", "/data", "-log", "/logs/server.log"]
