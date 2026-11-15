package blindcrypto

// Hint mode: the client downloads the server's hint H = DB * A once per corpus
// version and keeps it. Each question then needs only a fresh secret s, the
// encrypted query (d values, ~3 KB) and the answer (N values). No per-query
// token, so upload and server CPU drop by ~10,000x.
//
// The hint is public (a function of the public table and the public seed) and
// is sent with its low 32 bits dropped. Decryption tolerates the extra error:
// |sum_j (H_ij - H'_ij) s_j| <= 2048 * 2^31 = 2^42, far below Delta/2 = 2^46,
// next to LWE noise around 2^30.

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"sync"

	"github.com/henrycg/simplepir/matrix"
	"github.com/henrycg/simplepir/pir"
	"github.com/henrycg/simplepir/rand"
)

// HintDropBits is how many low-order bits of each hint entry are not sent.
const HintDropBits = 32

// EncodeHint serializes the hint: u32 rows, u32 cols, then rows*cols u32 (top bits).
func EncodeHint(h *matrix.Matrix[Elem]) []byte {
	rows, cols := h.Rows(), h.Cols()
	out := make([]byte, 8+4*rows*cols)
	le.PutUint32(out[0:], uint32(rows))
	le.PutUint32(out[4:], uint32(cols))
	for i, v := range h.Data() {
		le.PutUint32(out[8+4*i:], uint32(uint64(v)>>HintDropBits))
	}
	return out
}

// DecodeHint rebuilds an approximate hint (dropped bits set to their midpoint).
func DecodeHint(b []byte, wantRows, wantCols uint64) (*matrix.Matrix[Elem], error) {
	if len(b) < 8 {
		return nil, errors.New("hint too short")
	}
	rows, cols := uint64(le.Uint32(b[0:])), uint64(le.Uint32(b[4:]))
	if rows != wantRows || cols != wantCols || uint64(len(b)) != 8+4*rows*cols {
		return nil, fmt.Errorf("hint shape %dx%d (%d bytes), want %dx%d", rows, cols, len(b), wantRows, wantCols)
	}
	m := matrix.Zeros[Elem](rows, cols)
	data := m.Data()
	for i := range data {
		data[i] = Elem(uint64(le.Uint32(b[8+4*i:]))<<HintDropBits | 1<<(HintDropBits-1))
	}
	return m, nil
}

func HintSHA256(b []byte) string {
	h := sha256.Sum256(b)
	return "sha256:" + hex.EncodeToString(h[:])
}

// HintClient is the device side of hint mode. One per corpus; safe for
// concurrent use. Every Prepare makes a fresh secret key.
type HintClient struct {
	mu sync.Mutex
	c  *pir.Client[Elem]
	n  uint64
	d  uint64
}

func NewHintClient(seed *rand.PRGKey, info *pir.DBInfo, hint *matrix.Matrix[Elem]) *HintClient {
	return &HintClient{c: pir.NewClient[Elem](hint, seed, info), n: info.L, d: info.M}
}

// HintKey is one question's secret state. Use once.
type HintKey struct {
	hc *HintClient
	s  *pir.SecretLHE[Elem]
}

// Prepare makes a fresh secret and precomputes H*s. It does not depend on the question.
func (hc *HintClient) Prepare() *HintKey {
	hc.mu.Lock()
	defer hc.mu.Unlock()
	return &HintKey{hc: hc, s: hc.c.PreprocessQueryLHE()}
}

func (k *HintKey) Dim() uint64 { return k.hc.d }

// Encrypt encrypts the d-dim int8 query under this key.
func (k *HintKey) Encrypt(q []int8) (*pir.Query[Elem], error) {
	if uint64(len(q)) != k.hc.d {
		return nil, fmt.Errorf("query has %d dims, want %d", len(q), k.hc.d)
	}
	m := matrix.Zeros[Elem](k.hc.d, 1)
	for i, x := range q {
		m.Set(uint64(i), 0, Elem(EncodeSigned(int64(x))))
	}
	k.hc.mu.Lock()
	defer k.hc.mu.Unlock()
	return k.hc.c.QueryLHEPreprocessed(m, k.s), nil
}

// Decrypt returns the N signed scores.
func (k *HintKey) Decrypt(a *pir.Answer[Elem]) []int64 {
	k.hc.mu.Lock()
	out := k.hc.c.RecoverManyLHE(k.s, a)
	k.hc.mu.Unlock()
	scores := make([]int64, k.hc.n)
	for i := uint64(0); i < k.hc.n; i++ {
		scores[i] = DecodeSigned(uint64(out.Get(i, 0)))
	}
	return scores
}

// Hint exposes the server's full hint (for EncodeHint).
func (s *ScoreServer) Hint() *matrix.Matrix[Elem] { return s.srv.Hint() }
