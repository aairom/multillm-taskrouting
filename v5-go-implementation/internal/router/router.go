// Package router implements the core routing logic.
// Selection rules:
//  1. Security overrides → always tier-4 (then failover if circuit open)
//  2. Filter by capability + context window
//  3. Filter by blended quality threshold
//  4. Best utility wins
//  5. Safety net: highest quality if no candidate passes threshold
//  6. Resolve failover if the chosen model's circuit is not callable
package router

import (
	"math"

	"github.com/routing-v5/internal/classifier"
	"github.com/routing-v5/internal/failover"
	"github.com/routing-v5/internal/registry"
	"github.com/routing-v5/internal/telemetry"
)

// Static fallback parameters (used before telemetry has data).
const (
	BaseQualityThreshold = 0.72
	BaseCostWeight       = 0.40
)

// StaticTaskThresholds are the per-task baseline quality thresholds.
var StaticTaskThresholds = map[string]float64{
	"documentation":   0.60,
	"summarisation":   0.55,
	"qa_simple":       0.55,
	"code_generation": 0.72,
	"code_review":     0.85,
	"reasoning":       0.80,
}

// securityOverrides always uses tier-4.
var securityOverrides = map[string]bool{"code_review": true}

// Utility computes U = β·Q − α·C for a model+profile pair.
func Utility(eng *telemetry.Engine, model *registry.ModelSpec, profile classifier.TaskProfile) float64 {
	alpha := eng.GetCostWeight(model.Label, string(profile.TaskType))
	beta := 1.0 - alpha
	q := model.QualityAt(profile.Complexity)
	return beta*q - alpha*model.CostPer1k
}

// effectiveThreshold blends static + dynamic thresholds.
func effectiveThreshold(eng *telemetry.Engine, taskType string) float64 {
	static := StaticTaskThresholds[taskType]
	if static == 0 {
		static = BaseQualityThreshold
	}
	dyn := eng.GetThreshold("", taskType)
	return math.Round((static+dyn)/2*10000) / 10000
}

// DispatchResult bundles the routing outcome for one sub-task.
type DispatchResult struct {
	Profile       classifier.TaskProfile
	Model         *registry.ModelSpec
	FailoverEvent *failover.FailoverEvent
}

// Route selects the best model for a single TaskProfile.
func Route(
	eng *telemetry.Engine,
	fm *failover.Manager,
	profile classifier.TaskProfile,
) (*registry.ModelSpec, *failover.FailoverEvent) {
	ttype := string(profile.TaskType)

	if securityOverrides[ttype] {
		// Always use tier-4 for security tasks
		var tier4 *registry.ModelSpec
		for _, m := range registry.Models {
			if m.Tier == 4 {
				tier4 = m
				break
			}
		}
		return fm.Resolve(tier4, ttype)
	}

	threshold := effectiveThreshold(eng, ttype)

	var candidates []*registry.ModelSpec
	for _, m := range registry.Models {
		if !m.CapableTypes[ttype] {
			continue
		}
		if m.MaxTokens < profile.TokenEstimate {
			continue
		}
		if m.QualityAt(profile.Complexity) >= threshold {
			candidates = append(candidates, m)
		}
	}

	if len(candidates) == 0 {
		// Safety net: all models sorted by quality
		candidates = make([]*registry.ModelSpec, len(registry.Models))
		copy(candidates, registry.Models)
	}

	// Best utility wins
	primary := candidates[0]
	for _, m := range candidates[1:] {
		if Utility(eng, m, profile) > Utility(eng, primary, profile) {
			primary = m
		}
	}

	return fm.Resolve(primary, ttype)
}

// Dispatch routes each profile independently.
func Dispatch(
	eng *telemetry.Engine,
	fm *failover.Manager,
	profiles []classifier.TaskProfile,
) map[string]DispatchResult {
	result := make(map[string]DispatchResult, len(profiles))
	typeCounts := make(map[string]int)

	for _, profile := range profiles {
		key := string(profile.TaskType)
		count := typeCounts[key]
		typeCounts[key]++
		uniqueKey := key
		if count > 0 {
			uniqueKey = key + "_" + string(rune('0'+count))
		}
		model, fev := Route(eng, fm, profile)
		result[uniqueKey] = DispatchResult{
			Profile:       profile,
			Model:         model,
			FailoverEvent: fev,
		}
	}
	return result
}
