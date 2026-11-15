// crypto-helper runs on the asker's device. It holds every secret key in
// memory, never on disk, and only listens on 127.0.0.1. Python's
// client/crypto_client calls it; nothing else should.
//
//	go run ./cmd/crypto-helper            # http://127.0.0.1:8090
//
// Endpoints (all binary, little-endian):
//
//	POST /prepare?seed=<hex>&n=<N>&d=<d>   -> header X-Handle (fresh key + token, made ahead of time)
//	POST /encrypt?handle=<id>              body: d int8 -> body for /v1/score (uses the prepared key)
//	POST /encrypt?seed=<hex>&n=<N>&d=<d>   body: d int8 -> same, one shot (fresh key now), header X-Handle
//	POST /decrypt?handle=<id>              body: /v1/score response -> N int32 scores
//	GET  /health
//
// Every /encrypt makes a fresh secret key: reusing one across questions would
// leak. /decrypt uses that key once and then wipes it. Unused keys expire.
package main

import (
	"crypto/rand"
	"encoding/binary"
	"encoding/hex"
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

const keyTTL = 10 * time.Minute

type pending struct {
	cli     *blindcrypto.ScoreClient
	token   []byte // encoded token, ready to send
	used    bool   // a query has been encrypted under this key
	created time.Time
}

type helper struct {
	mu    sync.Mutex
	infos map[[2]uint64]*pir.DBInfo // public table shape, cached per (n, d)
	keys  map[string]*pending
}

func main() {
	addr := flag.String("addr", "127.0.0.1:8090", "listen address (keep it on 127.0.0.1)")
	flag.Parse()
	h := &helper{infos: map[[2]uint64]*pir.DBInfo{}, keys: map[string]*pending{}}
	go h.expireLoop()

	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, _ *http.Request) { w.Write([]byte("ok")) })
	mux.HandleFunc("POST /prepare", h.handlePrepare)
	mux.HandleFunc("POST /encrypt", h.handleEncrypt)
	mux.HandleFunc("POST /decrypt", h.handleDecrypt)
	log.Printf("crypto-helper on http://%s (keys in memory only)", *addr)
	log.Fatal(http.ListenAndServe(*addr, mux))
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

// newKey makes a fresh secret key and its encoded token for (seed, n, d).
func (h *helper) newKey(r *http.Request) (*pending, uint64, error) {
	q := r.URL.Query()
	seedBytes, err := hex.DecodeString(q.Get("seed"))
	n, err2 := strconv.ParseUint(q.Get("n"), 10, 64)
	d, err3 := strconv.ParseUint(q.Get("d"), 10, 64)
	var seed sprand.PRGKey
	if err != nil || err2 != nil || err3 != nil || len(seedBytes) != len(seed) || n == 0 || d == 0 {
		return nil, 0, fmt.Errorf("need seed (hex, from manifest scoring.seed), n, d")
	}
	copy(seed[:], seedBytes)
	inf, err := h.info(n, d)
	if err != nil {
		return nil, 0, err
	}
	cli := blindcrypto.NewScoreClient(&seed, inf)
	tok := cli.Token()
	return &pending{cli: cli, token: blindcrypto.MarshalToken(*tok), created: time.Now()}, d, nil
}

func (h *helper) store(p *pending) string {
	id := newHandle()
	h.mu.Lock()
	h.keys[id] = p
	h.mu.Unlock()
	return id
}

func (h *helper) handlePrepare(w http.ResponseWriter, r *http.Request) {
	p, _, err := h.newKey(r)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	w.Header().Set("X-Handle", h.store(p))
}

func (h *helper) handleEncrypt(w http.ResponseWriter, r *http.Request) {
	var p *pending
	id := r.URL.Query().Get("handle")
	if id != "" {
		h.mu.Lock()
		p = h.keys[id]
		if p != nil && p.used {
			p = nil // never encrypt two questions under one key
		}
		if p != nil {
			p.used = true
		}
		h.mu.Unlock()
		if p == nil {
			http.Error(w, "unknown, expired or used handle; call /prepare again", http.StatusNotFound)
			return
		}
	} else {
		var err error
		if p, _, err = h.newKey(r); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		p.used = true
		id = h.store(p)
	}

	d := p.cli.Dim()
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
	enc, err := p.cli.EncryptQuery(vec)
	if err != nil {
		h.drop(id)
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	q := blindcrypto.MarshalQuery(enc)
	w.Header().Set("Content-Type", "application/octet-stream")
	w.Header().Set("Content-Length", strconv.Itoa(len(p.token)+len(q)))
	w.Header().Set("X-Handle", id)
	w.Write(p.token)
	w.Write(q)
}

func (h *helper) drop(id string) {
	h.mu.Lock()
	if p := h.keys[id]; p != nil {
		p.cli.Free()
		delete(h.keys, id)
	}
	h.mu.Unlock()
}

func (h *helper) handleDecrypt(w http.ResponseWriter, r *http.Request) {
	id := r.URL.Query().Get("handle")
	h.mu.Lock()
	p := h.keys[id]
	delete(h.keys, id) // one use only
	h.mu.Unlock()
	if p == nil {
		http.Error(w, "unknown or expired handle; call /encrypt again", http.StatusNotFound)
		return
	}
	defer p.cli.Free()

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
		scores = p.cli.DecryptScores(resp.TokenAnswer, resp.Scores)
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

func (h *helper) expireLoop() {
	for range time.Tick(time.Minute) {
		h.mu.Lock()
		for id, p := range h.keys {
			if time.Since(p.created) > keyTTL {
				p.cli.Free()
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
