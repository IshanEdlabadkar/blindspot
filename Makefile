# Crypto targets (need Go + SEAL; see SETUP.md). Run from the repo root.
.PHONY: seal test server

seal:            ## one-time: build and install Microsoft SEAL 4.1.1
	./scripts/install_seal.sh

test:            ## crypto unit + HTTP integration tests (~30 s)
	cd crypto-server && go test ./... -v 2>&1 | grep -v "Total packed"

server:          ## run the document server on data/ at http://127.0.0.1:8080
	cd crypto-server && go run . -data ../data
