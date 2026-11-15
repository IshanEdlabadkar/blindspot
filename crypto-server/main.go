// Blind RAG document server. Computes only on encrypted data; holds no keys.
//
// The corpus (manifest.json, score_table.bin, fetch_store.bin) comes from the
// provider's own storage, never from this program or its image:
//
//	go run . -data ../artifacts                          # a folder
//	BLIND_RAG_DATA_URL=https://storage.example/blindrag/ go run .   # a URL
//
// Files are checked against the manifest's sha256 hashes. The server polls the
// source and swaps in a new corpus when corpus_version changes, without a
// restart; clients holding the old version get 409 and reload the manifest.
//
// Endpoints:
//
//	GET  /v1/manifest     manifest.json plus public scoring parameters (seed, mode, hint URL)
//	GET  /v1/score_hint   public scoring hint, downloaded once per corpus version (hint mode)
//	POST /v1/score        encrypted query in, encrypted scores out (see blindcrypto/wire.go).
//	                      A request with no token is hint mode; with a token, token mode.
//	GET  /v1/fetch_store  the whole fetch store (trivial PIR: the client reads chunks locally)
//	GET  /v1/fetch_hint   public PIR hint for the fetch store, downloaded once (real PIR)
//	POST /v1/fetch        one encrypted selector in, one encrypted column out (real PIR)
//	POST /v1/fetch_batch  up to 64 selectors in one round trip (real PIR, each its own secret)
//	GET  /v1/server_log   recent log lines (only with -public-log)
//
// Logs one JSON line per request to -log, the fields fixed in contracts.py:
// ts, endpoint, response_bytes, latency_ms. Request bodies are never logged or stored.
package main

import (
	"bytes"
	"encoding/json"
	"flag"
	"log"
	"math"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"sync"
	"sync/atomic"
	"time"

	"github.com/IshanEdlabadkar/blindspot/crypto-server/blindcrypto"
	"github.com/ahenzinger/underhood/underhood"
	"github.com/henrycg/simplepir/pir"
)

const (
	maxScoreBody = 64 << 20 // token-mode token is ~33 MB
	recentMax    = 200
	freeDelay    = 2 * time.Minute // keep a replaced corpus alive for in-flight requests
)

type server struct {
	cur    atomic.Pointer[corpus]
	src    source
	opts   corpusOpts
	logOut *json.Encoder
	logMu  sync.Mutex
	recent [][]byte // last log lines, for GET /v1/server_log
}

func envBool(name string, def bool) bool {
	switch os.Getenv(name) {
	case "1", "true", "yes":
		return true
	case "0", "false", "no":
		return false
	}
	return def
}

func envDuration(name string, def time.Duration) time.Duration {
	if d, err := time.ParseDuration(os.Getenv(name)); err == nil {
		return d
	}
	return def
}

func main() {
	dataDir := flag.String("data", envOr("BLIND_RAG_DATA_DIR", "../artifacts"), "folder with the provider's manifest.json, score_table.bin, fetch_store.bin")
	dataURL := flag.String("data-url", os.Getenv("BLIND_RAG_DATA_URL"), "base URL of the provider's corpus files (overrides -data); a query string such as a signed-URL token is kept")
	dataAuth := os.Getenv("BLIND_RAG_DATA_AUTH") // optional Authorization header for -data-url; env only, never a flag
	poll := flag.Duration("poll", envDuration("BLIND_RAG_DATA_POLL", time.Minute), "how often to check the source for a new corpus_version (0 = never)")
	defAddr := "127.0.0.1:8080"
	if port := os.Getenv("PORT"); port != "" { // set by Docker and Render
		defAddr = "0.0.0.0:" + port
	}
	addr := flag.String("addr", defAddr, "listen address (use 0.0.0.0:8080 to serve other machines; $PORT sets 0.0.0.0:$PORT)")
	tokenMode := flag.Bool("token-mode", envBool("BLIND_RAG_TOKEN_MODE", true), "also serve token mode (~650 MB RAM at 2,101 chunks; hint mode alone ~100 MB)")
	realPIR := flag.Bool("pir", envBool("BLIND_RAG_PIR", true), "also serve real PIR fetch at /v1/fetch (~50 MB RAM, ~2 s startup at 2,101 chunks)")
	publicLog := flag.Bool("public-log", envBool("BLIND_RAG_PUBLIC_LOG", false), "serve recent log lines at GET /v1/server_log (for the UI's server panel when the server is remote)")
	logPath := flag.String("log", os.Getenv("BLIND_RAG_LOG"), "request log file (default <data>/server.log, or ./server.log with -data-url)")
	allowWrap := flag.Bool("allow-wrap", false, "load even if scores can exceed the modulus (random dummy tables only)")
	flag.Parse()

	src, err := sourceFromFlags(*dataDir, *dataURL, dataAuth)
	if err != nil {
		log.Fatal(err)
	}
	s, err := newServer(src, corpusOpts{allowWrap: *allowWrap, tokenMode: *tokenMode, realPIR: *realPIR})
	if err != nil {
		log.Fatal(err)
	}
	if *logPath == "" {
		*logPath = "server.log"
		if d, ok := src.(dirSource); ok {
			*logPath = filepath.Join(d.dir, "server.log")
		}
	}
	lf, err := os.OpenFile(*logPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		log.Fatal(err)
	}
	defer lf.Close()
	s.logOut = json.NewEncoder(lf)
	log.Printf("corpus source: %s; request log: %s", src, *logPath)

	var handler http.Handler = s.routes(*publicLog)
	if rc, on := rateConfigFromEnv(); on {
		handler = newLimiter(rc).wrap(handler)
		log.Printf("rate limits per client: %.0f question requests/min (burst %.0f), %.0f downloads/min (burst %.0f); "+
			"penalty box %v after %d refusals in a minute; at most %d requests in flight",
			rc.questionPerMin, rc.questionBurst, rc.downloadPerMin, rc.downloadBurst, rc.penalty, rc.strikes, rc.maxInFlight)
	}
	if !*tokenMode {
		log.Printf("token mode off: hint mode only")
	}
	if *poll > 0 {
		go s.pollLoop(*poll)
		log.Printf("checking for a new corpus_version every %v", *poll)
	}
	log.Printf("serving corpus %s on http://%s", s.cur.Load().version, *addr)
	// Timeouts so slow or stalled clients can't hold connections open (slowloris). Writes get
	// minutes: a cold client downloads the 4 MB fetch store or the 17 MB hint over a slow link.
	srv := &http.Server{Addr: *addr, Handler: handler, ReadHeaderTimeout: 10 * time.Second,
		ReadTimeout: 60 * time.Second, WriteTimeout: 5 * time.Minute, IdleTimeout: 120 * time.Second,
		MaxHeaderBytes: 64 << 10}
	log.Fatal(srv.ListenAndServe())
}

func envOr(name, def string) string {
	if v := os.Getenv(name); v != "" {
		return v
	}
	return def
}

func newServer(src source, o corpusOpts) (*server, error) {
	c, err := loadCorpus(src, o)
	if err != nil {
		return nil, err
	}
	s := &server{src: src, opts: o, logOut: json.NewEncoder(nopWriter{})}
	s.cur.Store(c)
	return s, nil
}

type nopWriter struct{}

func (nopWriter) Write(b []byte) (int, error) { return len(b), nil }

// load is the folder-based constructor used by the tests.
func load(dir string, allowWrap, tokenMode, realPIR bool) (*server, error) {
	return newServer(dirSource{dir}, corpusOpts{allowWrap: allowWrap, tokenMode: tokenMode, realPIR: realPIR})
}

func (s *server) routes(publicLog bool) *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /v1/manifest", s.logged("/v1/manifest", s.handleManifest))
	mux.HandleFunc("GET /v1/score_hint", s.logged("/v1/score_hint", s.handleHint))
	mux.HandleFunc("POST /v1/score", s.logged("/v1/score", s.handleScore))
	mux.HandleFunc("GET /v1/fetch_store", s.logged("/v1/fetch_store", s.handleFetchStore))
	mux.HandleFunc("GET /v1/fetch_hint", s.logged("/v1/fetch_hint", s.handleFetchHint))
	mux.HandleFunc("POST /v1/fetch", s.logged("/v1/fetch", s.handleFetch))
	mux.HandleFunc("POST /v1/fetch_batch", s.logged("/v1/fetch_batch", s.handleFetchBatch))
	if publicLog {
		// Not itself logged, so a UI polling it does not flood the log.
		mux.HandleFunc("GET /v1/server_log", s.handleServerLog)
		log.Printf("public log enabled: GET /v1/server_log")
	}
	return mux
}

// reload loads the source's corpus if its version differs from the one being
// served. On any error the current corpus keeps serving.
func (s *server) reload() (bool, error) {
	v, err := readVersion(s.src)
	if err != nil {
		return false, err
	}
	old := s.cur.Load()
	if v == old.version {
		return false, nil
	}
	c, err := loadCorpus(s.src, s.opts)
	if err != nil {
		return false, err
	}
	s.cur.Store(c)
	log.Printf("now serving corpus %s (was %s)", c.version, old.version)
	time.AfterFunc(freeDelay, old.free)
	return true, nil
}

func (s *server) pollLoop(every time.Duration) {
	for range time.Tick(every) {
		if _, err := s.reload(); err != nil {
			log.Printf("corpus check: %v (still serving %s)", err, s.cur.Load().version)
		}
	}
}

func (s *server) handleManifest(w http.ResponseWriter, r *http.Request) {
	c := s.cur.Load()
	// hint URLs are absolute, built from the address the client used, so the
	// client needs no extra configuration to find them.
	scheme := "http"
	if r.TLS != nil || r.Header.Get("X-Forwarded-Proto") == "https" {
		scheme = "https"
	}
	m := make(map[string]any, len(c.manifest))
	for k, v := range c.manifest {
		m[k] = v
	}
	sc := make(map[string]any)
	for k, v := range c.manifest["scoring"].(map[string]any) {
		sc[k] = v
	}
	sc["hint_url"] = scheme + "://" + r.Host + "/v1/score_hint"
	m["scoring"] = sc
	if c.fetch != nil {
		pm := make(map[string]any)
		for k, v := range c.manifest["pir"].(map[string]any) {
			pm[k] = v
		}
		pm["hint_url"] = scheme + "://" + r.Host + "/v1/fetch_hint"
		m["pir"] = pm
	}
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

func serveBlob(w http.ResponseWriter, version string, b []byte) {
	w.Header().Set("Content-Type", "application/octet-stream")
	w.Header().Set("X-Corpus-Version", version)
	w.Write(b)
}

func (s *server) handleHint(w http.ResponseWriter, r *http.Request) {
	c := s.cur.Load()
	serveBlob(w, c.version, c.hint)
}

func (s *server) handleFetchStore(w http.ResponseWriter, r *http.Request) {
	c := s.cur.Load()
	serveBlob(w, c.version, c.store)
}

func (s *server) handleFetchHint(w http.ResponseWriter, r *http.Request) {
	c := s.cur.Load()
	if c.fetch == nil {
		http.Error(w, "real PIR is off on this server", http.StatusNotFound)
		return
	}
	serveBlob(w, c.version, c.fetchHnt)
}

// handleFetch: real PIR. The server multiplies every record by the encrypted
// selector, so it touches all of them equally and learns nothing about which
// one was wanted.
func (s *server) handleFetch(w http.ResponseWriter, r *http.Request) {
	c := s.cur.Load()
	if c.fetch == nil {
		http.Error(w, "real PIR is off on this server", http.StatusNotFound)
		return
	}
	if r.Header.Get("X-Corpus-Version") != c.version {
		http.Error(w, "stale corpus_version", http.StatusConflict)
		return
	}
	q, err := blindcrypto.UnmarshalFetchRequest(http.MaxBytesReader(w, r.Body, 1<<20))
	if err != nil || q.Query.Rows() < c.fetch.Info.M {
		http.Error(w, "bad request", http.StatusBadRequest)
		return
	}
	c.fetchMu.Lock()
	ans := c.fetch.Answer(q)
	c.fetchMu.Unlock()
	w.Header().Set("Content-Type", "application/octet-stream")
	w.Write(blindcrypto.MarshalAnswer(ans))
}

// handleFetchBatch answers several PIR selectors in one round trip. The client
// always sends exactly k, so the batch size reveals nothing.
func (s *server) handleFetchBatch(w http.ResponseWriter, r *http.Request) {
	c := s.cur.Load()
	if c.fetch == nil {
		http.Error(w, "real PIR is off on this server", http.StatusNotFound)
		return
	}
	if r.Header.Get("X-Corpus-Version") != c.version {
		http.Error(w, "stale corpus_version", http.StatusConflict)
		return
	}
	qs, err := blindcrypto.UnmarshalFetchBatch(http.MaxBytesReader(w, r.Body, 1<<24))
	if err != nil {
		http.Error(w, "bad request", http.StatusBadRequest)
		return
	}
	for _, q := range qs {
		if q.Query.Rows() < c.fetch.Info.M {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
	}
	as := make([]*pir.Answer[blindcrypto.Elem], len(qs))
	c.fetchMu.Lock()
	for i, q := range qs {
		as[i] = c.fetch.Answer(q)
	}
	c.fetchMu.Unlock()
	w.Header().Set("Content-Type", "application/octet-stream")
	w.Write(blindcrypto.MarshalAnswers(as))
}

func (s *server) handleScore(w http.ResponseWriter, r *http.Request) {
	c := s.cur.Load()
	if r.Header.Get("X-Corpus-Version") != c.version {
		http.Error(w, "stale corpus_version", http.StatusConflict)
		return
	}
	req, err := blindcrypto.UnmarshalScoreRequest(http.MaxBytesReader(w, r.Body, maxScoreBody))
	if err != nil {
		http.Error(w, "bad request", http.StatusBadRequest)
		return
	}
	if len(req.Token) > 0 && !c.score.TokenMode() {
		http.Error(w, "token mode is off on this server; use hint mode", http.StatusBadRequest)
		return
	}
	if req.Query.Query.Rows() < c.score.DB.Info.M {
		http.Error(w, "bad query size", http.StatusBadRequest)
		return
	}
	resp := c.compute(req)
	w.Header().Set("Content-Type", "application/octet-stream")
	w.Write(resp.MarshalBinary())
}

func (c *corpus) compute(req *blindcrypto.ScoreRequest) *blindcrypto.ScoreResponse {
	c.mu.Lock()
	defer c.mu.Unlock()
	ta := &underhood.HintAnswer{} // hint mode: the client already has the hint
	if len(req.Token) > 0 && c.score.TokenMode() {
		ta = c.score.HintAnswer(&req.Token) // token mode
	}
	return &blindcrypto.ScoreResponse{TokenAnswer: ta, Scores: c.score.Answer(req.Query)}
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
