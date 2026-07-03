// Package registry defines the 4-tier model pool with failover chains.
//
// Tier mapping:
//
//	model::light    → IBM Granite   (granite4.1:3b)
//	model::medium   → Meta LLaMA   (llama3.2:latest)
//	model::balanced → Google Gemma  (gemma3:4b)
//	model::heavy    → Mistral AI    (mistral-small3.2:latest)
package registry

import "math"

// FailoverEntry is one step in a model's failover chain.
type FailoverEntry struct {
	Label  string
	Reason string
}

// ModelSpec describes a single model in the registry.
type ModelSpec struct {
	Label         string
	Tier          int
	Provider      string
	CostPer1k     float64
	MaxTokens     int
	CapableTypes  map[string]bool
	QualityScore  func(complexity float64) float64
	FailoverChain []FailoverEntry
}

// QualityAt returns quality clamped to [0,1].
func (m *ModelSpec) QualityAt(complexity float64) float64 {
	q := m.QualityScore(complexity)
	if q < 0 {
		return 0
	}
	if q > 1 {
		return 1
	}
	return q
}

// Models is the global registry (light < medium < balanced < heavy).
var Models = []*ModelSpec{
	{
		Label:     "model::light",
		Tier:      1,
		Provider:  "IBM Granite",
		CostPer1k: 0.05,
		MaxTokens: 16_384,
		CapableTypes: map[string]bool{
			"documentation": true,
			"summarisation": true,
			"qa_simple":     true,
		},
		QualityScore: func(c float64) float64 { return math.Max(0, 1.0-c*1.4) },
		FailoverChain: []FailoverEntry{
			{Label: "model::medium", Reason: "light_degraded"},
			{Label: "model::balanced", Reason: "light_circuit_open"},
		},
	},
	{
		Label:     "model::medium",
		Tier:      2,
		Provider:  "Meta LLaMA",
		CostPer1k: 0.28,
		MaxTokens: 32_768,
		CapableTypes: map[string]bool{
			"code_generation": true,
			"documentation":   true,
			"qa_simple":       true,
			"summarisation":   true,
		},
		QualityScore: func(c float64) float64 { return 0.72 + c*0.08 },
		FailoverChain: []FailoverEntry{
			{Label: "model::balanced", Reason: "medium_degraded"},
			{Label: "model::heavy", Reason: "medium_circuit_open"},
		},
	},
	{
		Label:     "model::balanced",
		Tier:      3,
		Provider:  "Google Gemma",
		CostPer1k: 0.35,
		MaxTokens: 32_768,
		CapableTypes: map[string]bool{
			"code_generation": true,
			"code_review":     true,
			"documentation":   true,
			"qa_simple":       true,
			"summarisation":   true,
			"reasoning":       true,
		},
		QualityScore: func(c float64) float64 { return 0.78 + c*0.12 },
		FailoverChain: []FailoverEntry{
			{Label: "model::heavy", Reason: "balanced_degraded"},
			{Label: "model::medium", Reason: "balanced_circuit_open"},
		},
	},
	{
		Label:     "model::heavy",
		Tier:      4,
		Provider:  "Mistral AI",
		CostPer1k: 1.00,
		MaxTokens: 128_000,
		CapableTypes: map[string]bool{
			"code_generation": true,
			"code_review":     true,
			"reasoning":       true,
			"documentation":   true,
			"summarisation":   true,
			"qa_simple":       true,
		},
		QualityScore: func(c float64) float64 { return 0.90 + c*0.10 },
		FailoverChain: []FailoverEntry{
			{Label: "model::balanced", Reason: "heavy_degraded"},
			{Label: "model::medium", Reason: "heavy_circuit_open"},
		},
	},
}

// ByLabel returns the ModelSpec with the given label, or nil.
func ByLabel(label string) *ModelSpec {
	for _, m := range Models {
		if m.Label == label {
			return m
		}
	}
	return nil
}

// TaskFailoverPriority maps task_type → preferred model label order.
var TaskFailoverPriority = map[string][]string{
	"documentation":   {"model::light", "model::medium", "model::balanced", "model::heavy"},
	"summarisation":   {"model::light", "model::medium", "model::balanced", "model::heavy"},
	"qa_simple":       {"model::light", "model::medium", "model::balanced", "model::heavy"},
	"code_generation": {"model::medium", "model::balanced", "model::heavy", "model::light"},
	"code_review":     {"model::heavy", "model::balanced", "model::medium", "model::light"},
	"reasoning":       {"model::balanced", "model::heavy", "model::medium", "model::light"},
}
