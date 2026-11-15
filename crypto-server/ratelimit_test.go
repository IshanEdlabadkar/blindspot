package main

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestRateLimitPenaltyBox(t *testing.T) {
	cfg := rateConfig{questionPerMin: 60, questionBurst: 5, downloadPerMin: 2, downloadBurst: 2,
		strikes: 3, strikeWindow: time.Minute, penalty: 5 * time.Minute, idle: 10 * time.Minute}
	l := newLimiter(cfg)
	now := time.Unix(1_800_000_000, 0)
	l.now = func() time.Time { return now }

	for i := 0; i < 5; i++ { // the burst
		if w := l.allow("1.2.3.4", "/v1/score"); w != 0 {
			t.Fatalf("request %d refused", i)
		}
	}
	if l.allow("1.2.3.4", "/v1/score") == 0 {
		t.Fatal("6th request in the same instant should be refused")
	}
	if l.allow("5.6.7.8", "/v1/score") != 0 {
		t.Fatal("another client must not be affected")
	}
	if l.allow("1.2.3.4", "/v1/fetch_store") != 0 { // separate download budget
		t.Fatal("download budget is separate from question traffic")
	}
	now = now.Add(time.Second) // refills 1 question token per second at 60/min
	if l.allow("1.2.3.4", "/v1/score") != 0 {
		t.Fatal("bucket should refill")
	}
	l.allow("1.2.3.4", "/v1/score")
	if w := l.allow("1.2.3.4", "/v1/score"); w != cfg.penalty { // 3rd refusal within a minute
		t.Fatalf("expected penalty box, got wait %v", w)
	}
	now = now.Add(time.Minute) // buckets full again, but still boxed
	if l.allow("1.2.3.4", "/v1/manifest") == 0 {
		t.Fatal("penalty box must refuse every request")
	}
	now = now.Add(cfg.penalty)
	if l.allow("1.2.3.4", "/v1/manifest") != 0 {
		t.Fatal("released after the penalty")
	}
	now = now.Add(time.Hour)
	l.forgetIdle()
	if len(l.clients) != 0 {
		t.Fatalf("idle clients should be forgotten, %d left", len(l.clients))
	}
}

func TestRateLimitHTTPAndClientAddr(t *testing.T) {
	cfg := rateConfig{questionPerMin: 60, questionBurst: 1, downloadPerMin: 1, downloadBurst: 1,
		strikes: 100, strikeWindow: time.Minute, penalty: time.Minute, maxInFlight: 4, idle: time.Minute}
	h := newLimiter(cfg).wrap(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.Write([]byte("ok")) }))
	do := func(hdr, val string) *httptest.ResponseRecorder {
		r := httptest.NewRequest("GET", "/v1/manifest", nil)
		r.RemoteAddr = "10.0.0.1:5000"
		if hdr != "" {
			r.Header.Set(hdr, val)
		}
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		return w
	}
	if do("", "").Code != 200 {
		t.Fatal("first request allowed")
	}
	if w := do("", ""); w.Code != 429 || w.Header().Get("Retry-After") == "" {
		t.Fatalf("second request: %d, Retry-After %q", w.Code, w.Header().Get("Retry-After"))
	}
	if do("CF-Connecting-IP", "203.0.113.9").Code != 200 { // a different client behind the proxy
		t.Fatal("CF-Connecting-IP identifies the client")
	}
	if do("X-Forwarded-For", "198.51.100.7, 10.1.1.1").Code != 200 {
		t.Fatal("left-most X-Forwarded-For identifies the client")
	}
}
