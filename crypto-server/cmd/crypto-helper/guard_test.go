package main

import (
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func TestGuard(t *testing.T) {
	file := filepath.Join(t.TempDir(), "sub", "helper-token")
	tok, err := newSessionToken(file)
	if err != nil {
		t.Fatal(err)
	}
	if st, _ := os.Stat(file); st.Mode().Perm() != 0o600 {
		t.Fatalf("token file mode %v, want 0600", st.Mode().Perm())
	}
	ok := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.Write([]byte("ok")) })
	h := guard(ok, tok)
	try := func(path, host string, hdr map[string]string) int {
		r := httptest.NewRequest("POST", path, nil)
		r.Host = host
		for k, v := range hdr {
			r.Header.Set(k, v)
		}
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		return w.Code
	}
	good := map[string]string{"X-Blind-RAG-Token": tok}
	cases := []struct {
		name, path, host string
		hdr              map[string]string
		want             int
	}{
		{"our client", "/encrypt", "127.0.0.1:8090", good, 200},
		{"localhost name", "/encrypt", "localhost:8090", good, 200},
		{"health needs no token", "/health", "127.0.0.1:8090", nil, 200},
		{"no token", "/encrypt", "127.0.0.1:8090", nil, 401},
		{"wrong token", "/encrypt", "127.0.0.1:8090", map[string]string{"X-Blind-RAG-Token": "x"}, 401},
		{"DNS rebinding host", "/encrypt", "evil.example:8090", good, 403},
		{"web page (Origin)", "/encrypt", "127.0.0.1:8090", map[string]string{"X-Blind-RAG-Token": tok, "Origin": "https://evil.example"}, 403},
		{"web page (Sec-Fetch-Site)", "/health", "127.0.0.1:8090", map[string]string{"Sec-Fetch-Site": "cross-site"}, 403},
	}
	for _, c := range cases {
		if got := try(c.path, c.host, c.hdr); got != c.want {
			t.Errorf("%s: got %d, want %d", c.name, got, c.want)
		}
	}
}
