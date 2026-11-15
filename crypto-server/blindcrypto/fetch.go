package blindcrypto

// Real PIR fetch (SimplePIR, hint downloaded once). Optional: trivial PIR
// (download the whole store) is cheaper at small N and stays the default.
//
// Layout: each 2,048-byte record is 1,024 elements of Z_(2^16) (2 bytes each),
// stacked in one column. With M = min(N, 8192) columns, the matrix is
// L = ceil(N/M) * 1024 rows. A query selects one column; the answer is that
// whole column (L values), from which the client reads its record's 1,024 rows.
//
// The hint (L x 2048) is public and sent with its low 32 bits dropped, like
// the scoring hint: extra error <= 2048 * 2^31 = 2^42, Delta/2 = 2^47.

import (
	"errors"
	"fmt"
	"sync"

	"github.com/henrycg/simplepir/lwe"
	"github.com/henrycg/simplepir/matrix"
	"github.com/henrycg/simplepir/pir"
	"github.com/henrycg/simplepir/rand"
)

const (
	FetchP       = uint64(1 << 16)
	fetchMaxCols = uint64(1 << 13)
)

func fetchShape(n, recLen uint64) (*pir.DBInfo, error) {
	if recLen%2 != 0 {
		return nil, errors.New("record length must be even")
	}
	m := n
	if m > fetchMaxCols {
		m = fetchMaxCols
	}
	params := lwe.NewParamsFixedP(LogQ, m, FetchP)
	if params == nil {
		return nil, fmt.Errorf("no LWE params for fetch with %d columns", m)
	}
	info := pir.NewDBInfoFixedParams(n, recLen*8, params, true)
	if info.Ne != recLen/2 {
		return nil, fmt.Errorf("unexpected %d elements per record", info.Ne)
	}
	return info, nil
}

// NewFetchDB lays out the fetch store (n records of recLen bytes) for PIR.
func NewFetchDB(store []byte, n, recLen uint64) (*pir.Database[Elem], error) {
	if uint64(len(store)) != n*recLen {
		return nil, fmt.Errorf("store is %d bytes, want %d", len(store), n*recLen)
	}
	info, err := fetchShape(n, recLen)
	if err != nil {
		return nil, err
	}
	db := &pir.Database[Elem]{Info: info, Data: matrix.Zeros[Elem](info.L, info.M)}
	ne := info.Ne
	for i := uint64(0); i < n; i++ {
		rec := store[i*recLen : (i+1)*recLen]
		row0, col := (i/info.M)*ne, i%info.M
		for j := uint64(0); j < ne; j++ {
			db.Data.Set(row0+j, col, Elem(uint64(rec[2*j])|uint64(rec[2*j+1])<<8))
		}
	}
	return db, nil
}

// FetchDBInfo rebuilds the public shape on the client, including the
// compression fields the server sets when it squishes its matrix.
func FetchDBInfo(n, recLen uint64) (*pir.DBInfo, error) {
	info, err := fetchShape(n, recLen)
	if err != nil {
		return nil, err
	}
	db := &pir.Database[Elem]{Info: info, Data: matrix.Zeros[Elem](info.L, info.M)}
	db.Squish()
	return db.Info, nil
}

type FetchServer struct {
	Info *pir.DBInfo
	s    *pir.Server[Elem]
}

func NewFetchServer(db *pir.Database[Elem], seed *rand.PRGKey) *FetchServer {
	s := pir.NewServerSeed(db, seed)
	return &FetchServer{Info: s.DBInfo(), s: s}
}

func (f *FetchServer) Hint() *matrix.Matrix[Elem]                  { return f.s.Hint() }
func (f *FetchServer) Answer(q *pir.Query[Elem]) *pir.Answer[Elem] { return f.s.Answer(q) }

// FetchClient is the device side. Safe for concurrent use; every Query uses a fresh secret.
type FetchClient struct {
	mu     sync.Mutex
	c      *pir.Client[Elem]
	info   *pir.DBInfo
	n      uint64
	recLen uint64
}

func NewFetchClient(seed *rand.PRGKey, info *pir.DBInfo, hint *matrix.Matrix[Elem], n, recLen uint64) *FetchClient {
	return &FetchClient{c: pir.NewClient[Elem](hint, seed, info), info: info, n: n, recLen: recLen}
}

// FetchKey is one fetch's secret state. Use once.
type FetchKey struct {
	fc    *FetchClient
	s     *pir.Secret[Elem]
	index uint64
}

// Query makes a fresh secret and the encrypted selector for record index.
func (fc *FetchClient) Query(index uint64) (*FetchKey, *pir.Query[Elem], error) {
	if index >= fc.n {
		return nil, nil, fmt.Errorf("index %d out of range (n=%d)", index, fc.n)
	}
	fc.mu.Lock()
	defer fc.mu.Unlock()
	s := fc.c.PreprocessQuery()
	q := fc.c.QueryPreprocessed(index, s)
	// QueryPreprocessed adds to the secret's query in place; copy for the wire.
	return &FetchKey{fc: fc, s: s, index: index}, &pir.Query[Elem]{Query: q.Query.Copy()}, nil
}

// Decrypt recovers the record bytes from the server's answer.
func (k *FetchKey) Decrypt(a *pir.Answer[Elem]) ([]byte, error) {
	info := k.fc.info
	if a.Answer.Rows() < info.L {
		return nil, errors.New("answer too short")
	}
	interm := k.s.Interm() // H * s, from Query
	if interm == nil || interm.Rows() != a.Answer.Rows() {
		return nil, errors.New("answer does not match this key")
	}
	ans := a.Answer.Copy()
	ans.Sub(interm)
	params := info.Params
	out := make([]byte, k.fc.recLen)
	row0 := (k.index / info.M) * info.Ne
	for j := uint64(0); j < info.Ne; j++ {
		v := params.Round(uint64(ans.Get(row0+j, 0)))
		out[2*j], out[2*j+1] = byte(v), byte(v>>8)
	}
	return out, nil
}
