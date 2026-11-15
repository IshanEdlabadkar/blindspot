// crypto-helper runs on the asker's device. It holds every secret key in
// memory, never on disk, and only listens on 127.0.0.1. Python's
// client/crypto_client calls it; nothing else should.
//
//	go run ./cmd/crypto-helper            # http://127.0.0.1:8090
//
// Two scoring modes (the manifest's scoring.mode says which the server prefers):
//
//	hint  : the public hint is loaded once per corpus; each question is ~3 KB up.
//	token : no hint; each question uploads a ~33 MB token (Tiptoe's underhood).
//
// Endpoints (binary bodies, little-endian; P = seed=<hex>&n=<N>&d=<d>&mode=hint|token):
//
//	GET  /hint?seed=&n=&d=        200 if the hint for this corpus is loaded, else 404
//	POST /hint?seed=&n=&d=        body: hint from /v1/score_hint -> loads it
//	POST /prepare?P               -> header X-Handle (fresh key, made ahead of time)
//	POST /encrypt?handle=<id>     body: d int8 -> body for /v1/score (uses the prepared key once)
//	POST /encrypt?P               body: d int8 -> same, one shot, header X-Handle
//	POST /decrypt?handle=<id>     body: /v1/score response -> N int32 scores; wipes the key
//	GET  /health
//
// Every question gets a fresh secret key: reusing one would leak. Unused keys
// expire after 10 minutes.
package main

import (
	"crypto/rand"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"strconv"
	"sync"
	"time"

	"github.com/IshanEdlabadkar/blindspot/crypto-server/blindcrypto"
	"github.com/henrycg/simplepir/pir"
	sprand "github.com/henrycg/simplepir/rand"
)

const (
	keyTTL     = 10 * time.Minute
	hintCols   = 2048 // LWE secret dimension for 64-bit params
	maxHintLen = 1 << 30
)

// questionKey is one question's secret state, in either mode.
type questionKey interface {
	token() []byte // encoded token prefix for /v1/score (empty in hint mode)
	dim() uint64
	encrypt(q []int8) (*pir.Query[blindcrypto.Elem], error)
	decrypt(r *blindcrypto.ScoreResponse) []int64
	free()
}

type tokenKey struct {
	cli *blindcrypto.ScoreClient
	tok []byte
}

func (k *tokenKey) token() []byte { return k.tok }
func (k *tokenKey) dim() uint64   { return k.cli.Dim() }
func (k *tokenKey) encrypt(q []int8) (*pir.Query[blindcrypto.Elem], error) {
	return k.cli.EncryptQuery(q)
}
func (k *tokenKey) decrypt(r *blindcrypto.ScoreResponse) []int64 {
	return k.cli.DecryptScores(r.TokenAnswer, r.Scores)
}
func (k *tokenKey) free() { k.cli.Free() }

type hintKey struct{ k *blindcrypto.HintKey }

var emptyToken = blindcrypto.MarshalToken(nil)

func (k *hintKey) token() []byte { return emptyToken }
func (k *hintKey) dim() uint64   { return k.k.Dim() }
func (k *hintKey) encrypt(q []int8) (*pir.Query[blindcrypto.Elem], error) {
	return k.k.Encrypt(q)
}
func (k *hintKey) decrypt(r *blindcrypto.ScoreResponse) []int64 { return k.k.Decrypt(r.Scores) }
func (k *hintKey) free()                                        {}

type pending struct {
	key     questionKey
	used    bool
	created time.Time
}

type corpus struct {
	seed sprand.PRGKey
	n, d uint64
}

type helper struct {
	mu    sync.Mutex
	infos map[[2]uint64]*pir.DBInfo
	hints map[corpus]*blindcrypto.HintClient
	keys  map[string]*pending
}

func main() {
	addr := flag.String("addr", "127.0.0.1:8090", "listen address (keep it on 127.0.0.1)")
	flag.Parse()
	h := &helper{infos: map[[2]uint64]*pir.DBInfo{}, hints: map[corpus]*blindcrypto.HintClient{},
		keys: map[string]*pending{}}
	go h.expireLoop()

	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, _ *http.Request) { w.Write([]byte("ok")) })
	mux.HandleFunc("GET /hint", h.handleHintStatus)
	mux.HandleFunc("POST /hint", h.handleHintLoad)
	mux.HandleFunc("POST /prepare", h.handlePrepare)
	mux.HandleFunc("POST /encrypt", h.handleEncrypt)
	mux.HandleFunc("POST /decrypt", h.handleDecrypt)
	log.Printf("crypto-helper on http://%s (keys in memory only)", *addr)
	log.Fatal(http.ListenAndServe(*addr, mux))
}

func parseCorpus(r *http.Request) (corpus, error) {
	q := r.URL.Query()
	var c corpus
	seedBytes, err := hex.DecodeString(q.Get("seed"))
	n, err2 := strconv.ParseUint(q.Get("n"), 10, 64)
	d, err3 := strconv.ParseUint(q.Get("d"), 10, 64)
	if err != nil || err2 != nil || err3 != nil || len(seedBytes) != len(c.seed) || n == 0 || d == 0 {
		return c, errors.New("need seed (hex, from manifest scoring.seed), n, d")
	}
	copy(c.seed[:], seedBytes)
	c.n, c.d = n, d
	return c, nil
}

func (h *helper) info(n, d uint64) (*pir.DBInfo, error) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if inf, ok := h.infos[[2]uint64{n, d}]; ok {
		return inf, nil
	}
	inf, err := blindcrypto.ScoreDBInfo(n, d)
	if err == nil {
		h.infos[[2]uint64{n, d}] = inf
	}
	return inf, err
}

func (h *helper) hintClient(c corpus) *blindcrypto.HintClient {
	h.mu.Lock()
	defer h.mu.Unlock()
	return h.hints[c]
}

func (h *helper) handleHintStatus(w http.ResponseWriter, r *http.Request) {
	c, err := parseCorpus(r)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	if h.hintClient(c) == nil {
		http.Error(w, "hint not loaded", http.StatusNotFound)
		return
	}
	w.Write([]byte("loaded"))
}

func (h *helper) handleHintLoad(w http.ResponseWriter, r *http.Request) {
	c, err := parseCorpus(r)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	body, err := io.ReadAll(io.LimitReader(r.Body, maxHintLen))
	if err != nil {
		http.Error(w, "read error", http.StatusBadRequest)
		return
	}
	inf, err := h.info(c.n, c.d)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	hint, err := blindcrypto.DecodeHint(body, c.n, hintCols)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	seed := c.seed
	hc := blindcrypto.NewHintClient(&seed, inf, hint)
	h.mu.Lock()
	h.hints[c] = hc
	h.mu.Unlock()
	log.Printf("loaded hint for corpus n=%d d=%d (%.1f MB)", c.n, c.d, float64(len(body))/1e6)
	w.Write([]byte("loaded"))
}

var errNoHint = errors.New("hint not loaded for this corpus; POST /hint first")

// newKey makes a fresh secret key for the request's corpus and mode.
func (h *helper) newKey(r *http.Request) (questionKey, error) {
	c, err := parseCorpus(r)
	if err != nil {
		return nil, err
	}
	if r.URL.Query().Get("mode") == "hint" {
		hc := h.hintClient(c)
		if hc == nil {
			return nil, errNoHint
		}
		return &hintKey{hc.Prepare()}, nil
	}
	inf, err := h.info(c.n, c.d)
	if err != nil {
		return nil, err
	}
	seed := c.seed
	cli := blindcrypto.NewScoreClient(&seed, inf)
	return &tokenKey{cli: cli, tok: blindcrypto.MarshalToken(*cli.Token())}, nil
}

func keyError(w http.ResponseWriter, err error) {
	code := http.StatusBadRequest
	if err == errNoHint {
		code = http.StatusConflict
	}
	http.Error(w, err.Error(), code)
}

func (h *helper) store(k questionKey, used bool) string {
	id := newHandle()
	h.mu.Lock()
	h.keys[id] = &pending{key: k, used: used, created: time.Now()}
	h.mu.Unlock()
	return id
}

func (h *helper) handlePrepare(w http.ResponseWriter, r *http.Request) {
	k, err := h.newKey(r)
	if err != nil {
		keyError(w, err)
		return
	}
	w.Header().Set("X-Handle", h.store(k, false))
}

func (h *helper) handleEncrypt(w http.ResponseWriter, r *http.Request) {
	var k questionKey
	id := r.URL.Query().Get("handle")
	if id != "" {
		h.mu.Lock()
		p := h.keys[id]
		if p != nil && !p.used {
			p.used = true // never encrypt two questions under one key
			k = p.key
		}
		h.mu.Unlock()
		if k == nil {
			http.Error(w, "unknown, expired or used handle; call /prepare again", http.StatusNotFound)
			return
		}
	} else {
		var err error
		if k, err = h.newKey(r); err != nil {
			keyError(w, err)
			return
		}
		id = h.store(k, true)
	}

	d := k.dim()
	body, err := io.ReadAll(io.LimitReader(r.Body, int64(d)+1))
	if err != nil || uint64(len(body)) != d {
		h.drop(id)
		http.Error(w, fmt.Sprintf("body must be exactly d=%d int8 bytes", d), http.StatusBadRequest)
		return
	}
	vec := make([]int8, d)
	for i, b := range body {
		vec[i] = int8(b)
	}
	enc, err := k.encrypt(vec)
	if err != nil {
		h.drop(id)
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	tok, q := k.token(), blindcrypto.MarshalQuery(enc)
	w.Header().Set("Content-Type", "application/octet-stream")
	w.Header().Set("Content-Length", strconv.Itoa(len(tok)+len(q)))
	w.Header().Set("X-Handle", id)
	w.Write(tok)
	w.Write(q)
}

func (h *helper) handleDecrypt(w http.ResponseWriter, r *http.Request) {
	id := r.URL.Query().Get("handle")
	h.mu.Lock()
	p := h.keys[id]
	delete(h.keys, id) // one use only
	h.mu.Unlock()
	if p == nil || !p.used {
		if p != nil {
			p.key.free()
		}
		http.Error(w, "unknown or expired handle; call /encrypt again", http.StatusNotFound)
		return
	}
	defer p.key.free()

	resp, err := blindcrypto.UnmarshalScoreResponse(r.Body)
	if err != nil {
		http.Error(w, "bad score response", http.StatusBadRequest)
		return
	}
	var scores []int64
	func() {
		defer func() {
			if recover() != nil {
				err = fmt.Errorf("decryption failed")
			}
		}()
		scores = p.key.decrypt(resp)
	}()
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	out := make([]byte, 4*len(scores))
	for i, s := range scores {
		binary.LittleEndian.PutUint32(out[4*i:], uint32(int32(s)))
	}
	w.Header().Set("Content-Type", "application/octet-stream")
	w.Write(out)
}

func (h *helper) drop(id string) {
	h.mu.Lock()
	if p := h.keys[id]; p != nil {
		p.key.free()
		delete(h.keys, id)
	}
	h.mu.Unlock()
}

func (h *helper) expireLoop() {
	for range time.Tick(time.Minute) {
		h.mu.Lock()
		for id, p := range h.keys {
			if time.Since(p.created) > keyTTL {
				p.key.free()
				delete(h.keys, id)
			}
		}
		h.mu.Unlock()
	}
}

func newHandle() string {
	var b [16]byte
	rand.Read(b[:])
	return hex.EncodeToString(b[:])
}
