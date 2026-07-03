// Package orchestrator ties together splitting → routing → parallel execution
// → telemetry recording → feedback persistence → WebSocket broadcast.
//
// Every completed sub-task emits an event to the eventCh channel so the
// front-end receives real-time updates.
package orchestrator

import (
	"context"
	"fmt"
	"math"
	"strings"
	"sync"
	"time"
	"unicode"

	"github.com/routing-v5/internal/classifier"
	"github.com/routing-v5/internal/failover"
	"github.com/routing-v5/internal/feedback"
	"github.com/routing-v5/internal/llmclient"
	"github.com/routing-v5/internal/registry"
	"github.com/routing-v5/internal/router"
	"github.com/routing-v5/internal/telemetry"
)

// SubTaskResult holds the outcome of one routed sub-task.
type SubTaskResult struct {
	Profile        classifier.TaskProfile
	Model          *registry.ModelSpec
	Response       string
	LatencyMs      int
	OutTokens      int
	UtilityScore   float64
	QualityScore   float64
	Threshold      float64
	OllamaModel    string
	CostUnits      float64
	FailoverUsed   bool
	FailoverFrom   string
	FailoverReason string
	DynThreshold   float64
	DynCostWeight  float64
}

// OrchestratorResult holds the full result of one /api/chat request.
type OrchestratorResult struct {
	Prompt     string
	SubResults []SubTaskResult
	Merged     string
	TotalMs    int
}

func (r *OrchestratorResult) RoutingTable() []map[string]interface{} {
	out := make([]map[string]interface{}, len(r.SubResults))
	for i, s := range r.SubResults {
		out[i] = map[string]interface{}{
			"task_type":        string(s.Profile.TaskType),
			"complexity":       s.Profile.Complexity,
			"tier":             s.Profile.Tier.String(),
			"model":            s.Model.Label,
			"provider":         s.Model.Provider,
			"ollama_model":     s.OllamaModel,
			"utility":          r4(s.UtilityScore),
			"quality":          r4(s.QualityScore),
			"threshold":        s.Threshold,
			"latency_ms":       s.LatencyMs,
			"out_tokens":       s.OutTokens,
			"cost_units":       s.CostUnits,
			"failover_used":    s.FailoverUsed,
			"failover_from":    s.FailoverFrom,
			"failover_reason":  s.FailoverReason,
			"dyn_threshold":    s.DynThreshold,
			"dyn_cost_weight":  s.DynCostWeight,
			"response":         s.Response,
		}
	}
	return out
}

func (r *OrchestratorResult) ToUIPayload() map[string]interface{} {
	return map[string]interface{}{
		"prompt":    r.Prompt,
		"total_ms":  r.TotalMs,
		"merged":    r.Merged,
		"sub_tasks": r.RoutingTable(),
	}
}

// Orchestrator is the central coordinator.
type Orchestrator struct {
	store   *feedback.Store
	eng     *telemetry.Engine
	fm      *failover.Manager
	eventCh chan<- map[string]interface{}
}

// New creates an Orchestrator.
func New(
	store *feedback.Store,
	eng *telemetry.Engine,
	fm *failover.Manager,
) *Orchestrator {
	return &Orchestrator{store: store, eng: eng, fm: fm}
}

// SetEventChannel registers the channel for WebSocket broadcast events.
func (o *Orchestrator) SetEventChannel(ch chan<- map[string]interface{}) {
	o.eventCh = ch
	o.eng.SetEventChannel(ch)
}

// Handle processes a prompt end-to-end and returns the full result.
func (o *Orchestrator) Handle(ctx context.Context, prompt string) (*OrchestratorResult, error) {
	tStart := time.Now()
	profiles := classifier.SplitAndClassify(prompt)
	routing := router.Dispatch(o.eng, o.fm, profiles)

	// Broadcast routing plan
	planTasks := make([]map[string]interface{}, 0, len(routing))
	for _, dr := range routing {
		entry := map[string]interface{}{
			"task_type":  string(dr.Profile.TaskType),
			"complexity": dr.Profile.Complexity,
			"tier":       dr.Profile.Tier.String(),
			"model":      dr.Model.Label,
			"provider":   dr.Model.Provider,
		}
		if dr.FailoverEvent != nil {
			entry["failover"] = dr.FailoverEvent.FallbackLabel
		}
		planTasks = append(planTasks, entry)
	}
	o.emit(map[string]interface{}{
		"type":      "routing_plan",
		"prompt":    prompt,
		"sub_tasks": planTasks,
	})

	// Execute all sub-tasks in parallel
	type indexedResult struct {
		key string
		res SubTaskResult
		err error
	}
	ch := make(chan indexedResult, len(routing))
	var wg sync.WaitGroup

	for key, dr := range routing {
		wg.Add(1)
		go func(key string, dr router.DispatchResult) {
			defer wg.Done()
			res, err := o.execSubTask(ctx, key, dr)
			ch <- indexedResult{key: key, res: res, err: err}
		}(key, dr)
	}

	wg.Wait()
	close(ch)

	var subResults []SubTaskResult
	for ir := range ch {
		if ir.err == nil {
			subResults = append(subResults, ir.res)
		}
	}

	merged := merge(subResults)
	totalMs := int(time.Since(tStart).Milliseconds())

	o.emit(map[string]interface{}{
		"type":     "request_complete",
		"total_ms": totalMs,
		"merged":   merged,
	})

	return &OrchestratorResult{
		Prompt:     prompt,
		SubResults: subResults,
		Merged:     merged,
		TotalMs:    totalMs,
	}, nil
}

func (o *Orchestrator) execSubTask(
	ctx context.Context,
	key string,
	dr router.DispatchResult,
) (SubTaskResult, error) {
	profile := dr.Profile
	model := dr.Model
	fev := dr.FailoverEvent

	failoverLabel := ""
	if fev != nil {
		failoverLabel = fev.FallbackLabel
	}

	o.emit(map[string]interface{}{
		"type":      "subtask_start",
		"key":       key,
		"task_type": string(profile.TaskType),
		"model":     model.Label,
		"provider":  model.Provider,
		"failover":  failoverLabel,
	})

	maxTokens := int(math.Min(2048, float64(profile.TokenEstimate*3)))
	cr := llmclient.CallModel(ctx, o.fm, model.Label, profile.RawText, maxTokens)

	latMs := int(cr.LatencySec * 1000)
	success := !strings.HasPrefix(cr.Text, "[LiteLLM ERROR")

	quality := feedback.HeuristicQuality(latMs, cr.Tokens)
	telRec := telemetry.Record{
		ModelLabel:  model.Label,
		TaskType:    string(profile.TaskType),
		LatencyMs:   latMs,
		OutTokens:   cr.Tokens,
		CostUnits:   r6(model.CostPer1k * float64(cr.Tokens) / 1000),
		QualityEval: quality,
		Success:     success,
	}
	dynParams := o.eng.Record(telRec)

	u := router.Utility(o.eng, model, profile)
	q := model.QualityAt(profile.Complexity)
	thr := router.StaticTaskThresholds[string(profile.TaskType)]
	if thr == 0 {
		thr = router.BaseQualityThreshold
	}
	ollamaName := llmclient.TierModels[model.Label]
	if ollamaName == "" {
		ollamaName = model.Label
	}
	cost := r6(model.CostPer1k * float64(cr.Tokens) / 1000)

	failoverFrom := ""
	failoverReason := ""
	if fev != nil {
		failoverFrom = fev.PrimaryLabel
		failoverReason = fev.Reason
	}

	o.store.Record(
		string(profile.TaskType),
		profile.Complexity,
		model.Tier,
		model.Label,
		latMs,
		cr.Tokens,
		model.CostPer1k,
		len(profile.RawText),
		fev != nil,
		failoverFrom,
		failoverReason,
	)

	res := SubTaskResult{
		Profile:        profile,
		Model:          model,
		Response:       cr.Text,
		LatencyMs:      latMs,
		OutTokens:      cr.Tokens,
		UtilityScore:   r4(u),
		QualityScore:   r4(q),
		Threshold:      thr,
		OllamaModel:    ollamaName,
		CostUnits:      cost,
		FailoverUsed:   fev != nil,
		FailoverFrom:   failoverFrom,
		FailoverReason: failoverReason,
		DynThreshold:   dynParams.QualityThreshold,
		DynCostWeight:  dynParams.CostWeight,
	}

	health := o.fm.HealthSnapshot()
	o.emit(map[string]interface{}{
		"type":            "subtask_complete",
		"key":             key,
		"task_type":       string(profile.TaskType),
		"model":           model.Label,
		"provider":        model.Provider,
		"tier":            model.Tier,
		"latency_ms":      latMs,
		"out_tokens":      cr.Tokens,
		"cost_units":      cost,
		"quality":         r4(q),
		"utility":         r4(u),
		"threshold":       thr,
		"dyn_threshold":   dynParams.QualityThreshold,
		"dyn_cost_weight": dynParams.CostWeight,
		"success":         success,
		"failover_used":   fev != nil,
		"failover_from":   failoverFrom,
		"failover_reason": failoverReason,
		"health":          health,
	})

	return res, nil
}

func (o *Orchestrator) emit(payload map[string]interface{}) {
	if o.eventCh != nil {
		select {
		case o.eventCh <- payload:
		default:
		}
	}
}

func merge(results []SubTaskResult) string {
	sections := make([]string, 0, len(results))
	for _, r := range results {
		label := strings.ReplaceAll(string(r.Profile.TaskType), "_", " ")
		// title-case without deprecated strings.Title
		words := strings.Fields(label)
		for i, w := range words {
			if len(w) > 0 {
				runes := []rune(w)
				runes[0] = unicode.ToTitle(runes[0])
				words[i] = string(runes)
			}
		}
		label = strings.Join(words, " ")
		foTag := ""
		if r.FailoverUsed {
			foTag = fmt.Sprintf(" ⚡ failover from %s", r.FailoverFrom)
		}
		header := fmt.Sprintf("## %s  _(via %s [%s]%s, %d ms)_",
			label, r.Model.Label, r.Model.Provider, foTag, r.LatencyMs)
		sections = append(sections, header+"\n\n"+strings.TrimSpace(r.Response))
	}
	return strings.Join(sections, "\n\n---\n\n")
}

func r4(f float64) float64  { return math.Round(f*10000) / 10000 }
func r6(f float64) float64  { return math.Round(f*1e6) / 1e6 }
