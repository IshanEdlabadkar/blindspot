package blindcrypto

import (
	"bytes"
	"math"
	mrand "math/rand"
	"testing"
	"time"

	"github.com/henrycg/simplepir/rand"
)

// roundTrip runs the full token + query flow and returns decrypted scores.
func roundTrip(t *testing.T, table, q []int8, n, d uint64) []int64 {
	t.Helper()
	db, err := NewScoreDB(table, n, d)
	if err != nil {
		t.Fatal(err)
	}
	seed := rand.RandomPRGKey()
	srv := NewScoreServer(db, seed)
	defer srv.Free()

	cli := NewScoreClient(seed, db.Info)
	defer cli.Free()

	start := time.Now()
	tok := cli.Token()
	enc, err := cli.EncryptQuery(q)
	if err != nil {
		t.Fatal(err)
	}
	// Round-trip through the wire format, as over HTTP.
	req, err := UnmarshalScoreRequest(bytes.NewReader((&ScoreRequest{Token: *tok, Query: enc}).MarshalBinary()))
	if err != nil {
		t.Fatal(err)
	}
	respBytes := (&ScoreResponse{TokenAnswer: srv.HintAnswer(&req.Token), Scores: srv.Answer(req.Query)}).MarshalBinary()
	resp, err := UnmarshalScoreResponse(bytes.NewReader(respBytes))
	if err != nil {
		t.Fatal(err)
	}
	got := cli.DecryptScores(resp.TokenAnswer, resp.Scores)
	t.Logf("download %d KB", len(respBytes)/1024)
	t.Logf("query phase: %v", time.Since(start))
	return got
}

// Gate 1: one encrypted dot product round-trips on a 4 x 8 toy matrix.
// Full-range int8 rows can exceed P/2 here, so compare mod P (centered).
func TestGate1Toy4x8(t *testing.T) {
	r := mrand.New(mrand.NewSource(1))
	n, d := uint64(4), uint64(8)
	table := make([]int8, n*d)
	q := make([]int8, d)
	for i := range table {
		table[i] = int8(r.Intn(255) - 127)
	}
	for i := range q {
		q[i] = int8(r.Intn(255) - 127)
	}
	got := roundTrip(t, table, q, n, d)
	want := PlainScores(table, q, n, d)
	for i := range want {
		w := DecodeSigned(EncodeSigned(want[i]))
		if got[i] != w {
			t.Fatalf("row %d: got %d want %d (raw %d)", i, got[i], w, want[i])
		}
		t.Logf("row %d: encrypted=%d plaintext=%d", i, got[i], want[i])
	}
}

// unitInt8 makes an L2-normalized random vector quantized at scale 127,
// matching the agreed embedding contract.
func unitInt8(r *mrand.Rand, d uint64) []int8 {
	v := make([]float64, d)
	var norm float64
	for i := range v {
		v[i] = r.NormFloat64()
		norm += v[i] * v[i]
	}
	norm = math.Sqrt(norm)
	out := make([]int8, d)
	for i := range v {
		out[i] = int8(math.Round(v[i] / norm * 127))
	}
	return out
}

// Realistic shape: 5,000 x 384 unit vectors. Scores must match exactly,
// with no wraparound.
func TestScore5000x384(t *testing.T) {
	if testing.Short() {
		t.Skip()
	}
	r := mrand.New(mrand.NewSource(2))
	n, d := uint64(5000), uint64(384)
	table := make([]int8, 0, n*d)
	for i := uint64(0); i < n; i++ {
		table = append(table, unitInt8(r, d)...)
	}
	// Query equal to row 42 so there is a clear top hit.
	q := append([]int8(nil), table[42*d:43*d]...)
	got := roundTrip(t, table, q, n, d)
	want := PlainScores(table, q, n, d)
	best := 0
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("row %d: got %d want %d", i, got[i], want[i])
		}
		if got[i] > got[best] {
			best = i
		}
	}
	if best != 42 {
		t.Fatalf("top hit %d, want 42", best)
	}
	t.Logf("all %d scores exact; top hit row %d score %d", n, best, got[best])
}
