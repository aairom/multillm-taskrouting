// Package telemetry implements a live ring-buffer telemetry engine with
// dynamic threshold and cost-weight optimisation.
//
// For each (model_label, task_type) pair a fixed-size ring buffer of recent
// call records is maintained. After every ingest the tuner recomputes:
//
//   - p50 / p95 latency percentiles
//   - EMA quality score
//   - dynamic quality threshold
//   - dynamic cost weight
package telemetry

import (
	"math"
	"os"
	"sort"
	"strconv"
	"sync"
	"time"
)

// tunable defaults (env-overridable).
var (
	windowSize      = envInt("TELEMETRY_WINDOW", 50)
	emaAlpha        = envFloat("EMA_ALPHA", 0.15)
	baseThreshold   = 0.72
	minThreshold    = 0.40
	maxThreshold    = 0.95
	baseCostWeight  = 0.40
	minCostWeight   = 0.10
	maxCostWeight   = 0.70
	targetLatencyMs = 3_000.0
)

func envInt(key string, def int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}

func envFloat(key string, def float64) float64 {
	if v := os.Getenv(key); v != "" {
		if f, err := strconv.ParseFloat(v, 64); err == nil {
			return f
		}
	}
	return def
}

// Record is a single telemetry observation.
type Record struct {
	ModelLabel  string
	TaskType    string
	LatencyMs   int
	OutTokens   int
	CostUnits   float64
	QualityEval float64
	Success     bool
	Timestamp   float64
}

// DynamicParams holds the current computed parameters for one (model, task) pair.
type DynamicParams struct {
	ModelLabel       string  `json:"model_label"`
	TaskType         string  `json:"task_type"`
	QualityThreshold float64 `json:"quality_threshold"`
	CostWeight       float64 `json:"cost_weight"`
	QualityEMA       float64 `json:"quality_ema"`
	P50LatencyMs     float64 `json:"p50_latency_ms"`
	P95LatencyMs     float64 `json:"p95_latency_ms"`
	SuccessRate      float64 `json:"success_rate"`
	SampleCount      int     `json:"sample_count"`
	LastUpdated      float64 `json:"last_updated"`
}

type ringBuffer struct {
	data []Record
	pos  int
	full bool
	cap  int
}

func newRing(cap int) *ringBuffer { return &ringBuffer{data: make([]Record, cap), cap: cap} }

func (r *ringBuffer) push(rec Record) {
	r.data[r.pos] = rec
	r.pos = (r.pos + 1) % r.cap
	if r.pos == 0 {
		r.full = true
	}
}

func (r *ringBuffer) slice() []Record {
	if r.full {
		s := make([]Record, r.cap)
		copy(s, r.data[r.pos:])
		copy(s[r.cap-r.pos:], r.data[:r.pos])
		return s
	}
	return r.data[:r.pos]
}

// Engine is the singleton telemetry engine.
type Engine struct {
	buffers         map[[2]string]*ringBuffer
	params          map[[2]string]*DynamicParams
	modelQualityEMA map[string]float64
	mu              sync.Mutex
	eventCh         chan<- map[string]interface{}
}

// New creates a new Engine.
func New() *Engine {
	return &Engine{
		buffers:         make(map[[2]string]*ringBuffer),
		params:          make(map[[2]string]*DynamicParams),
		modelQualityEMA: make(map[string]float64),
	}
}

// SetEventChannel sets the channel used to broadcast threshold_update events.
func (e *Engine) SetEventChannel(ch chan<- map[string]interface{}) {
	e.mu.Lock()
	e.eventCh = ch
	e.mu.Unlock()
}

// Record ingests an observation and returns updated DynamicParams.
func (e *Engine) Record(rec Record) DynamicParams {
	if rec.Timestamp == 0 {
		rec.Timestamp = float64(time.Now().UnixNano()) / 1e9
	}
	key := [2]string{rec.ModelLabel, rec.TaskType}
	e.mu.Lock()
	if e.buffers[key] == nil {
		e.buffers[key] = newRing(windowSize)
	}
	e.buffers[key].push(rec)
	dp := e.recompute(key)
	e.params[key] = &dp

	// Update global model EMA
	prev, ok := e.modelQualityEMA[rec.ModelLabel]
	if !ok {
		prev = rec.QualityEval
	}
	e.modelQualityEMA[rec.ModelLabel] = emaAlpha*rec.QualityEval + (1-emaAlpha)*prev
	e.mu.Unlock()

	// Non-blocking push
	if e.eventCh != nil {
		select {
		case e.eventCh <- map[string]interface{}{"type": "threshold_update", "params": dp}:
		default:
		}
	}
	return dp
}

// GetThreshold returns the current quality threshold for (model, task_type).
func (e *Engine) GetThreshold(modelLabel, taskType string) float64 {
	key := [2]string{modelLabel, taskType}
	e.mu.Lock()
	defer e.mu.Unlock()
	if p := e.params[key]; p != nil {
		return p.QualityThreshold
	}
	return baseThreshold
}

// GetCostWeight returns the current cost weight for (model, task_type).
func (e *Engine) GetCostWeight(modelLabel, taskType string) float64 {
	key := [2]string{modelLabel, taskType}
	e.mu.Lock()
	defer e.mu.Unlock()
	if p := e.params[key]; p != nil {
		return p.CostWeight
	}
	return baseCostWeight
}

// GetAllParams returns all current DynamicParams.
func (e *Engine) GetAllParams() []DynamicParams {
	e.mu.Lock()
	defer e.mu.Unlock()
	out := make([]DynamicParams, 0, len(e.params))
	for _, p := range e.params {
		out = append(out, *p)
	}
	return out
}

// GetModelQualityEMA returns the global model-level quality EMA.
func (e *Engine) GetModelQualityEMA(label string) float64 {
	e.mu.Lock()
	defer e.mu.Unlock()
	if v, ok := e.modelQualityEMA[label]; ok {
		return v
	}
	return 1.0
}

// RecentRecords returns up to limit of the most recent records across all buffers.
func (e *Engine) RecentRecords(limit int) []Record {
	e.mu.Lock()
	var all []Record
	for _, buf := range e.buffers {
		all = append(all, buf.slice()...)
	}
	e.mu.Unlock()
	sort.Slice(all, func(i, j int) bool { return all[i].Timestamp < all[j].Timestamp })
	if len(all) > limit {
		all = all[len(all)-limit:]
	}
	return all
}

func (e *Engine) recompute(key [2]string) DynamicParams {
	modelLabel, taskType := key[0], key[1]
	buf := e.buffers[key].slice()
	n := len(buf)

	// Quality EMA
	qEMA := buf[0].QualityEval
	for _, r := range buf[1:] {
		qEMA = emaAlpha*r.QualityEval + (1-emaAlpha)*qEMA
	}

	// Latency percentiles
	lats := make([]int, n)
	for i, r := range buf {
		lats[i] = r.LatencyMs
	}
	sort.Ints(lats)
	p50 := float64(lats[int(float64(n)*0.50)])
	p95Idx := int(float64(n) * 0.95)
	if p95Idx >= n {
		p95Idx = n - 1
	}
	p95 := float64(lats[p95Idx])

	// Success rate
	successes := 0
	for _, r := range buf {
		if r.Success {
			successes++
		}
	}
	successRate := 1.0
	if n > 0 {
		successRate = float64(successes) / float64(n)
	}

	// Dynamic quality threshold
	delta := qEMA - baseThreshold
	newThr := baseThreshold + 0.5*delta
	newThr = math.Max(minThreshold, math.Min(maxThreshold, newThr))

	// Dynamic cost weight
	latPressure := p95 / targetLatencyMs
	costW := baseCostWeight * (1.0 - math.Min(0.5, latPressure*0.3))
	costW = math.Max(minCostWeight, math.Min(maxCostWeight, costW))

	return DynamicParams{
		ModelLabel:       modelLabel,
		TaskType:         taskType,
		QualityThreshold: r4(newThr),
		CostWeight:       r4(costW),
		QualityEMA:       r4(qEMA),
		P50LatencyMs:     p50,
		P95LatencyMs:     p95,
		SuccessRate:      r3(successRate),
		SampleCount:      n,
		LastUpdated:      float64(time.Now().UnixNano()) / 1e9,
	}
}

func r3(f float64) float64 { return math.Round(f*1000) / 1000 }
func r4(f float64) float64 { return math.Round(f*10000) / 10000 }
