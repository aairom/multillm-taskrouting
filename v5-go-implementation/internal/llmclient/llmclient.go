// Package llmclient provides a failover-aware HTTP client for Ollama via the
// OpenAI-compatible chat completions API.
package llmclient

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"net/http"
	"os"
	"time"

	"github.com/routing-v5/internal/failover"
)

// env-configurable
var (
	ollamaBase = func() string {
		if v := os.Getenv("OLLAMA_BASE_URL"); v != "" {
			return v
		}
		return "http://localhost:11434"
	}()

	ollamaTimeout = func() time.Duration {
		if v := os.Getenv("OLLAMA_TIMEOUT"); v != "" {
			var n int
			fmt.Sscanf(v, "%d", &n)
			return time.Duration(n) * time.Second
		}
		return 120 * time.Second
	}()
)

// TierModels maps the tier label to the primary Ollama model name.
var TierModels = map[string]string{
	"model::light":    getenv("LLM_LIGHT", "granite4.1:3b"),
	"model::medium":   getenv("LLM_MEDIUM", "llama3.2:latest"),
	"model::balanced": getenv("LLM_BALANCED", "gemma3:4b"),
	"model::heavy":    getenv("LLM_HEAVY", "mistral-small3.2:latest"),
}

// fallbackModels maps tier labels to secondary Ollama model names.
var fallbackModels = map[string]string{
	"model::light":    getenv("LLM_LIGHT_FALLBACK", "llama3.2:latest"),
	"model::medium":   getenv("LLM_MEDIUM_FALLBACK", "gemma3:4b"),
	"model::balanced": getenv("LLM_BALANCED_FALLBACK", "llama3.2:latest"),
	"model::heavy":    getenv("LLM_HEAVY_FALLBACK", "gemma3:4b"),
}

func getenv(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

// openAIRequest is the JSON body sent to the completions endpoint.
type openAIRequest struct {
	Model       string           `json:"model"`
	Messages    []openAIMessage  `json:"messages"`
	MaxTokens   int              `json:"max_tokens"`
	Temperature float64          `json:"temperature"`
	Stream      bool             `json:"stream"`
}

type openAIMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type openAIResponse struct {
	Choices []struct {
		Message struct {
			Content string `json:"content"`
		} `json:"message"`
	} `json:"choices"`
	Usage struct {
		CompletionTokens int `json:"completion_tokens"`
	} `json:"usage"`
}

// CallResult holds the result of a single model call.
type CallResult struct {
	Text      string
	LatencySec float64
	Tokens    int
}

// CallModel calls the Ollama model identified by tierLabel.
// It reports success/failure to the FailoverManager and retries once on
// transient errors before returning an error string.
func CallModel(
	ctx context.Context,
	fm *failover.Manager,
	tierLabel string,
	prompt string,
	maxTokens int,
) CallResult {
	ollamaModel := TierModels[tierLabel]
	start := time.Now()

	result, err := doCall(ctx, ollamaModel, prompt, maxTokens)
	if err != nil {
		// One retry with fallback model
		fb := fallbackModels[tierLabel]
		if fb != "" && fb != ollamaModel {
			result, err = doCall(ctx, fb, prompt, maxTokens)
		}
	}

	latency := time.Since(start).Seconds()
	if err != nil {
		fm.RecordFailure(tierLabel)
		return CallResult{
			Text:       fmt.Sprintf("[LiteLLM ERROR — %s: %v]", ollamaModel, err),
			LatencySec: latency,
			Tokens:     0,
		}
	}
	fm.RecordSuccess(tierLabel)
	tokens := result.Usage.CompletionTokens
	text := ""
	if len(result.Choices) > 0 {
		text = result.Choices[0].Message.Content
	}
	if tokens == 0 {
		tokens = int(math.Max(1, float64(len(text)/4)))
	}
	return CallResult{Text: text, LatencySec: latency, Tokens: tokens}
}

func doCall(ctx context.Context, model, prompt string, maxTokens int) (*openAIResponse, error) {
	body := openAIRequest{
		Model:       model,
		Messages:    []openAIMessage{{Role: "user", Content: prompt}},
		MaxTokens:   maxTokens,
		Temperature: 0.3,
		Stream:      false,
	}
	data, err := json.Marshal(body)
	if err != nil {
		return nil, err
	}
	reqCtx, cancel := context.WithTimeout(ctx, ollamaTimeout)
	defer cancel()

	req, err := http.NewRequestWithContext(reqCtx, http.MethodPost,
		ollamaBase+"/v1/chat/completions", bytes.NewReader(data))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		b, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(b))
	}
	var result openAIResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, err
	}
	return &result, nil
}
