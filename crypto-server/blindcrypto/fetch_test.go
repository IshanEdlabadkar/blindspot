package blindcrypto

import (
	"bytes"
	mrand "math/rand"
	"testing"
	"time"

	"github.com/henrycg/simplepir/rand"
)

func TestFetchPIR(t *testing.T) {
	for _, n := range []uint64{2101, 9000} {
		recLen := uint64(2048)
		r := mrand.New(mrand.NewSource(int64(n)))
		store := make([]byte, n*recLen)
		r.Read(store)
		db, err := NewFetchDB(store, n, recLen)
		if err != nil {
			t.Fatal(err)
		}
		seed := rand.RandomPRGKey()
		start := time.Now()
		srv := NewFetchServer(db, seed)
		setup := time.Since(start)
		hintBytes := EncodeHint(srv.Hint())

		info, err := FetchDBInfo(n, recLen)
		if err != nil {
			t.Fatal(err)
		}
		h, err := DecodeHint(hintBytes, info.L, 2048)
		if err != nil {
			t.Fatal(err)
		}
		fc := NewFetchClient(seed, info, h, n, recLen)
		for _, idx := range []uint64{0, 1, n / 2, n - 1} {
			k, q, err := fc.Query(idx)
			if err != nil {
				t.Fatal(err)
			}
			wire := MarshalQuery(q)
			qq, _ := readVec(bytes.NewReader(wire))
			ans := srv.Answer(pirQuery{qq}.q())
			var w bytes.Buffer
			putVec(&w, ans.Answer)
			back, _ := readVec(&w)
			rec, err := k.Decrypt(pirAnswer{back}.a())
			if err != nil {
				t.Fatal(err)
			}
			if !bytes.Equal(rec, store[idx*recLen:(idx+1)*recLen]) {
				t.Fatalf("n=%d record %d mismatch", n, idx)
			}
			if idx == 0 {
				t.Logf("n=%d: L=%d M=%d; hint %.1f MB once; per fetch up %d B, down %d B; setup %v",
					n, info.L, info.M, float64(len(hintBytes))/1e6, len(wire), 4+8*ans.Answer.Rows(), setup)
			}
		}
	}
}
