package main

import (
	"bytes"
	"crypto/sha256"
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
	"strings"
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
	s, err := load(dir, false, true, true)
	if err != nil {
		t.Fatal(err)
	}
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

func TestEndToEndHintModeHTTP(t *testing.T) {
	n, d, L := 2101, 384, 2048
	dir := t.TempDir()
	table := writeTestCorpus(t, dir, n, d, L)
	s, err := load(dir, false, true, true)
	if err != nil {
		t.Fatal(err)
	}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /v1/manifest", s.logged("/v1/manifest", s.handleManifest))
	mux.HandleFunc("GET /v1/score_hint", s.logged("/v1/score_hint", s.handleHint))
	mux.HandleFunc("POST /v1/score", s.logged("/v1/score", s.handleScore))
	ts := httptest.NewServer(mux)
	defer ts.Close()

	resp, _ := http.Get(ts.URL + "/v1/manifest")
	var man map[string]any
	json.NewDecoder(resp.Body).Decode(&man)
	sc := man["scoring"].(map[string]any)
	if sc["mode"] != "hint" {
		t.Fatalf("mode %v", sc["mode"])
	}
	resp, err = http.Get(sc["hint_url"].(string)) // absolute URL from the manifest
	if err != nil {
		t.Fatal(err)
	}
	hintBytes, _ := io.ReadAll(resp.Body)
	if blindcrypto.HintSHA256(hintBytes) != sc["hint_sha256"] {
		t.Fatal("hint hash mismatch")
	}
	sb, _ := hex.DecodeString(sc["seed"].(string))
	var seed rand.PRGKey
	copy(seed[:], sb)
	info, _ := blindcrypto.ScoreDBInfo(uint64(n), uint64(d))
	h, err := blindcrypto.DecodeHint(hintBytes, uint64(n), 2048)
	if err != nil {
		t.Fatal(err)
	}
	hc := blindcrypto.NewHintClient(&seed, info, h)
	for _, qi := range []int{0, 777, 2100} {
		k := hc.Prepare()
		q := table[qi*d : (qi+1)*d]
		enc, _ := k.Encrypt(q)
		body := (&blindcrypto.ScoreRequest{Query: enc}).MarshalBinary()
		resp, err := post(ts.URL+"/v1/score", "test.1", body)
		if err != nil || resp.StatusCode != 200 {
			t.Fatalf("score: %v", err)
		}
		sr, err := blindcrypto.UnmarshalScoreResponse(resp.Body)
		if err != nil {
			t.Fatal(err)
		}
		got := k.Decrypt(sr.Scores)
		want := blindcrypto.PlainScores(table, q, uint64(n), uint64(d))
		for i := range want {
			if got[i] != want[i] {
				t.Fatalf("q%d row %d: %d vs %d", qi, i, got[i], want[i])
			}
		}
		if qi == 0 {
			t.Logf("hint %.1f MB once; per question upload %d B; all %d scores exact", float64(len(hintBytes))/1e6, len(body), n)
		}
	}
}

func TestFetchPIRHTTP(t *testing.T) {
	n, d, L := 2101, 384, 2048
	dir := t.TempDir()
	writeTestCorpus(t, dir, n, d, L)
	store, _ := os.ReadFile(filepath.Join(dir, "fetch_store.bin"))
	s, err := load(dir, false, false, true)
	if err != nil {
		t.Fatal(err)
	}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /v1/manifest", s.logged("/v1/manifest", s.handleManifest))
	mux.HandleFunc("GET /v1/fetch_hint", s.logged("/v1/fetch_hint", s.handleFetchHint))
	mux.HandleFunc("POST /v1/fetch", s.logged("/v1/fetch", s.handleFetch))
	ts := httptest.NewServer(mux)
	defer ts.Close()

	resp, _ := http.Get(ts.URL + "/v1/manifest")
	var man map[string]any
	json.NewDecoder(resp.Body).Decode(&man)
	pm := man["pir"].(map[string]any)
	resp, _ = http.Get(pm["hint_url"].(string))
	hb, _ := io.ReadAll(resp.Body)
	if blindcrypto.HintSHA256(hb) != pm["hint_sha256"] {
		t.Fatal("fetch hint hash mismatch")
	}
	sb, _ := hex.DecodeString(pm["seed"].(string))
	var seed rand.PRGKey
	copy(seed[:], sb)
	info, _ := blindcrypto.FetchDBInfo(uint64(n), uint64(L))
	h, err := blindcrypto.DecodeHint(hb, info.L, 2048)
	if err != nil {
		t.Fatal(err)
	}
	fc := blindcrypto.NewFetchClient(&seed, info, h, uint64(n), uint64(L))
	for _, idx := range []uint64{0, 1234, 2100} {
		k, q, _ := fc.Query(idx)
		resp, err := post(ts.URL+"/v1/fetch", "test.1", blindcrypto.MarshalQuery(q))
		if err != nil || resp.StatusCode != 200 {
			t.Fatalf("fetch: %v %v", err, resp.Status)
		}
		a, err := blindcrypto.UnmarshalAnswer(resp.Body)
		if err != nil {
			t.Fatal(err)
		}
		rec, err := k.Decrypt(a)
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(rec, store[idx*uint64(L):(idx+1)*uint64(L)]) {
			t.Fatalf("record %d mismatch", idx)
		}
	}
	t.Logf("real PIR over HTTP: 3 records exact; fetch hint %.1f MB", float64(len(hb))/1e6)
}

// addHashes writes the manifest's hashes, as B's ingestion pipeline does.
func addHashes(t *testing.T, dir, version string) {
	mb, _ := os.ReadFile(filepath.Join(dir, "manifest.json"))
	var m map[string]any
	json.Unmarshal(mb, &m)
	h := map[string]any{}
	for key, name := range map[string]string{"score_table": "score_table.bin", "fetch_store": "fetch_store.bin"} {
		b, _ := os.ReadFile(filepath.Join(dir, name))
		sum := sha256.Sum256(b)
		h[key] = "sha256:" + hex.EncodeToString(sum[:])
	}
	m["hashes"] = h
	m["corpus_version"] = version
	mb, _ = json.Marshal(m)
	os.WriteFile(filepath.Join(dir, "manifest.json"), mb, 0o644)
}

func TestURLSourceVerifyAndHotReload(t *testing.T) {
	dir := t.TempDir()
	writeTestCorpus(t, dir, 300, 384, 2048)
	addHashes(t, dir, "v1")
	storage := httptest.NewServer(http.FileServer(http.Dir(dir))) // the provider's storage
	defer storage.Close()

	src, err := newURLSource(storage.URL+"/?sig=secret", "")
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(src.String(), "secret") {
		t.Fatal("source string leaks the token")
	}
	s, err := newServer(src, corpusOpts{realPIR: true})
	if err != nil {
		t.Fatal(err)
	}
	ts := httptest.NewServer(s.routes(false))
	defer ts.Close()
	if v := s.cur.Load().version; v != "v1" {
		t.Fatalf("version %s", v)
	}
	if changed, err := s.reload(); changed || err != nil {
		t.Fatalf("no-op reload: %v %v", changed, err)
	}

	// A half-finished upload: v2 manifest, but the store doesn't match its hash.
	addHashes(t, dir, "v2")
	f, _ := os.OpenFile(filepath.Join(dir, "fetch_store.bin"), os.O_WRONLY, 0)
	f.WriteAt([]byte{0xff}, 5000)
	f.Close()
	if _, err := s.reload(); err == nil || !strings.Contains(err.Error(), "does not match") {
		t.Fatalf("corrupt upload accepted: %v", err)
	}
	if s.cur.Load().version != "v1" {
		t.Fatal("swapped to a corrupt corpus")
	}

	// Upload finishes: now v2 is valid and is swapped in.
	writeTestCorpus(t, dir, 300, 384, 2048)
	addHashes(t, dir, "v2")
	if changed, err := s.reload(); !changed || err != nil {
		t.Fatalf("reload to v2: %v %v", changed, err)
	}
	resp, _ := http.Get(ts.URL + "/v1/manifest")
	var man map[string]any
	json.NewDecoder(resp.Body).Decode(&man)
	if man["corpus_version"] != "v2" {
		t.Fatalf("manifest still %v", man["corpus_version"])
	}
	// A client still on v1 is told to reload.
	resp, _ = post(ts.URL+"/v1/score", "v1", []byte{0, 0, 0, 0})
	if resp.StatusCode != http.StatusConflict {
		t.Fatalf("stale client got %d", resp.StatusCode)
	}
	t.Logf("URL source: corrupt upload rejected, v1 -> v2 swapped live, stale client gets 409")
}

// A stand-in for Databricks' Files API: GET /api/2.0/fs/files/Volumes/... with a bearer token.
func TestDatabricksStyleSource(t *testing.T) {
	dir := t.TempDir()
	writeTestCorpus(t, dir, 200, 384, 2048)
	addHashes(t, dir, "dbx.1")
	const prefix = "/api/2.0/fs/files/Volumes/main/blindrag/corpus/current/"
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer dapi-test" {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		if !strings.HasPrefix(r.URL.Path, prefix) {
			http.NotFound(w, r)
			return
		}
		http.ServeFile(w, r, filepath.Join(dir, strings.TrimPrefix(r.URL.Path, prefix)))
	}))
	defer fake.Close()

	if _, err := sourceFromFlags("", fake.URL+prefix, ""); err != nil {
		t.Fatal(err)
	}
	noAuth, _ := sourceFromFlags("", fake.URL+prefix, "")
	if _, err := newServer(noAuth, corpusOpts{}); err == nil || !strings.Contains(err.Error(), "401") {
		t.Fatalf("missing token not reported: %v", err)
	}
	src, _ := sourceFromFlags("", fake.URL+prefix, "Bearer dapi-test")
	s, err := newServer(src, corpusOpts{realPIR: true})
	if err != nil {
		t.Fatal(err)
	}
	if s.cur.Load().version != "dbx.1" {
		t.Fatal("wrong version")
	}
	t.Logf("Databricks-style volume URL + bearer token: corpus %s loaded and verified", s.cur.Load().version)
}
