package blindcrypto

import (
	"bytes"
	mrand "math/rand"
	"testing"
	"time"

	"github.com/ahenzinger/underhood/underhood"
	"github.com/henrycg/simplepir/rand"
)

func TestHintMode(t *testing.T) {
	for _, n := range []uint64{2101, 5000} {
		r := mrand.New(mrand.NewSource(int64(n)))
		d := uint64(384)
		table := make([]int8, 0, n*d)
		for i := uint64(0); i < n; i++ {
			table = append(table, unitInt8(r, d)...)
		}
		db, err := NewScoreDB(table, n, d)
		if err != nil {
			t.Fatal(err)
		}
		seed := rand.RandomPRGKey()
		srv := NewScoreServer(db, seed)
		hintBytes := EncodeHint(srv.Hint())

		// Client: rebuild public shape, decode the compressed hint.
		info, _ := ScoreDBInfo(n, d)
		h, err := DecodeHint(hintBytes, n, uint64(2048))
		if err != nil {
			t.Fatal(err)
		}
		hc := NewHintClient(seed, info, h)
		for trial := 0; trial < 5; trial++ {
			qi := uint64(r.Intn(int(n)))
			q := table[qi*d : (qi+1)*d]
			start := time.Now()
			k := hc.Prepare()
			prep := time.Since(start)
			enc, _ := k.Encrypt(q)
			reqBytes := (&ScoreRequest{Token: underhood.HintQuery{}, Query: enc}).MarshalBinary()
			req, err := UnmarshalScoreRequest(bytes.NewReader(reqBytes))
			if err != nil || len(req.Token) != 0 {
				t.Fatalf("wire: %v", err)
			}
			start = time.Now()
			ans := srv.Answer(req.Query)
			serverT := time.Since(start)
			respBytes := (&ScoreResponse{TokenAnswer: &underhood.HintAnswer{}, Scores: ans}).MarshalBinary()
			resp, _ := UnmarshalScoreResponse(bytes.NewReader(respBytes))
			got := k.Decrypt(resp.Scores)
			want := PlainScores(table, q, n, d)
			for i := range want {
				if got[i] != want[i] {
					t.Fatalf("n=%d row %d: got %d want %d", n, i, got[i], want[i])
				}
			}
			if trial == 0 {
				t.Logf("n=%d: hint %.1f MB once; per question up %d B, down %d B; prepare %v, server %v; all scores exact",
					n, float64(len(hintBytes))/1e6, len(reqBytes), len(respBytes), prep, serverT)
			}
		}
		srv.Free()
	}
}
