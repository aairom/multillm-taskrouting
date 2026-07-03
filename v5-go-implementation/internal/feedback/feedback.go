// Package feedback implements an append-only JSONL routing record store
// with per-model analytics.
package feedback

import (
	"encoding/json"
	"math"
	"os"
	"path/filepath"
	"sync"
	"time"
)

// RoutingRecord is one persisted routing call.
type RoutingRecord struct {
	Timestamp      string  `json:"timestamp"`
	TaskType       string  `json:"task_type"`
	Complexity     float64 `json:"complexity"`
	Tier           int     `json:"tier"`
	ModelUsed      string  `json:"model_used"`
	LatencyMs      int     `json:"latency_ms"`
	CostUnits      float64 `json:"cost_units"`
	QualityEval    float64 `json:"quality_eval"`
	PromptLen      int     `json:"prompt_len"`
	FailoverUsed   bool    `json:"failover_used"`
	FailoverFrom   string  `json:"failover_from"`
	FailoverReason string  `json:"failover_reason"`
}

// Store is a thread-safe append-only JSONL record store.
type Store struct {
	path    string
	records []RoutingRecord
	mu      sync.Mutex
}

// New opens (or creates) the JSONL file at path.
func New(path string) (*Store, error) {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return nil, err
	}
	s := &Store{path: path}
	if err := s.load(); err != nil {
		return nil, err
	}
	return s, nil
}

func (s *Store) load() error {
	f, err := os.Open(s.path)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return err
	}
	defer f.Close()
	dec := json.NewDecoder(f)
	for dec.More() {
		var r RoutingRecord
		if err := dec.Decode(&r); err == nil {
			s.records = append(s.records, r)
		}
	}
	return nil
}

// Record appends a routing record to the JSONL file.
func (s *Store) Record(
	taskType string,
	complexity float64,
	tier int,
	modelUsed string,
	latencyMs int,
	outputTokens int,
	costPer1k float64,
	promptLen int,
	failoverUsed bool,
	failoverFrom string,
	failoverReason string,
) {
	qualityEval := HeuristicQuality(latencyMs, outputTokens)
	costUnits := costPer1k * float64(outputTokens) / 1000.0
	rec := RoutingRecord{
		Timestamp:      time.Now().UTC().Format(time.RFC3339Nano),
		TaskType:       taskType,
		Complexity:     math.Round(complexity*1000) / 1000,
		Tier:           tier,
		ModelUsed:      modelUsed,
		LatencyMs:      latencyMs,
		CostUnits:      math.Round(costUnits*1e6) / 1e6,
		QualityEval:    math.Round(qualityEval*1000) / 1000,
		PromptLen:      promptLen,
		FailoverUsed:   failoverUsed,
		FailoverFrom:   failoverFrom,
		FailoverReason: failoverReason,
	}
	s.mu.Lock()
	s.records = append(s.records, rec)
	s.mu.Unlock()

	// Append to file (best-effort — don't block callers on I/O error)
	if f, err := os.OpenFile(s.path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644); err == nil {
		enc := json.NewEncoder(f)
		_ = enc.Encode(rec)
		f.Close()
	}
}

// HeuristicQuality computes a quality proxy from latency and token count.
func HeuristicQuality(latencyMs int, outputTokens int) float64 {
	if outputTokens == 0 {
		return 0.0
	}
	latSec := math.Max(1, float64(latencyMs)/1000)
	tps := float64(outputTokens) / latSec
	q := 0.5 + tps/60
	if q > 1.0 {
		return 1.0
	}
	return q
}

// Summary returns aggregated analytics over all stored records.
func (s *Store) Summary() map[string]interface{} {
	s.mu.Lock()
	recs := make([]RoutingRecord, len(s.records))
	copy(recs, s.records)
	s.mu.Unlock()

	if len(recs) == 0 {
		return map[string]interface{}{"total_calls": 0}
	}

	var totalCost, totalQuality float64
	var totalLatency int
	failoverCount := 0
	byTier := map[int]int{}
	type modelAcc struct {
		calls, totalLatency int
		totalCost, totalQuality float64
	}
	byModel := map[string]*modelAcc{}

	for _, r := range recs {
		totalCost += r.CostUnits
		totalQuality += r.QualityEval
		totalLatency += r.LatencyMs
		if r.FailoverUsed {
			failoverCount++
		}
		byTier[r.Tier]++
		if byModel[r.ModelUsed] == nil {
			byModel[r.ModelUsed] = &modelAcc{}
		}
		acc := byModel[r.ModelUsed]
		acc.calls++
		acc.totalLatency += r.LatencyMs
		acc.totalCost += r.CostUnits
		acc.totalQuality += r.QualityEval
	}
	n := len(recs)

	modelStats := map[string]interface{}{}
	for label, acc := range byModel {
		c := acc.calls
		modelStats[label] = map[string]interface{}{
			"calls":       c,
			"avg_latency": acc.totalLatency / c,
			"avg_cost":    math.Round(acc.totalCost/float64(c)*1e6) / 1e6,
			"avg_quality": math.Round(acc.totalQuality/float64(c)*1000) / 1000,
		}
	}

	return map[string]interface{}{
		"total_calls":    n,
		"total_cost":     math.Round(totalCost*1e6) / 1e6,
		"avg_quality":    math.Round(totalQuality/float64(n)*1000) / 1000,
		"avg_latency_ms": totalLatency / n,
		"failover_count": failoverCount,
		"calls_by_tier":  byTier,
		"by_model":       modelStats,
	}
}
