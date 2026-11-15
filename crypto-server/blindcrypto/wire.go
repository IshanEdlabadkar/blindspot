package blindcrypto

// Wire format for /v1/score. All integers little-endian.
//
// The corpus version travels in the X-Corpus-Version header (contracts.py).
//
// Score request:
//   u32 count, then count x (u32 len, bytes)   -- token (underhood HintQuery)
//   u32 d, then d x u64                         -- encrypted query (pir.Query)
//
// Score response:
//   u64 matrix_rows
//   u32 rows, then rows x (u32 cols, cols x (u32 len, bytes))  -- token answer
//   u32 n, then n x u64                                         -- encrypted scores

import (
	"bytes"
	"encoding/binary"
	"errors"
	"io"

	"github.com/ahenzinger/underhood/underhood"
	"github.com/henrycg/simplepir/matrix"
	"github.com/henrycg/simplepir/pir"
)

var le = binary.LittleEndian

// Generous caps so a bad request can't make the server allocate unbounded memory.
const (
	maxBlobs   = 1 << 16
	maxBlobLen = 1 << 20
	maxVecLen  = 1 << 22
	maxVersion = 256
)

type ScoreRequest struct {
	Token underhood.HintQuery
	Query *pir.Query[Elem]
}

type ScoreResponse struct {
	TokenAnswer *underhood.HintAnswer
	Scores      *pir.Answer[Elem]
}

func putU32(w *bytes.Buffer, v uint32) { var b [4]byte; le.PutUint32(b[:], v); w.Write(b[:]) }
func putU64(w *bytes.Buffer, v uint64) { var b [8]byte; le.PutUint64(b[:], v); w.Write(b[:]) }

func putBlob(w *bytes.Buffer, b []byte) { putU32(w, uint32(len(b))); w.Write(b) }

func putVec(w *bytes.Buffer, m *matrix.Matrix[Elem]) {
	data := m.Data()
	putU32(w, uint32(len(data)))
	buf := make([]byte, 8*len(data))
	for i, v := range data {
		le.PutUint64(buf[8*i:], uint64(v))
	}
	w.Write(buf)
}

func readU32(r io.Reader) (uint32, error) {
	var b [4]byte
	if _, err := io.ReadFull(r, b[:]); err != nil {
		return 0, err
	}
	return le.Uint32(b[:]), nil
}

func readU64(r io.Reader) (uint64, error) {
	var b [8]byte
	if _, err := io.ReadFull(r, b[:]); err != nil {
		return 0, err
	}
	return le.Uint64(b[:]), nil
}

func readBlob(r io.Reader) ([]byte, error) {
	n, err := readU32(r)
	if err != nil {
		return nil, err
	}
	if n > maxBlobLen {
		return nil, errors.New("blob too large")
	}
	b := make([]byte, n)
	_, err = io.ReadFull(r, b)
	return b, err
}

func readVec(r io.Reader) (*matrix.Matrix[Elem], error) {
	n, err := readU32(r)
	if err != nil {
		return nil, err
	}
	if n > maxVecLen {
		return nil, errors.New("vector too large")
	}
	buf := make([]byte, 8*int(n))
	if _, err := io.ReadFull(r, buf); err != nil {
		return nil, err
	}
	m := matrix.Zeros[Elem](uint64(n), 1)
	for i := uint64(0); i < uint64(n); i++ {
		m.Set(i, 0, Elem(le.Uint64(buf[8*i:])))
	}
	return m, nil
}

func (q *ScoreRequest) MarshalBinary() []byte {
	return append(MarshalToken(q.Token), MarshalQuery(q.Query)...)
}

// MarshalToken encodes the token part of a score request. It does not depend
// on the question, so the helper can encode it ahead of time.
func MarshalToken(tok underhood.HintQuery) []byte {
	var w bytes.Buffer
	putU32(&w, uint32(len(tok)))
	for _, c := range tok {
		putBlob(&w, c)
	}
	return w.Bytes()
}

// MarshalQuery encodes the encrypted-query part; append it after MarshalToken.
func MarshalQuery(q *pir.Query[Elem]) []byte {
	var w bytes.Buffer
	putVec(&w, q.Query)
	return w.Bytes()
}

func UnmarshalScoreRequest(r io.Reader) (*ScoreRequest, error) {
	n, err := readU32(r)
	if err != nil {
		return nil, err
	}
	if n > maxBlobs {
		return nil, errors.New("too many token blobs")
	}
	tok := make(underhood.HintQuery, n)
	for i := range tok {
		if tok[i], err = readBlob(r); err != nil {
			return nil, err
		}
	}
	q, err := readVec(r)
	if err != nil {
		return nil, err
	}
	return &ScoreRequest{Token: tok, Query: &pir.Query[Elem]{Query: q}}, nil
}

func (s *ScoreResponse) MarshalBinary() []byte {
	var w bytes.Buffer
	putU64(&w, s.TokenAnswer.MatrixRows)
	putU32(&w, uint32(len(s.TokenAnswer.HintCts)))
	for _, row := range s.TokenAnswer.HintCts {
		putU32(&w, uint32(len(row)))
		for _, c := range row {
			putBlob(&w, c)
		}
	}
	putVec(&w, s.Scores.Answer)
	return w.Bytes()
}

func UnmarshalScoreResponse(r io.Reader) (*ScoreResponse, error) {
	rows, err := readU64(r)
	if err != nil {
		return nil, err
	}
	nr, err := readU32(r)
	if err != nil {
		return nil, err
	}
	if nr > maxBlobs {
		return nil, errors.New("too many rows")
	}
	cts := make([][]underhood.CipherBlob, nr)
	for i := range cts {
		nc, err := readU32(r)
		if err != nil {
			return nil, err
		}
		if nc > maxBlobs {
			return nil, errors.New("too many cols")
		}
		cts[i] = make([]underhood.CipherBlob, nc)
		for j := range cts[i] {
			if cts[i][j], err = readBlob(r); err != nil {
				return nil, err
			}
		}
	}
	a, err := readVec(r)
	if err != nil {
		return nil, err
	}
	return &ScoreResponse{
		TokenAnswer: &underhood.HintAnswer{MatrixRows: rows, HintCts: cts},
		Scores:      &pir.Answer[Elem]{Answer: a},
	}, nil
}

// Fetch wire format (POST /v1/fetch): request = one encrypted selector
// (u32 len, u64s); response = the encrypted column (u32 len, u64s).

type pirQuery struct{ m *matrix.Matrix[Elem] }

func (p pirQuery) q() *pir.Query[Elem] { return &pir.Query[Elem]{Query: p.m} }

type pirAnswer struct{ m *matrix.Matrix[Elem] }

func (p pirAnswer) a() *pir.Answer[Elem] { return &pir.Answer[Elem]{Answer: p.m} }

func UnmarshalFetchRequest(r io.Reader) (*pir.Query[Elem], error) {
	m, err := readVec(r)
	if err != nil {
		return nil, err
	}
	return &pir.Query[Elem]{Query: m}, nil
}

func MarshalAnswer(a *pir.Answer[Elem]) []byte {
	var w bytes.Buffer
	putVec(&w, a.Answer)
	return w.Bytes()
}

func UnmarshalAnswer(r io.Reader) (*pir.Answer[Elem], error) {
	m, err := readVec(r)
	if err != nil {
		return nil, err
	}
	return &pir.Answer[Elem]{Answer: m}, nil
}

// Batched fetch (POST /v1/fetch_batch): request = u32 count, then count
// selectors (u32 len, u64s each); response = u32 count, then count columns.
// Each selector is encrypted under its own fresh secret.

const MaxFetchBatch = 64

func MarshalFetchBatch(qs []*pir.Query[Elem]) []byte {
	var w bytes.Buffer
	putU32(&w, uint32(len(qs)))
	for _, q := range qs {
		putVec(&w, q.Query)
	}
	return w.Bytes()
}

func UnmarshalFetchBatch(r io.Reader) ([]*pir.Query[Elem], error) {
	n, err := readU32(r)
	if err != nil {
		return nil, err
	}
	if n == 0 || n > MaxFetchBatch {
		return nil, errors.New("batch size out of range")
	}
	qs := make([]*pir.Query[Elem], n)
	for i := range qs {
		m, err := readVec(r)
		if err != nil {
			return nil, err
		}
		qs[i] = &pir.Query[Elem]{Query: m}
	}
	return qs, nil
}

func MarshalAnswers(as []*pir.Answer[Elem]) []byte {
	var w bytes.Buffer
	putU32(&w, uint32(len(as)))
	for _, a := range as {
		putVec(&w, a.Answer)
	}
	return w.Bytes()
}

func UnmarshalAnswers(r io.Reader) ([]*pir.Answer[Elem], error) {
	n, err := readU32(r)
	if err != nil {
		return nil, err
	}
	if n > MaxFetchBatch {
		return nil, errors.New("batch size out of range")
	}
	as := make([]*pir.Answer[Elem], n)
	for i := range as {
		m, err := readVec(r)
		if err != nil {
			return nil, err
		}
		as[i] = &pir.Answer[Elem]{Answer: m}
	}
	return as, nil
}
