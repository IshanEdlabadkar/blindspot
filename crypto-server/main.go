// Blind RAG document server. Computes only on encrypted data; holds no keys.
//
//	go run . -data ../data -addr :8080
//
// Endpoints:
//
//	GET  /v1/manifest     manifest.json plus the public scoring seed
//	POST /v1/score        encrypted query in, encrypted scores out (see blindcrypto/wire.go)
//	GET  /v1/fetch_store  the whole fetch store (trivial PIR: the client reads chunks locally)
//
// Logs one JSON line per request: ts, endpoint, status, response_bytes, latency_ms.
// Request bodies are never logged or stored.
package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/IshanEdlabadkar/blindspot/crypto-server/blindcrypto"
)

const maxScoreBody = 64 << 20 // token is ~33 MB

type server struct {
	version  string
	manifest []byte
	store    []byte
	score    *blindcrypto.ScoreServer
	mu       sync.Mutex // underhood's thread safety is undocumented; serialize
	logOut   *json.Encoder
	logMu    sync.Mutex
}

func main() {
	dataDir := flag.String("data", "../data", "directory with manifest.json, score_table.bin, fetch_store.bin")
	addr := flag.String("addr", "127.0.0.1:8080", "listen address")
	flag.Parse()

	s, err := load(*dataDir)
	if err != nil {
		log.Fatal(err)
	}
	defer s.score.Free()

	mux := http.NewServeMux()
	mux.HandleFunc("GET /v1/manifest", s.logged("/v1/manifest", s.handleManifest))
	mux.HandleFunc("POST /v1/score", s.logged("/v1/score", s.handleScore))
	mux.HandleFunc("GET /v1/fetch_store", s.logged("/v1/fetch_store", s.handleFetchStore))
	log.Printf("serving corpus %s on http://%s", s.version, *addr)
	log.Fatal(http.ListenAndServe(*addr, mux))
}

func load(dir string) (*server, error) {
	raw, err := os.ReadFile(filepath.Join(dir, "manifest.json"))
	if err != nil {
		return nil, err
	}
	var m map[string]any
	if err := json.Unmarshal(raw, &m); err != nil {
		return nil, fmt.Errorf("manifest.json: %w", err)
	}
	version, _ := m["corpus_version"].(string)
	nf, _ := m["num_chunks"].(float64)
	emb, _ := m["embedding"].(map[string]any)
	df, _ := emb["dim"].(float64)
	pirM, _ := m["pir"].(map[string]any)
	lf, _ := pirM["record_bytes"].(float64)
	n, d, recLen := uint64(nf), uint64(df), uint64(lf)
	if version == "" || n == 0 || d == 0 || recLen == 0 {
		return nil, fmt.Errorf("manifest needs corpus_version, num_chunks, embedding.dim, pir.record_bytes")
	}

	tableBytes, err := os.ReadFile(filepath.Join(dir, "score_table.bin"))
	if err != nil {
		return nil, err
	}
	if uint64(len(tableBytes)) != n*d {
		return nil, fmt.Errorf("score_table.bin is %d bytes, want N*d = %d", len(tableBytes), n*d)
	}
	store, err := os.ReadFile(filepath.Join(dir, "fetch_store.bin"))
	if err != nil {
		return nil, err
	}
	if uint64(len(store)) != n*recLen {
		return nil, fmt.Errorf("fetch_store.bin is %d bytes, want N*L = %d", len(store), n*recLen)
	}

	table := make([]int8, len(tableBytes))
	for i, b := range tableBytes {
		table[i] = int8(b)
	}
	db, err := blindcrypto.NewScoreDB(table, n, d)
	if err != nil {
		return nil, err
	}
	hash := sha256.Sum256(tableBytes)
	seed := blindcrypto.SeedFromTable(hash)
	start := time.Now()
	ss := blindcrypto.NewScoreServer(db, seed)
	log.Printf("precomputed score table (%d x %d) in %v", n, d, time.Since(start))

	// Publish what the client needs: the public seed and the fetch mode.
	scoring, _ := m["scoring"].(map[string]any)
	if scoring == nil {
		scoring = map[string]any{}
	}
	scoring["seed"] = hex.EncodeToString(seed[:])
	scoring["modulus"] = blindcrypto.P
	m["scoring"] = scoring
	pirM["mode"] = "trivial"
	out, _ := json.MarshalIndent(m, "", "  ")

	return &server{
		version: version, manifest: out, store: store, score: ss,
		logOut: json.NewEncoder(os.Stdout),
	}, nil
}

func (s *server) handleManifest(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Write(s.manifest)
}

func (s *server) handleFetchStore(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/octet-stream")
	w.Header().Set("X-Corpus-Version", s.version)
	w.Write(s.store)
}

func (s *server) handleScore(w http.ResponseWriter, r *http.Request) {
	req, err := blindcrypto.UnmarshalScoreRequest(http.MaxBytesReader(w, r.Body, maxScoreBody))
	if err != nil {
		http.Error(w, "bad request", http.StatusBadRequest)
		return
	}
	if req.CorpusVersion != s.version {
		http.Error(w, "stale corpus_version", http.StatusConflict)
		return
	}
	if req.Query.Query.Rows() < s.score.DB.Info.M {
		http.Error(w, "bad query size", http.StatusBadRequest)
		return
	}
	resp := s.compute(req)
	w.Header().Set("Content-Type", "application/octet-stream")
	w.Write(resp.MarshalBinary())
}

func (s *server) compute(req *blindcrypto.ScoreRequest) *blindcrypto.ScoreResponse {
	s.mu.Lock()
	defer s.mu.Unlock()
	return &blindcrypto.ScoreResponse{
		TokenAnswer: s.score.HintAnswer(&req.Token),
		Scores:      s.score.Answer(req.Query),
	}
}

// countingWriter records status and response size for the log line.
type countingWriter struct {
	http.ResponseWriter
	status int
	n      int
}

func (c *countingWriter) WriteHeader(code int) { c.status = code; c.ResponseWriter.WriteHeader(code) }
func (c *countingWriter) Write(b []byte) (int, error) {
	n, err := c.ResponseWriter.Write(b)
	c.n += n
	return n, err
}

func (s *server) logged(endpoint string, h http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		cw := &countingWriter{ResponseWriter: w, status: 200}
		// Recover from library panics on malformed ciphertext instead of crashing.
		defer func() {
			if rec := recover(); rec != nil {
				http.Error(cw, "bad request", http.StatusBadRequest)
			}
			s.logMu.Lock()
			s.logOut.Encode(map[string]any{
				"ts":             start.UTC().Format(time.RFC3339Nano),
				"endpoint":       endpoint,
				"status":         cw.status,
				"response_bytes": cw.n,
				"latency_ms":     float64(time.Since(start).Microseconds()) / 1000,
			})
			s.logMu.Unlock()
		}()
		h(cw, r)
	}
}
