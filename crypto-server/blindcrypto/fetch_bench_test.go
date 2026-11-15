package blindcrypto

import (
	mrand "math/rand"
	"testing"

	"github.com/henrycg/simplepir/rand"
)

func benchFetchClient(b *testing.B) *FetchClient {
	n, recLen := uint64(2101), uint64(2048)
	store := make([]byte, n*recLen)
	mrand.New(mrand.NewSource(1)).Read(store)
	db, _ := NewFetchDB(store, n, recLen)
	seed := rand.RandomPRGKey()
	srv := NewFetchServer(db, seed)
	info, _ := FetchDBInfo(n, recLen)
	h, _ := DecodeHint(EncodeHint(srv.Hint()), info.L, 2048)
	fc := NewFetchClient(seed, info, h, n, recLen)
	fc.Close()
	return fc
}

// Preparing one fetch secret (A*s + e, H*s). With A stored: ~8 ms on a 2-vCPU VM (was ~53 ms).
func BenchmarkFetchPrepare(b *testing.B) {
	fc := benchFetchClient(b)
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		fc.prepare()
	}
}

