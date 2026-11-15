// Package blindcrypto wraps Tiptoe's underhood library for Blindspot's
// encrypted scoring: the server multiplies an N x d int8 matrix by an
// encrypted d-dim int8 query and returns N encrypted scores.
//
// All arithmetic happens mod P. Signed values are stored as x mod P and
// decoded back to the centered range (-P/2, P/2]. With L2-normalized
// embeddings quantized at scale 127, |score| <= ~127^2 + rounding slack,
// far below P/2 = 65,536.
package blindcrypto

import (
	"fmt"

	"github.com/ahenzinger/underhood/underhood"
	"github.com/henrycg/simplepir/lwe"
	"github.com/henrycg/simplepir/matrix"
	"github.com/henrycg/simplepir/pir"
	"github.com/henrycg/simplepir/rand"
)

// P is the plaintext modulus. LHE needs a power of two, and underhood's hint
// compression (NumLimbs64 = 8) is tuned for 2^17, Tiptoe's own setting.
const P = uint64(1 << 17)

// LogQ: 64-bit ciphertext modulus (needed for P this large).
const LogQ = uint64(64)

type Elem = matrix.Elem64

// EncodeSigned maps a signed value into Z_P.
func EncodeSigned(x int64) uint64 {
	m := x % int64(P)
	if m < 0 {
		m += int64(P)
	}
	return uint64(m)
}

// DecodeSigned maps a Z_P value back to the centered signed range.
func DecodeSigned(v uint64) int64 {
	v %= P
	if v > P/2 {
		return int64(v) - int64(P)
	}
	return int64(v)
}

// ScoreParams returns LWE params for a matrix with d columns.
func ScoreParams(d uint64) (*lwe.Params, error) {
	p := lwe.NewParamsFixedP(LogQ, d, P)
	if p == nil {
		return nil, fmt.Errorf("no LWE params for d=%d, P=%d", d, P)
	}
	return p, nil
}

// NewScoreDB builds the server's linear function from an N x d int8 table
// stored row by row (the agreed score_table.bin layout).
func NewScoreDB(table []int8, n, d uint64) (*pir.Database[Elem], error) {
	if uint64(len(table)) != n*d {
		return nil, fmt.Errorf("table has %d values, want %d", len(table), n*d)
	}
	params, err := ScoreParams(d)
	if err != nil {
		return nil, err
	}
	vals := make([]uint64, len(table))
	for i, x := range table {
		vals[i] = EncodeSigned(int64(x))
	}
	// rowLength 17 bits = one Z_P element per entry (Ne = 1), as LHE requires.
	db := pir.NewDatabaseFixedParams[Elem](n*d, 17, vals, params)
	if db.Info.M != d || db.Info.L != n {
		return nil, fmt.Errorf("unexpected db shape L=%d M=%d", db.Info.L, db.Info.M)
	}
	return db, nil
}

// ScoreServer holds the table and precomputed state. Call Free when done.
// With token mode off it skips underhood's token-answer precomputation,
// which is most of the memory (~650 MB vs ~100 MB at 2,101 chunks).
type ScoreServer struct {
	DB   *pir.Database[Elem]
	Seed *rand.PRGKey
	srv  *underhood.Server[Elem] // nil when token mode is off
	pirS *pir.Server[Elem]       // used when token mode is off
}

func NewScoreServer(db *pir.Database[Elem], seed *rand.PRGKey) *ScoreServer {
	return &ScoreServer{DB: db, Seed: seed, srv: underhood.NewServer(db, seed)}
}

// NewScoreServerHintOnly serves hint mode only.
func NewScoreServerHintOnly(db *pir.Database[Elem], seed *rand.PRGKey) *ScoreServer {
	return &ScoreServer{DB: db, Seed: seed, pirS: pir.NewServerSeed(db, seed)}
}

func (s *ScoreServer) TokenMode() bool { return s.srv != nil }

func (s *ScoreServer) Free() {
	if s.srv != nil {
		s.srv.Free()
	}
}

// HintAnswer answers a token-mode token. Panics if token mode is off; check TokenMode.
func (s *ScoreServer) HintAnswer(q *underhood.HintQuery) *underhood.HintAnswer {
	return s.srv.HintAnswer(q)
}

func (s *ScoreServer) Answer(q *pir.Query[Elem]) *pir.Answer[Elem] {
	if s.srv != nil {
		return s.srv.Answer(q)
	}
	return s.pirS.Answer(q)
}

// ScoreClient is the device side. The secret lives only in this struct.
// One client = one question: Token, EncryptQuery, then DecryptScores.
type ScoreClient struct {
	c *underhood.Client[Elem]
	d uint64
	n uint64
}

// ScoreDBInfo rebuilds the public table shape on the client, including the
// compression fields the server sets when it squishes its matrix.
func ScoreDBInfo(n, d uint64) (*pir.DBInfo, error) {
	params, err := ScoreParams(d)
	if err != nil {
		return nil, err
	}
	db := pir.NewDatabaseFixedParams[Elem](n*d, 17, make([]uint64, n*d), params)
	db.Squish()
	return db.Info, nil
}

func NewScoreClient(seed *rand.PRGKey, info *pir.DBInfo) *ScoreClient {
	return &ScoreClient{c: underhood.NewClient[Elem](seed, info), d: info.M, n: info.L}
}

func (c *ScoreClient) Free() { c.c.Free() }

// Dim is the query dimension d.
func (c *ScoreClient) Dim() uint64 { return c.d }

// Token makes a fresh secret key and returns its encryption for the server.
// It does not depend on the question, so it can run while the user types.
func (c *ScoreClient) Token() *underhood.HintQuery {
	hq := c.c.HintQuery()
	c.c.PreprocessQueryLHE()
	return hq
}

// EncryptQuery encrypts a d-dim int8 vector. Call Token first.
func (c *ScoreClient) EncryptQuery(q []int8) (*pir.Query[Elem], error) {
	if uint64(len(q)) != c.d {
		return nil, fmt.Errorf("query has %d dims, want %d", len(q), c.d)
	}
	m := matrix.Zeros[Elem](c.d, 1)
	for i, x := range q {
		m.Set(uint64(i), 0, Elem(EncodeSigned(int64(x))))
	}
	return c.c.QueryLHE(m), nil
}

// DecryptScores uses the server's token answer and returns the N signed scores.
func (c *ScoreClient) DecryptScores(ta *underhood.HintAnswer, a *pir.Answer[Elem]) []int64 {
	c.c.HintRecover(ta)
	out := c.c.RecoverLHE(a)
	scores := make([]int64, c.n)
	for i := uint64(0); i < c.n; i++ {
		scores[i] = DecodeSigned(uint64(out.Get(i, 0)))
	}
	return scores
}

// SeedFromTable derives the public matrix-A seed from the score table bytes,
// so server and client agree without a manifest field B has to write.
// It is public by design; security rests on the client's secret, not the seed.
func SeedFromTable(tableHash [32]byte) *rand.PRGKey {
	var k rand.PRGKey
	copy(k[:], tableHash[:len(k)])
	return &k
}

// PlainScores is the reference: table (N x d) times query, in int64.
func PlainScores(table []int8, q []int8, n, d uint64) []int64 {
	out := make([]int64, n)
	for i := uint64(0); i < n; i++ {
		var s int64
		for j := uint64(0); j < d; j++ {
			s += int64(table[i*d+j]) * int64(q[j])
		}
		out[i] = s
	}
	return out
}
