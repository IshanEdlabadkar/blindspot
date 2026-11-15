package main

// A corpus is one version of the provider's documents, loaded from the
// provider's own storage (a folder or a URL), verified against the manifest's
// hashes, and precomputed for serving. The server swaps in a new corpus when
// the manifest's corpus_version changes, without restarting.

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"math"
	"net/http"
	"net/url"
	"os"
	"path"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/IshanEdlabadkar/blindspot/crypto-server/blindcrypto"
)

// Files the provider's ingestion pipeline publishes.
var corpusFiles = []string{"manifest.json", "score_table.bin", "fetch_store.bin"}

const maxCorpusFile = 2 << 30

// source is where the provider keeps the corpus.
type source interface {
	Read(name string) ([]byte, error)
	String() string
}

type dirSource struct{ dir string }

func (d dirSource) Read(name string) ([]byte, error) { return os.ReadFile(filepath.Join(d.dir, name)) }
func (d dirSource) String() string                   { return d.dir }

// urlSource reads <base>/<file>. Any query string on the base (for example a
// signed-URL token) is kept on every request; auth, if set, is sent as the
// Authorization header.
type urlSource struct {
	base *url.URL
	auth string
	http *http.Client
}

func newURLSource(raw, auth string) (*urlSource, error) {
	u, err := url.Parse(raw)
	if err != nil || (u.Scheme != "https" && u.Scheme != "http") {
		return nil, fmt.Errorf("data URL must be http(s): %q", raw)
	}
	return &urlSource{base: u, auth: auth, http: &http.Client{Timeout: 10 * time.Minute}}, nil
}

func (s *urlSource) Read(name string) ([]byte, error) {
	u := *s.base
	u.Path = path.Join(u.Path, name)
	req, _ := http.NewRequest("GET", u.String(), nil)
	if s.auth != "" {
		req.Header.Set("Authorization", s.auth)
	}
	resp, err := s.http.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("GET %s: %s", name, resp.Status)
	}
	return io.ReadAll(io.LimitReader(resp.Body, maxCorpusFile))
}

func (s *urlSource) String() string {
	u := *s.base
	u.RawQuery = "" // never log tokens
	return u.String()
}

type corpusOpts struct {
	allowWrap, tokenMode, realPIR bool
}

type corpus struct {
	version  string
	manifest map[string]any
	hint     []byte
	store    []byte
	score    *blindcrypto.ScoreServer
	mu       sync.Mutex               // underhood's thread safety is undocumented; serialize
	fetch    *blindcrypto.FetchServer // nil when real PIR is off
	fetchHnt []byte
	fetchMu  sync.Mutex
}

func (c *corpus) free() { c.score.Free() }

// readVersion reads only the manifest's corpus_version (cheap, for polling).
func readVersion(src source) (string, error) {
	raw, err := src.Read("manifest.json")
	if err != nil {
		return "", err
	}
	var m struct {
		Version string `json:"corpus_version"`
	}
	if err := json.Unmarshal(raw, &m); err != nil || m.Version == "" {
		return "", errors.New("manifest.json has no corpus_version")
	}
	return m.Version, nil
}

// checkHash verifies a file against the manifest's "sha256:<hex>" entry.
func checkHash(m map[string]any, key, name string, data []byte) error {
	hashes, _ := m["hashes"].(map[string]any)
	want, _ := hashes[key].(string)
	if want == "" {
		log.Printf("WARNING: manifest has no hashes.%s; %s is not verified", key, name)
		return nil
	}
	sum := sha256.Sum256(data)
	if got := "sha256:" + hex.EncodeToString(sum[:]); got != want {
		return fmt.Errorf("%s does not match the manifest (got %s, want %s): incomplete upload or wrong version?", name, got[:19], want[:min(19, len(want))])
	}
	return nil
}

func loadCorpus(src source, o corpusOpts) (*corpus, error) {
	files := map[string][]byte{}
	for _, f := range corpusFiles {
		b, err := src.Read(f)
		if err != nil {
			return nil, fmt.Errorf("reading %s from %s: %w", f, src, err)
		}
		files[f] = b
	}
	var m map[string]any
	if err := json.Unmarshal(files["manifest.json"], &m); err != nil {
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

	tableBytes, store := files["score_table.bin"], files["fetch_store.bin"]
	if uint64(len(tableBytes)) != n*d {
		return nil, fmt.Errorf("score_table.bin is %d bytes, want N*d = %d", len(tableBytes), n*d)
	}
	if uint64(len(store)) != n*recLen {
		return nil, fmt.Errorf("fetch_store.bin is %d bytes, want N*L = %d", len(store), n*recLen)
	}
	if err := checkHash(m, "score_table", "score_table.bin", tableBytes); err != nil {
		return nil, err
	}
	if err := checkHash(m, "fetch_store", "fetch_store.bin", store); err != nil {
		return nil, err
	}

	table := make([]int8, len(tableBytes))
	for i, b := range tableBytes {
		table[i] = int8(b)
	}
	if err := checkScoreRange(table, n, d, o.allowWrap); err != nil {
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
	if o.tokenMode {
		ss = blindcrypto.NewScoreServer(db, seed)
	}
	hint := blindcrypto.EncodeHint(ss.Hint())
	log.Printf("corpus %s: precomputed score table (%d x %d) and %.1f MB hint in %v",
		version, n, d, float64(len(hint))/1e6, time.Since(start))

	// Publish what the client needs: public seeds, modes, hint locations.
	scoring, _ := m["scoring"].(map[string]any)
	if scoring == nil {
		scoring = map[string]any{}
	}
	scoring["seed"] = hex.EncodeToString(seed[:])
	scoring["modulus"] = blindcrypto.P
	scoring["library"] = "underhood (Tiptoe) + SimplePIR LHE"
	scoring["params"] = fmt.Sprintf("logq=64 n=2048 p=2^17 d=%d", d)
	scoring["mode"] = "hint" // clients may still send a token (token mode) instead, if enabled
	scoring["token_mode"] = o.tokenMode
	scoring["hint_path"] = "/v1/score_hint"
	scoring["hint_bytes"] = len(hint)
	scoring["hint_sha256"] = blindcrypto.HintSHA256(hint)
	m["scoring"] = scoring
	pirM["mode"] = "trivial" // default; "simplepir" is offered below when enabled
	pirM["modes"] = []string{"trivial"}
	pirM["library"] = "trivial PIR (whole store)"
	pirM["params"] = "none"

	c := &corpus{version: version, manifest: m, hint: hint, store: store, score: ss}
	if o.realPIR {
		start := time.Now()
		fdb, err := blindcrypto.NewFetchDB(store, n, recLen)
		if err != nil {
			ss.Free()
			return nil, err
		}
		sh := sha256.Sum256(store)
		fseed := blindcrypto.SeedFromTable(sh)
		c.fetch = blindcrypto.NewFetchServer(fdb, fseed)
		c.fetchHnt = blindcrypto.EncodeHint(c.fetch.Hint())
		pirM["modes"] = []string{"trivial", "simplepir"}
		pirM["library"] = "trivial PIR (whole store) or SimplePIR"
		pirM["params"] = fmt.Sprintf("simplepir: logq=64 n=2048 p=2^16 L=%d M=%d", c.fetch.Info.L, c.fetch.Info.M)
		pirM["seed"] = hex.EncodeToString(fseed[:])
		pirM["hint_path"] = "/v1/fetch_hint"
		pirM["hint_bytes"] = len(c.fetchHnt)
		pirM["hint_sha256"] = blindcrypto.HintSHA256(c.fetchHnt)
		log.Printf("corpus %s: precomputed PIR fetch store (L=%d x M=%d) and %.1f MB hint in %v",
			version, c.fetch.Info.L, c.fetch.Info.M, float64(len(c.fetchHnt))/1e6, time.Since(start))
	}
	return c, nil
}

// checkScoreRange: scores are exact only while |score| < P/2 = 65,536.
// By Cauchy-Schwarz a query quantized like the rows scores at most about
// (max row norm)^2. Unit vectors at scale 127 give ~16,100, a 4x margin.
// Refuse to load if a close match could wrap: it would silently vanish
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

func sourceFromFlags(dataDir, dataURL, auth string) (source, error) {
	if dataURL != "" {
		return newURLSource(strings.TrimSpace(dataURL), auth)
	}
	return dirSource{dataDir}, nil
}
