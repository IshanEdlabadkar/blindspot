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

.PHONY: measure
measure:       ## with server + helper running: latency, bytes, CPU, log check -> data/measurements.md
	python3 scripts/measure.py

integration:   ## after merging A + C: real crypto vs mock, same top-k (~1 min)
	python3 scripts/integration_check.py

demo:          ## everything in one terminal: server + helper + UI with real crypto (Ctrl+C stops all)
	./scripts/start_demo.sh

demo-compare:  ## make demo plus B's plaintext server (:8001), for the side-by-side log contrast
	PLAIN=1 ./scripts/start_demo.sh

stop:          ## stop any server, helper or plaintext server left running (do this after git pull)
	-@pkill -f "[c]rypto-server/crypto-server"; pkill -f "[c]rypto-server/crypto-helper"; pkill -f "[g]o run . -data"; pkill -f "[g]o run ./cmd/crypto-helper"; pkill -f "[b]aseline.server"; echo "stopped"

preflight:     ## with make demo running: the 8-step smoke test before presenting (real crypto + real model)
	./scripts/start_demo.sh --preflight
