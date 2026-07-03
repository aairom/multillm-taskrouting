// routing-v5 — Advanced Multi-LLM Router (Go edition)
//
// HTTP endpoints:
//
//	GET  /                    → chat + dashboard UI (static/index.html)
//	POST /api/chat            → route prompt, execute LLMs, return enriched JSON
//	GET  /api/models          → model registry (tiers, failover chains, health)
//	GET  /api/stats           → aggregated routing feedback statistics
//	GET  /api/health          → liveness + circuit-breaker snapshot
//	GET  /api/telemetry       → current dynamic parameters (all model × task pairs)
//	GET  /api/failover/events → recent failover event log
//
// WebSocket:
//
//	WS   /ws/telemetry        → real-time event stream
package main

import (
	"context"
	"encoding/json"
	"math"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/gorilla/websocket"
	"github.com/joho/godotenv"
	"github.com/labstack/echo/v4"
	"github.com/labstack/echo/v4/middleware"

	"github.com/routing-v5/internal/classifier"
	"github.com/routing-v5/internal/failover"
	"github.com/routing-v5/internal/feedback"
	"github.com/routing-v5/internal/llmclient"
	"github.com/routing-v5/internal/orchestrator"
	"github.com/routing-v5/internal/registry"
	"github.com/routing-v5/internal/router"
	"github.com/routing-v5/internal/telemetry"
)

// ── Application state ────────────────────────────────────────────────────────

var (
	fm        *failover.Manager
	eng       *telemetry.Engine
	store     *feedback.Store
	orch      *orchestrator.Orchestrator
	eventCh   chan map[string]interface{}

	wsUpgrader = websocket.Upgrader{
		CheckOrigin: func(r *http.Request) bool { return true },
	}
	wsClients  = make(map[*websocket.Conn]chan string)
	wsClientMu sync.Mutex
)

// ── Main ─────────────────────────────────────────────────────────────────────

func main() {
	_ = godotenv.Load()

	// Initialise shared components
	var err error
	store, err = feedback.New("output/feedback.jsonl")
	if err != nil {
		panic("feedback store: " + err.Error())
	}
	fm = failover.New()
	eng = telemetry.New()

	eventCh = make(chan map[string]interface{}, 500)

	orch = orchestrator.New(store, eng, fm)
	orch.SetEventChannel(eventCh)

	// Background broadcaster: eventCh → all WS clients
	go broadcastLoop()

	// Echo server
	e := echo.New()
	e.HideBanner = true
	e.Use(middleware.Recover())
	e.Use(middleware.CORSWithConfig(middleware.CORSConfig{
		AllowOrigins: []string{"*"},
		AllowMethods: []string{echo.GET, echo.POST},
	}))

	// Static UI
	e.Static("/", "static")
	e.GET("/", serveUI)

	// API
	e.POST("/api/chat", handleChat)
	e.GET("/api/models", handleModels)
	e.GET("/api/stats", handleStats)
	e.GET("/api/health", handleHealth)
	e.GET("/api/telemetry", handleTelemetry)
	e.GET("/api/failover/events", handleFailoverEvents)

	// WebSocket
	e.GET("/ws/telemetry", handleWS)

	port := getenv("PORT", "8080")
	e.Logger.Fatal(e.Start("0.0.0.0:" + port))
}

// ── Static UI ─────────────────────────────────────────────────────────────────

func serveUI(c echo.Context) error {
	data, err := os.ReadFile("static/index.html")
	if err != nil {
		return echo.ErrInternalServerError
	}
	return c.HTMLBlob(http.StatusOK, data)
}

// ── Request / response types ─────────────────────────────────────────────────

type chatRequest struct {
	Prompt string `json:"prompt"`
	DryRun bool   `json:"dry_run"`
}

// ── API handlers ─────────────────────────────────────────────────────────────

func handleChat(c echo.Context) error {
	var req chatRequest
	if err := c.Bind(&req); err != nil {
		return echo.NewHTTPError(http.StatusBadRequest, err.Error())
	}
	if strings.TrimSpace(req.Prompt) == "" {
		return echo.NewHTTPError(http.StatusBadRequest, "Prompt must not be empty.")
	}

	if req.DryRun {
		return handleDryRun(c, req.Prompt)
	}

	result, err := orch.Handle(context.Background(), req.Prompt)
	if err != nil {
		return echo.NewHTTPError(http.StatusInternalServerError, err.Error())
	}
	payload := result.ToUIPayload()
	payload["dry_run"] = false
	return c.JSON(http.StatusOK, payload)
}

func handleDryRun(c echo.Context, prompt string) error {
	profiles := classifier.SplitAndClassify(prompt)
	routing := router.Dispatch(eng, fm, profiles)

	subTasks := make([]map[string]interface{}, 0, len(routing))
	for _, dr := range routing {
		p := dr.Profile
		m := dr.Model
		fev := dr.FailoverEvent
		failoverUsed := fev != nil
		failoverFrom := ""
		failoverReason := ""
		if fev != nil {
			failoverFrom = fev.PrimaryLabel
			failoverReason = fev.Reason
		}
		ollamaName := llmclient.TierModels[m.Label]
		subTasks = append(subTasks, map[string]interface{}{
			"task_type":        string(p.TaskType),
			"complexity":       p.Complexity,
			"tier":             p.Tier.String(),
			"model":            m.Label,
			"provider":         m.Provider,
			"ollama_model":     ollamaName,
			"utility":          r4(router.Utility(eng, m, p)),
			"quality":          r4(m.QualityAt(p.Complexity)),
			"threshold":        staticThreshold(string(p.TaskType)),
			"dyn_threshold":    eng.GetThreshold(m.Label, string(p.TaskType)),
			"dyn_cost_weight":  eng.GetCostWeight(m.Label, string(p.TaskType)),
			"failover_used":    failoverUsed,
			"failover_from":    failoverFrom,
			"failover_reason":  failoverReason,
			"latency_ms":       nil,
			"out_tokens":       nil,
			"cost_units":       nil,
			"response":         nil,
		})
	}
	return c.JSON(http.StatusOK, map[string]interface{}{
		"prompt":    prompt,
		"total_ms":  nil,
		"merged":    nil,
		"sub_tasks": subTasks,
		"dry_run":   true,
	})
}

func handleModels(c echo.Context) error {
	healthMap := map[string]map[string]interface{}{}
	for _, h := range fm.HealthSnapshot() {
		label, _ := h["label"].(string)
		healthMap[label] = h
	}
	out := make([]map[string]interface{}, 0, len(registry.Models))
	for _, m := range registry.Models {
		fc := make([]map[string]interface{}, len(m.FailoverChain))
		for i, f := range m.FailoverChain {
			fc[i] = map[string]interface{}{"label": f.Label, "reason": f.Reason}
		}
		out = append(out, map[string]interface{}{
			"label":           m.Label,
			"tier":            m.Tier,
			"provider":        m.Provider,
			"ollama_model":    llmclient.TierModels[m.Label],
			"cost_per_1k":     m.CostPer1k,
			"max_tokens":      m.MaxTokens,
			"capable_types":   capableList(m),
			"quality_at_low":  r3(m.QualityAt(0.1)),
			"quality_at_high": r3(m.QualityAt(0.9)),
			"failover_chain":  fc,
			"health":          healthMap[m.Label],
		})
	}
	return c.JSON(http.StatusOK, out)
}

func handleStats(c echo.Context) error {
	return c.JSON(http.StatusOK, store.Summary())
}

func handleHealth(c echo.Context) error {
	return c.JSON(http.StatusOK, map[string]interface{}{
		"status":   "ok",
		"version":  "5.0.0",
		"gateway":  "Go HTTP Client → Ollama",
		"circuits": fm.HealthSnapshot(),
	})
}

func handleTelemetry(c echo.Context) error {
	recs := eng.RecentRecords(50)
	recsOut := make([]map[string]interface{}, len(recs))
	for i, r := range recs {
		recsOut[i] = map[string]interface{}{
			"model_label":  r.ModelLabel,
			"task_type":    r.TaskType,
			"latency_ms":   r.LatencyMs,
			"out_tokens":   r.OutTokens,
			"cost_units":   r.CostUnits,
			"quality_eval": r.QualityEval,
			"success":      r.Success,
			"timestamp":    r.Timestamp,
		}
	}
	return c.JSON(http.StatusOK, map[string]interface{}{
		"params":          eng.GetAllParams(),
		"recent_records":  recsOut,
		"failover_events": fm.RecentEvents(20),
	})
}

func handleFailoverEvents(c echo.Context) error {
	return c.JSON(http.StatusOK, fm.RecentEvents(50))
}

// ── WebSocket /ws/telemetry ───────────────────────────────────────────────────

func handleWS(c echo.Context) error {
	conn, err := wsUpgrader.Upgrade(c.Response(), c.Request(), nil)
	if err != nil {
		return err
	}
	defer conn.Close()

	clientCh := make(chan string, 200)
	wsClientMu.Lock()
	wsClients[conn] = clientCh
	wsClientMu.Unlock()

	defer func() {
		wsClientMu.Lock()
		delete(wsClients, conn)
		wsClientMu.Unlock()
	}()

	// Initial snapshot
	healthMap := map[string]map[string]interface{}{}
	for _, h := range fm.HealthSnapshot() {
		label, _ := h["label"].(string)
		healthMap[label] = h
	}
	modelsSummary := make([]map[string]interface{}, 0, len(registry.Models))
	for _, m := range registry.Models {
		fc := make([]string, len(m.FailoverChain))
		for i, f := range m.FailoverChain {
			fc[i] = f.Label
		}
		modelsSummary = append(modelsSummary, map[string]interface{}{
			"label":          m.Label,
			"tier":           m.Tier,
			"provider":       m.Provider,
			"cost":           m.CostPer1k,
			"health":         healthMap[m.Label],
			"failover_chain": fc,
		})
	}
	initMsg, _ := json.Marshal(map[string]interface{}{
		"type":           "init",
		"models":         modelsSummary,
		"dynamic_params": eng.GetAllParams(),
		"stats":          store.Summary(),
	})
	if err := conn.WriteMessage(websocket.TextMessage, initMsg); err != nil {
		return nil
	}

	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case msg, ok := <-clientCh:
			if !ok {
				return nil
			}
			if err := conn.WriteMessage(websocket.TextMessage, []byte(msg)); err != nil {
				return nil
			}
		case <-ticker.C:
			hb, _ := json.Marshal(map[string]interface{}{
				"type":       "heartbeat",
				"health":     fm.HealthSnapshot(),
				"stats":      store.Summary(),
				"dyn_params": eng.GetAllParams(),
			})
			if err := conn.WriteMessage(websocket.TextMessage, hb); err != nil {
				return nil
			}
		}
	}
}

// broadcastLoop drains eventCh and fans out to all connected WS clients.
func broadcastLoop() {
	for payload := range eventCh {
		data, err := json.Marshal(payload)
		if err != nil {
			continue
		}
		msg := string(data)
		wsClientMu.Lock()
		dead := []*websocket.Conn{}
		for conn, ch := range wsClients {
			select {
			case ch <- msg:
			default:
				dead = append(dead, conn)
			}
		}
		for _, conn := range dead {
			delete(wsClients, conn)
		}
		wsClientMu.Unlock()
	}
}

// ── Helpers ───────────────────────────────────────────────────────────────────

func capableList(m *registry.ModelSpec) []string {
	out := make([]string, 0, len(m.CapableTypes))
	for k := range m.CapableTypes {
		out = append(out, k)
	}
	return out
}

func staticThreshold(taskType string) float64 {
	if v, ok := router.StaticTaskThresholds[taskType]; ok {
		return v
	}
	return router.BaseQualityThreshold
}

func getenv(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func r3(f float64) float64 { return math.Round(f*1000) / 1000 }
func r4(f float64) float64 { return math.Round(f*10000) / 10000 }
