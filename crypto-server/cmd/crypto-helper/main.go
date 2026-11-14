// crypto-helper runs on the asker's device. It holds every secret key in
// memory, never on disk, and only listens on 127.0.0.1. Python's
// client/crypto_client calls it; nothing else should.
//
//	go run ./cmd/crypto-helper            # http://127.0.0.1:8090
//
// Endpoints (all binary, little-endian):
//
//	POST /encrypt?seed=<hex>&n=<N>&d=<d>   body: d int8   -> body for /v1/score, header X-Handle
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

func (h *helper) handleEncrypt(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	seedBytes, err := hex.DecodeString(q.Get("seed"))
	n, err2 := strconv.ParseUint(q.Get("n"), 10, 64)
	d, err3 := strconv.ParseUint(q.Get("d"), 10, 64)
	var seed sprand.PRGKey
	if err != nil || err2 != nil || err3 != nil || len(seedBytes) != len(seed) || n == 0 || d == 0 {
		http.Error(w, "need seed (hex, from manifest scoring.seed), n, d", http.StatusBadRequest)
		return
	}
	copy(seed[:], seedBytes)
	body, err := io.ReadAll(io.LimitReader(r.Body, int64(d)+1))
	if err != nil || uint64(len(body)) != d {
		http.Error(w, fmt.Sprintf("body must be exactly d=%d int8 bytes", d), http.StatusBadRequest)
		return
	}
	vec := make([]int8, d)
	for i, b := range body {
		vec[i] = int8(b)
	}
	inf, err := h.info(n, d)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	cli := blindcrypto.NewScoreClient(&seed, inf)
	tok := cli.Token()
	enc, err := cli.EncryptQuery(vec)
	if err != nil {
		cli.Free()
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	id := newHandle()
	h.mu.Lock()
	h.keys[id] = &pending{cli: cli, created: time.Now()}
	h.mu.Unlock()

	w.Header().Set("Content-Type", "application/octet-stream")
	w.Header().Set("X-Handle", id)
	w.Write((&blindcrypto.ScoreRequest{Token: *tok, Query: enc}).MarshalBinary())
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
