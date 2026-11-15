# Run from the repo root. Crypto targets need Go + SEAL (see SETUP.md).
# DATA: folder with manifest.json, score_table.bin, fetch_store.bin (B writes artifacts/).
DATA ?= artifacts
.PHONY: seal test server helper integration demo demo-compare stop preflight corpus-expanded

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

demo:          ## everything in one terminal: server + helper + plaintext demo server + UI (Ctrl+C stops all; PLAIN=0 skips the plaintext server)
	./scripts/start_demo.sh

demo-compare:  ## same as make demo (which now always starts B's plaintext server on :8001)
	PLAIN=1 ./scripts/start_demo.sh

stop:          ## stop the server, helper, plaintext server and UI left running (do this after git pull)
	-@for port in 8080 8090 8001; do pids=$$(lsof -ti tcp:$$port -sTCP:LISTEN 2>/dev/null); [ -n "$$pids" ] && kill $$pids 2>/dev/null; done; \
	  pkill -f "[g]o run . -data"; pkill -f "[g]o run ./cmd/crypto-helper"; pkill -f "[s]treamlit run ui/app.py"; \
	  echo "stopped"

preflight:     ## with make demo running: the 8-step smoke test before presenting (real crypto + real model)
	./scripts/start_demo.sh --preflight

corpus-expanded: ## build artifacts-expanded/: MedlinePlus + MedlinePlus Genetics + MyHealthfinder (needs internet, ~5 min)
	$$(./scripts/find_python.sh sentence_transformers) -m ingest.build_multi --out artifacts-expanded
	@echo "Serve it with:  make stop && make demo DATA=artifacts-expanded"
