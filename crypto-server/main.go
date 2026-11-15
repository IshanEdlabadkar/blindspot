// Blind RAG document server. Computes only on encrypted data; holds no keys.
//
//	go run . -data ../data -addr :8080
//
// Endpoints:
//
//	GET  /v1/manifest     manifest.json plus public scoring parameters (seed, mode, hint URL)
//	GET  /v1/score_hint   public scoring hint, downloaded once per corpus version (hint mode)
//	POST /v1/score        encrypted query in, encrypted scores out (see blindcrypto/wire.go).
//	                      A request with no token is hint mode; with a token, token mode.
//	GET  /v1/fetch_store  the whole fetch store (trivial PIR: the client reads chunks locally)
//
// Logs one JSON line per request to -log (default <data>/server.log), the
// fields fixed in contracts.py: ts, endpoint, response_bytes, latency_ms.
// Request bodies are never logged or stored.
package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"math"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"sync"
	"time"

	"github.com/IshanEdlabadkar/blindspot/crypto-server/blindcrypto"
	"github.com/ahenzinger/underhood/underhood"
)

const maxScoreBody = 64 << 20 // token is ~33 MB

type server struct {
	version  string
	manifest map[string]any
	hint     []byte
	store    []byte
	score    *blindcrypto.ScoreServer
	mu       sync.Mutex // underhood's thread safety is undocumented; serialize
	logOut   *json.Encoder
	logMu    sync.Mutex
	recent   [][]byte // last log lines, for GET /v1/server_log
}

const recentMax = 200

func envBool(name string, def bool) bool {
	switch os.Getenv(name) {
	case "1", "true", "yes":
		return true
	case "0", "false", "no":
		return false
	}
	return def
}

func main() {
	dataDir := flag.String("data", "../data", "directory with manifest.json, score_table.bin, fetch_store.bin")
	defAddr := "127.0.0.1:8080"
	if port := os.Getenv("PORT"); port != "" { // set by Docker and Render
		defAddr = "0.0.0.0:" + port
	}
	addr := flag.String("addr", defAddr, "listen address (use 0.0.0.0:8080 to serve other machines; $PORT sets 0.0.0.0:$PORT)")
	tokenMode := flag.Bool("token-mode", envBool("BLIND_RAG_TOKEN_MODE", true), "also serve token mode (~650 MB RAM at 2,101 chunks; hint mode alone ~100 MB)")
	publicLog := flag.Bool("public-log", envBool("BLIND_RAG_PUBLIC_LOG", false), "serve recent log lines at GET /v1/server_log (for the UI's server panel when the server is remote)")
	logPath := flag.String("log", "", "request log file (default <data>/server.log)")
	allowWrap := flag.Bool("allow-wrap", false, "start even if scores can exceed the modulus (random dummy tables only)")
	flag.Parse()

	s, err := load(*dataDir, *allowWrap, *tokenMode)
	if err != nil {
		log.Fatal(err)
	}
	if *logPath == "" {
		*logPath = filepath.Join(*dataDir, "server.log")
	}
	lf, err := os.OpenFile(*logPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		log.Fatal(err)
	}
	defer lf.Close()
	s.logOut = json.NewEncoder(lf)
	log.Printf("request log: %s", *logPath)
	defer s.score.Free()

	mux := http.NewServeMux()
	mux.HandleFunc("GET /v1/manifest", s.logged("/v1/manifest", s.handleManifest))
	mux.HandleFunc("GET /v1/score_hint", s.logged("/v1/score_hint", s.handleHint))
	mux.HandleFunc("POST /v1/score", s.logged("/v1/score", s.handleScore))
	mux.HandleFunc("GET /v1/fetch_store", s.logged("/v1/fetch_store", s.handleFetchStore))
	if *publicLog {
		// Not itself logged, so a UI polling it does not flood the log.
		mux.HandleFunc("GET /v1/server_log", s.handleServerLog)
		log.Printf("public log enabled: GET /v1/server_log")
	}
	if !*tokenMode {
		log.Printf("token mode off: hint mode only")
	}
	log.Printf("serving corpus %s on http://%s", s.version, *addr)
	log.Fatal(http.ListenAndServe(*addr, mux))
}

func load(dir string, allowWrap, tokenMode bool) (*server, error) {
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
	if err := checkScoreRange(table, n, d, allowWrap); err != nil {
		return nil, err
	}
	db, err := blindcrypto.NewScoreDB(table, n, d)
	if err != nil {
		return nil, err
	}
	hash := sha256.Sum256(tableBytes)
	seed := blindcrypto.SeedFromTable(hash)
	start := time.Now()
	ss := blindcrypto.NewScoreServerHintOnly(db, seed)
	if tokenMode {
		ss = blindcrypto.NewScoreServer(db, seed)
	}
	hint := blindcrypto.EncodeHint(ss.Hint())
	log.Printf("precomputed score table (%d x %d) and %.1f MB hint in %v", n, d, float64(len(hint))/1e6, time.Since(start))

	// Publish what the client needs: the public seed and the fetch mode.
	scoring, _ := m["scoring"].(map[string]any)
	if scoring == nil {
		scoring = map[string]any{}
	}
	scoring["seed"] = hex.EncodeToString(seed[:])
	scoring["modulus"] = blindcrypto.P
	scoring["library"] = "underhood (Tiptoe) + SimplePIR LHE"
	scoring["params"] = fmt.Sprintf("logq=64 n=2048 p=2^17 d=%d", d)
	scoring["mode"] = "hint" // clients may still send a token (token mode) instead, if enabled
	scoring["token_mode"] = tokenMode
	scoring["hint_path"] = "/v1/score_hint"
	scoring["hint_bytes"] = len(hint)
	scoring["hint_sha256"] = blindcrypto.HintSHA256(hint)
	m["scoring"] = scoring
	pirM["mode"] = "trivial"
	pirM["library"] = "trivial PIR (whole store)"
	pirM["params"] = "none"

	return &server{
		version: version, manifest: m, hint: hint, store: store, score: ss,
		logOut: json.NewEncoder(io.Discard),
	}, nil
}

// checkScoreRange: scores are exact only while |score| < P/2 = 65,536.
// By Cauchy-Schwarz a query quantized like the rows scores at most about
// (max row norm)^2. Unit vectors at scale 127 give ~16,100, a 4x margin.
// Refuse to start if a close match could wrap: it would silently vanish
// from the top k.
func checkScoreRange(table []int8, n, d uint64, allowWrap bool) error {
	var worst float64
	for i := uint64(0); i < n; i++ {
		var ss float64
		for _, x := range table[i*d : (i+1)*d] {
			ss += float64(x) * float64(x)
		}
		worst = math.Max(worst, math.Sqrt(ss))
	}
	bound := worst * worst
	if bound < float64(blindcrypto.P/2) {
		log.Printf("score range OK: max row norm %.0f, worst-case score ~%.0f < %d", worst, bound, blindcrypto.P/2)
		return nil
	}
	msg := fmt.Sprintf("score_table can overflow: max row norm %.0f, so a close match scores ~%.0f, above the limit %d. "+
		"Rebuild with L2-normalized rows and quantization scale 127 (manifest quantization.scale = 127).", worst, bound, blindcrypto.P/2)
	if allowWrap {
		log.Printf("WARNING: %s Continuing because -allow-wrap is set.", msg)
		return nil
	}
	return fmt.Errorf("%s Use -allow-wrap only for random dummy tables", msg)
}

func (s *server) handleManifest(w http.ResponseWriter, r *http.Request) {
	// hint_url is absolute, built from the address the client used, so the
	// client needs no extra configuration to find it.
	scheme := "http"
	if r.TLS != nil || r.Header.Get("X-Forwarded-Proto") == "https" {
		scheme = "https"
	}
	m := make(map[string]any, len(s.manifest))
	for k, v := range s.manifest {
		m[k] = v
	}
	sc := make(map[string]any)
	for k, v := range s.manifest["scoring"].(map[string]any) {
		sc[k] = v
	}
	sc["hint_url"] = scheme + "://" + r.Host + "/v1/score_hint"
	m["scoring"] = sc
	out, _ := json.MarshalIndent(m, "", "  ")
	w.Header().Set("Content-Type", "application/json")
	w.Write(out)
}

// handleServerLog returns the last ?n= log lines (default 50) as JSON lines:
// the same records as the log file, which hold only what any network observer
// could see anyway (time, endpoint, response size, latency).
func (s *server) handleServerLog(w http.ResponseWriter, r *http.Request) {
	n := 50
	if v, err := strconv.Atoi(r.URL.Query().Get("n")); err == nil && v > 0 && v <= recentMax {
		n = v
	}
	s.logMu.Lock()
	lines := s.recent
	if len(lines) > n {
		lines = lines[len(lines)-n:]
	}
	var b bytes.Buffer
	for _, ln := range lines {
		b.Write(ln)
		b.WriteByte('\n')
	}
	s.logMu.Unlock()
	w.Header().Set("Content-Type", "application/x-ndjson")
	w.Header().Set("Cache-Control", "no-store")
	w.Write(b.Bytes())
}

func (s *server) handleHint(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/octet-stream")
	w.Header().Set("X-Corpus-Version", s.version)
	w.Write(s.hint)
}

func (s *server) handleFetchStore(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/octet-stream")
	w.Header().Set("X-Corpus-Version", s.version)
	w.Write(s.store)
}

func (s *server) handleScore(w http.ResponseWriter, r *http.Request) {
	if r.Header.Get("X-Corpus-Version") != s.version {
		http.Error(w, "stale corpus_version", http.StatusConflict)
		return
	}
	req, err := blindcrypto.UnmarshalScoreRequest(http.MaxBytesReader(w, r.Body, maxScoreBody))
	if err != nil {
		http.Error(w, "bad request", http.StatusBadRequest)
		return
	}
	if len(req.Token) > 0 && !s.score.TokenMode() {
		http.Error(w, "token mode is off on this server; use hint mode", http.StatusBadRequest)
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
	ta := &underhood.HintAnswer{} // hint mode: the client already has the hint
	if len(req.Token) > 0 && s.score.TokenMode() {
		ta = s.score.HintAnswer(&req.Token) // token mode
	}
	return &blindcrypto.ScoreResponse{TokenAnswer: ta, Scores: s.score.Answer(req.Query)}
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
			line, _ := json.Marshal(map[string]any{
				"ts":             start.UTC().Format("2006-01-02T15:04:05.000Z"),
				"endpoint":       endpoint,
				"response_bytes": cw.n,
				"latency_ms":     math.Round(float64(time.Since(start).Microseconds())/10) / 100,
			})
			s.logMu.Lock()
			s.logOut.Encode(json.RawMessage(line))
			s.recent = append(s.recent, line)
			if len(s.recent) > recentMax {
				s.recent = s.recent[len(s.recent)-recentMax:]
			}
			s.logMu.Unlock()
		}()
		h(cw, r)
	}
}
