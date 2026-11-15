package main

// Rate limiting with a penalty box (the idea from the MadHacks 2026 TDS workshop's haproxy demo),
// built into the server because on Render there is no separate load balancer we control.
//
//   - On for public servers ($PORT set, as on Render), off locally; BLIND_RAG_RATE_LIMIT overrides.
//   - Two budgets per client: the one-time downloads (hints, fetch store; megabytes each) and
//     question traffic (manifest, score, fetch). Token buckets: a steady rate plus a burst.
//   - A client that keeps going over a budget goes into the penalty box: every request from it is
//     refused for a while (429 with Retry-After).
//   - A global cap on requests in flight protects the small CPU; beyond it, 503 "busy".
//
// Privacy: clients are told apart by a keyed hash of their address (random key per process run),
// kept in memory only and forgotten after a few idle minutes. Nothing here is logged; the request
// log keeps its four fields. Every request of a kind is treated alike, so a refusal says nothing
// about what was asked.

import (
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"net"
	"net/http"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"
)

type rateConfig struct {
	questionPerMin, questionBurst float64       // manifest, score, fetch, fetch_batch, server_log
	downloadPerMin, downloadBurst float64       // score_hint, fetch_hint, fetch_store
	strikes                       int           // times over a budget within strikeWindow -> penalty
	strikeWindow, penalty         time.Duration //
	maxInFlight                   int           // 0 = no cap
	idle                          time.Duration // forget a client after this long without requests
}

func rateConfigFromEnv() (rateConfig, bool) {
	f := func(name string, def float64) float64 {
		if v, err := strconv.ParseFloat(os.Getenv(name), 64); err == nil {
			return v
		}
		return def
	}
	c := rateConfig{
		questionPerMin: f("BLIND_RAG_RATE_QUESTION", 1200), questionBurst: f("BLIND_RAG_BURST_QUESTION", 200),
		downloadPerMin: f("BLIND_RAG_RATE_DOWNLOAD", 20), downloadBurst: f("BLIND_RAG_BURST_DOWNLOAD", 12),
		strikes: int(f("BLIND_RAG_PENALTY_STRIKES", 20)), strikeWindow: time.Minute,
		penalty:     envDuration("BLIND_RAG_PENALTY", 5*time.Minute),
		maxInFlight: int(f("BLIND_RAG_MAX_INFLIGHT", 16)), idle: 10 * time.Minute,
	}
	// On by default for public servers (Render sets $PORT); off for a local one, where the only client
	// is this laptop and `make bench` runs as fast as it can. BLIND_RAG_RATE_LIMIT=1/0 overrides.
	return c, envBool("BLIND_RAG_RATE_LIMIT", os.Getenv("PORT") != "")
}

type bucket struct {
	tokens float64
	last   time.Time
}

type client struct {
	question, download bucket
	strikes            int
	strikeStart        time.Time
	boxedUntil         time.Time
	seen               time.Time
}

type limiter struct {
	cfg      rateConfig
	key      []byte
	mu       sync.Mutex
	clients  map[[16]byte]*client
	inflight chan struct{}
	now      func() time.Time
}

func newLimiter(cfg rateConfig) *limiter {
	k := make([]byte, 32)
	if _, err := rand.Read(k); err != nil {
		panic(err)
	}
	l := &limiter{cfg: cfg, key: k, clients: map[[16]byte]*client{}, now: time.Now}
	if cfg.maxInFlight > 0 {
		l.inflight = make(chan struct{}, cfg.maxInFlight)
	}
	go func() {
		for range time.Tick(time.Minute) {
			l.forgetIdle()
		}
	}()
	return l
}

// clientAddr: the connecting address, or the one the platform's proxy reports. On Render (behind
// Cloudflare) that's CF-Connecting-IP; otherwise the left-most X-Forwarded-For entry, which Render
// documents as the client. A client can forge those headers if it reaches the server directly, so
// this is a speed bump, not identity; the in-flight cap still protects the server either way.
func clientAddr(r *http.Request) string {
	if v := strings.TrimSpace(r.Header.Get("CF-Connecting-IP")); v != "" {
		return v
	}
	if v := r.Header.Get("X-Forwarded-For"); v != "" {
		return strings.TrimSpace(strings.Split(v, ",")[0])
	}
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}

func (l *limiter) id(addr string) [16]byte {
	m := hmac.New(sha256.New, l.key)
	m.Write([]byte(addr))
	var out [16]byte
	copy(out[:], m.Sum(nil))
	return out
}

func isDownload(path string) bool {
	return path == "/v1/score_hint" || path == "/v1/fetch_hint" || path == "/v1/fetch_store"
}

// take spends one token from b; false if it's empty.
func take(b *bucket, now time.Time, perMin, burst float64) bool {
	if b.last.IsZero() {
		b.tokens, b.last = burst, now
	}
	b.tokens += now.Sub(b.last).Minutes() * perMin
	if b.tokens > burst {
		b.tokens = burst
	}
	b.last = now
	if b.tokens < 1 {
		return false
	}
	b.tokens--
	return true
}

// allow decides one request: 0 if allowed, else how long the client should wait.
func (l *limiter) allow(addr, path string) time.Duration {
	now := l.now()
	l.mu.Lock()
	defer l.mu.Unlock()
	id := l.id(addr)
	c := l.clients[id]
	if c == nil {
		c = &client{}
		l.clients[id] = c
	}
	c.seen = now
	if now.Before(c.boxedUntil) {
		return c.boxedUntil.Sub(now)
	}
	ok := false
	if isDownload(path) {
		ok = take(&c.download, now, l.cfg.downloadPerMin, l.cfg.downloadBurst)
	} else {
		ok = take(&c.question, now, l.cfg.questionPerMin, l.cfg.questionBurst)
	}
	if ok {
		return 0
	}
	if now.Sub(c.strikeStart) > l.cfg.strikeWindow {
		c.strikes, c.strikeStart = 0, now
	}
	c.strikes++
	if l.cfg.strikes > 0 && c.strikes >= l.cfg.strikes {
		c.boxedUntil, c.strikes = now.Add(l.cfg.penalty), 0
		return l.cfg.penalty
	}
	return 2 * time.Second
}

func (l *limiter) forgetIdle() {
	now := l.now()
	l.mu.Lock()
	defer l.mu.Unlock()
	for id, c := range l.clients {
		if now.Sub(c.seen) > l.cfg.idle && now.After(c.boxedUntil) {
			delete(l.clients, id)
		}
	}
}

func (l *limiter) wrap(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if wait := l.allow(clientAddr(r), r.URL.Path); wait > 0 {
			w.Header().Set("Retry-After", strconv.Itoa(int(wait.Seconds()+0.999)))
			http.Error(w, "too many requests; slow down", http.StatusTooManyRequests)
			return
		}
		if l.inflight != nil {
			select {
			case l.inflight <- struct{}{}:
				defer func() { <-l.inflight }()
			case <-time.After(2 * time.Second):
				w.Header().Set("Retry-After", "2")
				http.Error(w, "server busy; retry shortly", http.StatusServiceUnavailable)
				return
			}
		}
		next.ServeHTTP(w, r)
	})
}
