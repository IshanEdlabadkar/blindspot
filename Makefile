# Run from the repo root. Crypto targets need Go + SEAL (see SETUP.md).
# DATA: folder with manifest.json, score_table.bin, fetch_store.bin (B writes artifacts/).
DATA ?= artifacts
.PHONY: seal test server helper integration demo demo-streamlit demo-compare stop preflight corpus-expanded
.DEFAULT_GOAL := demo

seal:          ## one-time: build and install Microsoft SEAL 4.1.1
	./scripts/install_seal.sh

test:          ## crypto unit + HTTP tests (~30 s)
	cd crypto-server && go test ./... 2>&1 | grep -v "Total packed"

server:        ## document server on $(DATA)/ at http://127.0.0.1:8080 (log: data/server.log, where C's UI reads it)
	mkdir -p data && cd crypto-server && go run . -data ../$(DATA) -log ../data/server.log

helper:        ## asker-side key holder at http://127.0.0.1:8090 (needed for BLIND_RAG_CRYPTO=real)
	cd crypto-server && go run ./cmd/crypto-helper

.PHONY: bench bench-quick check-servers
check-servers: ## every hosted server (servers.remote.json): reachable, right corpus, matches repo backup, log has only 4 fields
	python3 scripts/check_servers.py $(ARGS)

bench:         ## with make demo running (the key helper is started if needed): accuracy + speed + per-question trace for every eval question -> eval/results/bench/<run>/report.html
	@curl -fsS -o /dev/null --max-time 2 http://127.0.0.1:8090/health 2>/dev/null || { echo "starting the key helper (:8090, log data/helper.out)"; mkdir -p data; (cd crypto-server && go build -o crypto-helper ./cmd/crypto-helper) && (nohup ./crypto-server/crypto-helper > data/helper.out 2>&1 &) ; sleep 2; }
	python3 -m eval.bench $(ARGS)

bench-quick:   ## same, retrieval only (no rerank/model): crypto speed + right page in top-k, ~1 s per question
	@curl -fsS -o /dev/null --max-time 2 http://127.0.0.1:8090/health 2>/dev/null || { echo "starting the key helper (:8090, log data/helper.out)"; mkdir -p data; (cd crypto-server && go build -o crypto-helper ./cmd/crypto-helper) && (nohup ./crypto-server/crypto-helper > data/helper.out 2>&1 &) ; sleep 2; }
	python3 -m eval.bench --answer none $(ARGS)

.PHONY: measure
measure:       ## with server + helper running: latency, bytes, CPU, log check -> data/measurements.md
	python3 scripts/measure.py

integration:   ## after merging A + C: real crypto vs mock, same top-k (~1 min)
	python3 scripts/integration_check.py

demo:          ## DEFAULT: the Vault web UI (React) on :8600, opened in your browser, with everything behind it (Ctrl+C stops all; LOCAL=1 offline)
	./web/demo.sh

demo-streamlit: ## the older Streamlit-only stack on :8501 (honours DATA=..., PLAIN=0)
	./scripts/start_demo.sh

demo-compare:  ## Streamlit stack with B's plaintext server on :8001 (same as demo-streamlit)
	PLAIN=1 ./scripts/start_demo.sh

stop:          ## stop the server, helper, plaintext server and UI left running (do this after git pull)
	-@for port in 8080 8081 8082 8083 8090 8001 8501 8600 9001 9080 9081 9082 9083; do pids=$$(lsof -ti tcp:$$port -sTCP:LISTEN 2>/dev/null); [ -n "$$pids" ] && kill $$pids 2>/dev/null; done; \
	  pkill -f "[g]o run . -data"; pkill -f "[g]o run ./cmd/crypto-helper"; pkill -f "[s]treamlit run ui/app.py"; pkill -f "[w]iretap.proxy"; pkill -f "[u]vicorn api.app"; \
	  echo "stopped"

preflight:     ## with make demo running: every document server checked, then the 8-step smoke test (real crypto + real model)
	python3 scripts/check_servers.py
	./scripts/start_demo.sh --preflight

corpus-expanded: ## alternative, not the demo setup: ONE combined corpus (MedlinePlus + Genetics + MyHealthfinder) for a single server
	$$(./scripts/find_python.sh sentence_transformers) -m ingest.build_multi --out artifacts-expanded
	@echo "Serve it with:  make stop && make demo-streamlit DATA=artifacts-expanded"
