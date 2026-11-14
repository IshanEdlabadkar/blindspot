// Package blindcrypto wraps Tiptoe's underhood library for Blind RAG's
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

// ScoreServer holds the table and precomputed hint. Call Free when done.
type ScoreServer struct {
	DB   *pir.Database[Elem]
	Seed *rand.PRGKey
	srv  *underhood.Server[Elem]
}

func NewScoreServer(db *pir.Database[Elem], seed *rand.PRGKey) *ScoreServer {
	return &ScoreServer{DB: db, Seed: seed, srv: underhood.NewServer(db, seed)}
}

func (s *ScoreServer) Free() { s.srv.Free() }

func (s *ScoreServer) HintAnswer(q *underhood.HintQuery) *underhood.HintAnswer {
	return s.srv.HintAnswer(q)
}

func (s *ScoreServer) Answer(q *pir.Query[Elem]) *pir.Answer[Elem] {
	return s.srv.Answer(q)
}

// ScoreClient is the device side. The secret lives only in this struct.
type ScoreClient struct {
	c *underhood.Client[Elem]
	d uint64
}

func NewScoreClient(seed *rand.PRGKey, info *pir.DBInfo) *ScoreClient {
	return &ScoreClient{c: underhood.NewClient[Elem](seed, info), d: info.M}
}

func (c *ScoreClient) Free() { c.c.Free() }

// HintQuery starts the token phase (fresh secret key).
func (c *ScoreClient) HintQuery() *underhood.HintQuery { return c.c.HintQuery() }

// HintRecover finishes the token phase.
func (c *ScoreClient) HintRecover(a *underhood.HintAnswer) {
	c.c.HintRecover(a)
	c.c.PreprocessQueryLHE()
}

// EncryptQuery encrypts a d-dim int8 vector.
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

// DecryptScores returns the N signed scores.
func (c *ScoreClient) DecryptScores(a *pir.Answer[Elem], n uint64) []int64 {
	out := c.c.RecoverLHE(a)
	scores := make([]int64, n)
	for i := uint64(0); i < n; i++ {
		scores[i] = DecodeSigned(uint64(out.Get(i, 0)))
	}
	return scores
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
