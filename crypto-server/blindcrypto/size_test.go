package blindcrypto

import (
	mrand "math/rand"
	"testing"

	"github.com/ahenzinger/underhood/underhood"
	"github.com/henrycg/simplepir/rand"
)

// One round trip: hint query + encrypted query go together; client recovers after.
func TestOneRoundTripSizes(t *testing.T) {
	r := mrand.New(mrand.NewSource(3))
	n, d := uint64(5000), uint64(384)
	table := make([]int8, 0, n*d)
	for i := uint64(0); i < n; i++ {
		table = append(table, unitInt8(r, d)...)
	}
	db, _ := NewScoreDB(table, n, d)
	seed := rand.RandomPRGKey()
	srv := NewScoreServer(db, seed)
	defer srv.Free()
	c := underhood.NewClient[Elem](seed, db.Info)
	defer c.Free()

	hq := c.HintQuery()
	c.PreprocessQueryLHE()
	q := table[7*d : 8*d]
	cl := &ScoreClient{c: c, d: d}
	enc, _ := cl.EncryptQuery(q)

	ha := srv.HintAnswer(hq)
	ans := srv.Answer(enc)

	c.HintRecover(ha)
	got := cl.DecryptScores(ans, n)
	want := PlainScores(table, q, n, d)
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("row %d mismatch", i)
		}
	}
	hqBytes := 0
	for _, b := range *hq { hqBytes += len(b) }
	haBytes := 0
	for _, row := range ha.HintCts { for _, b := range row { haBytes += len(b) } }
	t.Logf("upload: hint query %d KB + query %d KB", hqBytes/1024, enc.Query.Rows()*8/1024)
	t.Logf("download: hint answer %d KB + answer %d KB", haBytes/1024, ans.Answer.Rows()*8/1024)
}
