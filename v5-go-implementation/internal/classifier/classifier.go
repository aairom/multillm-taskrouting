// Package classifier classifies a text prompt into a TaskProfile.
package classifier

import (
	"math"
	"regexp"
	"strings"
)

// TaskType enumerates the supported task categories.
type TaskType string

const (
	Documentation  TaskType = "documentation"
	CodeGeneration TaskType = "code_generation"
	CodeReview     TaskType = "code_review"
	Reasoning      TaskType = "reasoning"
	QASimple       TaskType = "qa_simple"
	Summarisation  TaskType = "summarisation"
)

// ComplexityTier maps a score range to a named tier.
type ComplexityTier int

const (
	Low    ComplexityTier = 1 // 0.00 – 0.34
	Medium ComplexityTier = 2 // 0.35 – 0.64
	High   ComplexityTier = 3 // 0.65 – 1.00
)

func (c ComplexityTier) String() string {
	switch c {
	case Low:
		return "LOW"
	case Medium:
		return "MEDIUM"
	default:
		return "HIGH"
	}
}

// TaskProfile is the classification result for a single prompt clause.
type TaskProfile struct {
	RawText       string
	TaskType      TaskType
	Complexity    float64
	Tier          ComplexityTier
	TokenEstimate int
}

// signal holds keywords and a base complexity score.
type signal struct {
	keywords  []string
	baseScore float64
}

var signals = map[TaskType]signal{
	Documentation:  {[]string{"write the api", "api reference", "write docs", "write documentation", "document", "readme", "docstring", "comment", "explain", "describe"}, 0.20},
	CodeGeneration: {[]string{"implement", "create function", "write code", "build", "develop", "middleware", "endpoint", "class", "module"}, 0.55},
	CodeReview:     {[]string{"review", "audit", "security", "vulnerability", "diff", "check", "analyse code", "analyze code"}, 0.60},
	Reasoning:      {[]string{"architecture", "design", "trade-off", "compare", "evaluate", "pros and cons", "should i", "best approach"}, 0.80},
	QASimple:       {[]string{"what is", "how does", "define", "tell me", "when was"}, 0.10},
	Summarisation:  {[]string{"summarise", "summarize", "tldr", "shorten", "brief", "condense", "overview"}, 0.15},
}

// phraseOverrides are evaluated before keyword scanning.
var phraseOverrides = []struct {
	phrase   string
	taskType TaskType
}{
	{"api reference", Documentation},
	{"write the api", Documentation},
	{"write docs", Documentation},
	{"write documentation", Documentation},
	{"code review", CodeReview},
	{"security audit", CodeReview},
}

var depthMarkers = []string{
	"step 1", "first,", "then,", "finally,",
	"however,", "alternatively,", "trade-off",
	"on the other hand", "in addition", "furthermore",
}

func tokenEstimate(text string) int {
	n := len(text) / 4
	if n < 1 {
		return 1
	}
	return n
}

func depthPenalty(lower string) float64 {
	hits := 0
	for _, m := range depthMarkers {
		if strings.Contains(lower, m) {
			hits++
		}
	}
	penalty := float64(hits) * 0.04
	if penalty > 0.20 {
		return 0.20
	}
	return penalty
}

// Classify classifies a single text into a TaskProfile.
func Classify(text string) TaskProfile {
	lower := strings.ToLower(text)
	bestType := QASimple
	baseScore := 0.10

	// Phrase overrides take priority
	for _, o := range phraseOverrides {
		if strings.Contains(lower, o.phrase) {
			bestType = o.taskType
			baseScore = signals[o.taskType].baseScore
			goto scored
		}
	}
	for ttype, sig := range signals {
		for _, kw := range sig.keywords {
			if strings.Contains(lower, kw) {
				if sig.baseScore > baseScore {
					bestType = ttype
					baseScore = sig.baseScore
				}
				break
			}
		}
	}

scored:
	tokens := tokenEstimate(text)
	tokenFactor := math.Min(0.15, math.Log10(math.Max(1, float64(tokens)))*0.05)
	depth := depthPenalty(lower)
	finalScore := math.Min(1.0, baseScore+tokenFactor+depth)

	tier := Low
	if finalScore >= 0.65 {
		tier = High
	} else if finalScore >= 0.35 {
		tier = Medium
	}

	return TaskProfile{
		RawText:       text,
		TaskType:      bestType,
		Complexity:    math.Round(finalScore*1000) / 1000,
		Tier:          tier,
		TokenEstimate: tokens,
	}
}

// splitPattern splits compound prompts on conjunctions.
var splitPattern = regexp.MustCompile(`(?i)\s*\b(and also|and then|additionally|plus|as well as|AND|also)\b\s*`)

// SplitAndClassify splits a compound prompt and classifies each clause.
func SplitAndClassify(prompt string) []TaskProfile {
	raw := splitPattern.Split(prompt, -1)
	var clauses []string
	for _, c := range raw {
		c = strings.TrimSpace(c)
		if len(c) > 8 && !splitPattern.MatchString(c) {
			clauses = append(clauses, c)
		}
	}
	if len(clauses) == 0 {
		clauses = []string{strings.TrimSpace(prompt)}
	}
	profiles := make([]TaskProfile, len(clauses))
	for i, c := range clauses {
		profiles[i] = Classify(c)
	}
	return profiles
}
