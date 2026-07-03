// Package failover implements per-model circuit breakers and failover resolution.
//
// Circuit states:
//
//	CLOSED    — normal; calls pass through
//	OPEN      — blocked after consecutive failures; calls bounce
//	HALF_OPEN — cooldown elapsed; limited probe calls allowed
package failover

import (
	"os"
	"strconv"
	"sync"
	"time"

	"github.com/routing-v5/internal/registry"
)

// CircuitState represents the state of a circuit breaker.
type CircuitState string

const (
	Closed   CircuitState = "CLOSED"
	Open     CircuitState = "OPEN"
	HalfOpen CircuitState = "HALF_OPEN"
)

// defaults (overridable via env).
var (
	failureThreshold = envInt("CIRCUIT_FAILURE_THRESHOLD", 3)
	cooldownSeconds  = envInt("CIRCUIT_COOLDOWN_SECONDS", 30)
	halfOpenProbes   = envInt("CIRCUIT_HALF_OPEN_PROBES", 2)
	healthEMAAlpha   = 0.20
)

func envInt(key string, def int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}

// FailoverEvent is emitted whenever a failover substitution occurs.
type FailoverEvent struct {
	PrimaryLabel  string
	FallbackLabel string
	Reason        string
	Timestamp     time.Time
}

// circuitBreakerState tracks state for one model.
type circuitBreakerState struct {
	label            string
	state            CircuitState
	consecutiveFails int
	lastFailureTs    time.Time
	halfOpenProbesCt int
	healthScore      float64
	mu               sync.Mutex
}

func newCB(label string) *circuitBreakerState {
	return &circuitBreakerState{label: label, state: Closed, healthScore: 1.0}
}

func (cb *circuitBreakerState) RecordSuccess() {
	cb.mu.Lock()
	defer cb.mu.Unlock()
	cb.updateHealth(1.0)
	switch cb.state {
	case HalfOpen:
		cb.halfOpenProbesCt++
		if cb.halfOpenProbesCt >= halfOpenProbes {
			cb.close()
		}
	case Closed:
		cb.consecutiveFails = 0
	}
}

func (cb *circuitBreakerState) RecordFailure() {
	cb.mu.Lock()
	defer cb.mu.Unlock()
	cb.updateHealth(0.0)
	cb.consecutiveFails++
	cb.lastFailureTs = time.Now()
	if cb.state == Closed || cb.state == HalfOpen {
		if cb.consecutiveFails >= failureThreshold {
			cb.openCircuit()
		}
	}
	if cb.state == HalfOpen {
		cb.openCircuit()
	}
}

func (cb *circuitBreakerState) IsCallable() bool {
	cb.mu.Lock()
	defer cb.mu.Unlock()
	switch cb.state {
	case Closed:
		return true
	case Open:
		if time.Since(cb.lastFailureTs) >= time.Duration(cooldownSeconds)*time.Second {
			cb.halfOpen()
			return true
		}
		return false
	default: // HalfOpen
		return true
	}
}

func (cb *circuitBreakerState) Snapshot() map[string]interface{} {
	cb.mu.Lock()
	defer cb.mu.Unlock()
	return map[string]interface{}{
		"label":             cb.label,
		"state":             string(cb.state),
		"consecutive_fails": cb.consecutiveFails,
		"health_score":      round3(cb.healthScore),
	}
}

func (cb *circuitBreakerState) HealthScore() float64 {
	cb.mu.Lock()
	defer cb.mu.Unlock()
	return cb.healthScore
}

func (cb *circuitBreakerState) updateHealth(outcome float64) {
	cb.healthScore = healthEMAAlpha*outcome + (1-healthEMAAlpha)*cb.healthScore
}

func (cb *circuitBreakerState) openCircuit() {
	cb.state = Open
	cb.halfOpenProbesCt = 0
}

func (cb *circuitBreakerState) halfOpen() {
	cb.state = HalfOpen
	cb.halfOpenProbesCt = 0
}

func (cb *circuitBreakerState) close() {
	cb.state = Closed
	cb.consecutiveFails = 0
	cb.halfOpenProbesCt = 0
}

// Manager is the global failover manager.
type Manager struct {
	circuits map[string]*circuitBreakerState
	events   []FailoverEvent
	mu       sync.Mutex
}

// New creates a Manager pre-populated with circuits for every model in the registry.
func New() *Manager {
	m := &Manager{circuits: make(map[string]*circuitBreakerState)}
	for _, mod := range registry.Models {
		m.circuits[mod.Label] = newCB(mod.Label)
	}
	return m
}

func (m *Manager) RecordSuccess(label string) {
	if cb := m.circuits[label]; cb != nil {
		cb.RecordSuccess()
	}
}

func (m *Manager) RecordFailure(label string) {
	if cb := m.circuits[label]; cb != nil {
		cb.RecordFailure()
	}
}

func (m *Manager) IsCallable(label string) bool {
	cb := m.circuits[label]
	if cb == nil {
		return true
	}
	return cb.IsCallable()
}

// Resolve returns the model to actually use and an optional FailoverEvent.
// If the primary's circuit is callable it is returned directly; otherwise the
// failover chain is walked and as a last resort the healthiest model wins.
func (m *Manager) Resolve(primary *registry.ModelSpec, taskType string) (*registry.ModelSpec, *FailoverEvent) {
	if m.IsCallable(primary.Label) {
		return primary, nil
	}
	for _, entry := range primary.FailoverChain {
		fb := registry.ByLabel(entry.Label)
		if fb != nil && m.IsCallable(entry.Label) {
			ev := &FailoverEvent{
				PrimaryLabel:  primary.Label,
				FallbackLabel: entry.Label,
				Reason:        entry.Reason,
				Timestamp:     time.Now(),
			}
			m.mu.Lock()
			m.events = append(m.events, *ev)
			m.mu.Unlock()
			return fb, ev
		}
	}
	// Last resort: best health score
	best := registry.Models[0]
	for _, mod := range registry.Models[1:] {
		if m.circuits[mod.Label].HealthScore() > m.circuits[best.Label].HealthScore() {
			best = mod
		}
	}
	ev := &FailoverEvent{
		PrimaryLabel:  primary.Label,
		FallbackLabel: best.Label,
		Reason:        "all_chains_exhausted",
		Timestamp:     time.Now(),
	}
	m.mu.Lock()
	m.events = append(m.events, *ev)
	m.mu.Unlock()
	return best, ev
}

// HealthSnapshot returns a snapshot of all circuit states.
func (m *Manager) HealthSnapshot() []map[string]interface{} {
	out := make([]map[string]interface{}, 0, len(m.circuits))
	for _, cb := range m.circuits {
		out = append(out, cb.Snapshot())
	}
	return out
}

// RecentEvents returns up to limit recent failover events.
func (m *Manager) RecentEvents(limit int) []map[string]interface{} {
	m.mu.Lock()
	defer m.mu.Unlock()
	tail := m.events
	if len(tail) > limit {
		tail = tail[len(tail)-limit:]
	}
	out := make([]map[string]interface{}, len(tail))
	for i, e := range tail {
		out[i] = map[string]interface{}{
			"primary":   e.PrimaryLabel,
			"fallback":  e.FallbackLabel,
			"reason":    e.Reason,
			"timestamp": e.Timestamp.Unix(),
		}
	}
	return out
}

func round3(f float64) float64 {
	return float64(int(f*1000+0.5)) / 1000
}
