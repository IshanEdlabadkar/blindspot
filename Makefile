# Run from the repo root. Crypto targets need Go + SEAL (see SETUP.md).
# DATA: folder with manifest.json, score_table.bin, fetch_store.bin (B writes artifacts/).
DATA ?= artifacts
.PHONY: seal test server helper integration demo demo-compare stop preflight

seal:          ## one-time: build and install Microsoft SEAL 4.1.1
	./scripts/install_seal.sh

test:          ## crypto unit + HTTP tests (~30 s)
	cd crypto-server && go test ./... 2>&1 | grep -v "Total packed"

server:        ## document server on $(DATA)/ at http://127.0.0.1:8080 (log: data/server.log, where C's UI reads it)
	mkdir -p data && cd crypto-server && go run . -data ../$(DATA) -log ../data/server.log

helper:        ## asker-side key holder at http://127.0.0.1:8090 (needed for BLIND_RAG_CRYPTO=real)
	cd crypto-server && go run ./cmd/crypto-helper

.PHONY: bench bench-quick
bench:         ## with make demo running: accuracy + speed + per-question trace for every eval question -> eval/results/bench/<run>/report.html
	python3 -m eval.bench $(ARGS)

bench-quick:   ## same, retrieval only (no rerank/model): crypto speed + right page in top-k, ~1 s per question
	python3 -m eval.bench --answer none $(ARGS)

.PHONY: measure
measure:       ## with server + helper running: latency, bytes, CPU, log check -> data/measurements.md
	python3 scripts/measure.py

integration:   ## after merging A + C: real crypto vs mock, same top-k (~1 min)
	python3 scripts/integration_check.py

demo:          ## everything in one terminal: server + helper + plaintext demo server + UI (Ctrl+C stops all; PLAIN=0 skips the plaintext server)
	./scripts/start_demo.sh

demo-compare:  ## same as make demo (which now always starts B's plaintext server on :8001)
	PLAIN=1 ./scripts/start_demo.sh

stop:          ## stop any server, helper or plaintext server left running (do this after git pull)
	-@pkill -f "[c]rypto-server/crypto-server"; pkill -f "[c]rypto-server/crypto-helper"; pkill -f "[g]o run . -data"; pkill -f "[g]o run ./cmd/crypto-helper"; pkill -f "[b]aseline.server"; echo "stopped"

preflight:     ## with make demo running: the 8-step smoke test before presenting (real crypto + real model)
	./scripts/start_demo.sh --preflight
