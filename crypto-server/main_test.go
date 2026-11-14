package main

import (
	"bytes"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"math"
	mrand "math/rand"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	"github.com/IshanEdlabadkar/blindspot/crypto-server/blindcrypto"
	"github.com/henrycg/simplepir/rand"
)

// writeTestCorpus writes unit-norm int8 rows, fixed-size records and a manifest.
func writeTestCorpus(t *testing.T, dir string, n, d, L int) []int8 {
	r := mrand.New(mrand.NewSource(5))
	table := make([]int8, 0, n*d)
	for i := 0; i < n; i++ {
		v := make([]float64, d)
		var norm float64
		for j := range v {
			v[j] = r.NormFloat64()
			norm += v[j] * v[j]
		}
		for j := range v {
			table = append(table, int8(math.Round(v[j]/math.Sqrt(norm)*127)))
		}
	}
	tb := make([]byte, len(table))
	for i, x := range table {
		tb[i] = byte(x)
	}
	os.WriteFile(filepath.Join(dir, "score_table.bin"), tb, 0o644)
	store := make([]byte, n*L)
	for i := 0; i < n; i++ {
		js, _ := json.Marshal(map[string]any{"id": i, "title": fmt.Sprintf("Chunk %d", i)})
		binary.LittleEndian.PutUint16(store[i*L:], uint16(len(js)))
		copy(store[i*L+2:], js)
	}
	os.WriteFile(filepath.Join(dir, "fetch_store.bin"), store, 0o644)
	m := map[string]any{
		"protocol": "blind-rag/1", "corpus_version": "test.1", "num_chunks": n, "top_k": 10,
		"embedding": map[string]any{"dim": d}, "pir": map[string]any{"record_bytes": L},
	}
	mb, _ := json.Marshal(m)
	os.WriteFile(filepath.Join(dir, "manifest.json"), mb, 0o644)
	return table
}

func TestEndToEndHTTP(t *testing.T) {
	n, d, L := 5000, 384, 2048
	dir := t.TempDir()
	table := writeTestCorpus(t, dir, n, d, L)
	s, err := load(dir, false)
	if err != nil {
		t.Fatal(err)
	}
	defer s.score.Free()
	mux := http.NewServeMux()
	mux.HandleFunc("GET /v1/manifest", s.logged("/v1/manifest", s.handleManifest))
	mux.HandleFunc("POST /v1/score", s.logged("/v1/score", s.handleScore))
	mux.HandleFunc("GET /v1/fetch_store", s.logged("/v1/fetch_store", s.handleFetchStore))
	ts := httptest.NewServer(mux)
	defer ts.Close()

	// Client: manifest -> seed -> token + query -> /v1/score -> decrypt.
	resp, _ := http.Get(ts.URL + "/v1/manifest")
	var man map[string]any
	json.NewDecoder(resp.Body).Decode(&man)
	seedHex := man["scoring"].(map[string]any)["seed"].(string)
	sb, _ := hex.DecodeString(seedHex)
	var seed rand.PRGKey
	copy(seed[:], sb)
	info, _ := blindcrypto.ScoreDBInfo(uint64(n), uint64(d))
	cli := blindcrypto.NewScoreClient(&seed, info)
	defer cli.Free()

	q := table[123*d : 124*d]
	tok := cli.Token()
	enc, _ := cli.EncryptQuery(q)
	body := (&blindcrypto.ScoreRequest{Token: *tok, Query: enc}).MarshalBinary()
	resp, err = post(ts.URL+"/v1/score", "test.1", body)
	if err != nil || resp.StatusCode != 200 {
		t.Fatalf("score: %v %v", err, resp.Status)
	}
	sr, err := blindcrypto.UnmarshalScoreResponse(resp.Body)
	if err != nil {
		t.Fatal(err)
	}
	got := cli.DecryptScores(sr.TokenAnswer, sr.Scores)
	want := blindcrypto.PlainScores(table, q, uint64(n), uint64(d))
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("row %d: %d vs %d", i, got[i], want[i])
		}
	}
	t.Logf("upload %.1f MB; all %d scores exact over HTTP", float64(len(body))/1e6, n)

	// Stale version -> 409.
	bad := (&blindcrypto.ScoreRequest{Token: *tok, Query: enc}).MarshalBinary()
	resp, _ = post(ts.URL+"/v1/score", "old", bad)
	if resp.StatusCode != http.StatusConflict {
		t.Fatalf("stale version: got %d", resp.StatusCode)
	}
	// Garbage -> 400, server survives.
	resp, _ = post(ts.URL+"/v1/score", "test.1", []byte{1, 2, 3})
	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("garbage: got %d", resp.StatusCode)
	}
	// Trivial PIR: whole store.
	resp, _ = http.Get(ts.URL + "/v1/fetch_store")
	store, _ := io.ReadAll(resp.Body)
	rec := store[123*L:]
	ln := binary.LittleEndian.Uint16(rec)
	t.Logf("fetch_store %d bytes; record 123 = %s", len(store), rec[2:2+ln])
}

func post(url, version string, body []byte) (*http.Response, error) {
	req, _ := http.NewRequest("POST", url, bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/octet-stream")
	req.Header.Set("X-Corpus-Version", version)
	return http.DefaultClient.Do(req)
}
