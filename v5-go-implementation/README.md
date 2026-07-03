# routing-v5 — Advanced Multi-LLM Router (Go Edition)

[![Go 1.22+](https://img.shields.io/badge/Go-1.22+-00ADD8?logo=go)](https://go.dev)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A feature-complete port of `routing-v4` (Python/FastAPI) to pure Go.  
Identical behaviour, zero Python runtime dependency.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                          main.go                             │
│   Echo HTTP server  ·  /api/*  ·  WebSocket /ws/telemetry   │
└──────────────┬───────────────────────────────────────────────┘
               │
       orchestrator.Handle()
               │
   ┌──────────┬┴────────────┬──────────────┐
   │          │             │              │
classifier  router      llmclient      feedback
 SplitAndClassify  Dispatch   CallModel   Store.Record
               │
            failover                 telemetry
         Manager.Resolve         Engine.Record / GetThreshold
```

### Request Flow

1. `POST /api/chat` → `orchestrator.Handle(prompt)`
2. `classifier.SplitAndClassify` splits compound prompts into clauses
3. `router.Dispatch` assigns each clause to the best model tier using:
   - Static quality thresholds (blended with live telemetry)
   - Utility function `U = β·Q − α·C`
   - Circuit-breaker-aware failover
4. Sub-tasks execute in parallel (goroutines)
5. `llmclient.CallModel` calls Ollama via the OpenAI-compatible REST API
6. `telemetry.Engine.Record` recomputes dynamic thresholds after every call
7. `feedback.Store.Record` persists routing records to `output/feedback.jsonl`
8. WebSocket events stream to the live dashboard in real time

---

## Prerequisites

| Tool   | Version |
|--------|---------|
| Go     | ≥ 1.22  |
| Ollama | any     |

### Required Ollama models (defaults)

```bash
ollama pull granite4.1:3b          # light  (IBM Granite)
ollama pull llama3.2:latest        # medium (Meta LLaMA)
ollama pull gemma3:4b              # balanced (Google Gemma)
ollama pull mistral-small3.2:latest # heavy (Mistral AI)
```

---

## Quick Start

```bash
cd v5-go-implementation
cp env.example .env       # edit if needed
bash scripts/start.sh
# → http://localhost:8080
```

To stop:

```bash
bash scripts/stop.sh
```

---

## Configuration (.env)

| Variable                  | Default                       | Description                        |
|---------------------------|-------------------------------|------------------------------------|
| `PORT`                    | `8080`                        | HTTP listen port                   |
| `OLLAMA_BASE_URL`         | `http://localhost:11434`      | Ollama API base URL                |
| `OLLAMA_TIMEOUT`          | `120`                         | Request timeout (seconds)          |
| `LLM_LIGHT`               | `granite4.1:3b`               | Primary light model                |
| `LLM_MEDIUM`              | `llama3.2:latest`             | Primary medium model               |
| `LLM_BALANCED`            | `gemma3:4b`                   | Primary balanced model             |
| `LLM_HEAVY`               | `mistral-small3.2:latest`     | Primary heavy model                |
| `LLM_*_FALLBACK`          | (see llmclient.go)            | Fallback models per tier           |
| `CIRCUIT_FAILURE_THRESHOLD` | `3`                         | Failures before circuit opens      |
| `CIRCUIT_COOLDOWN_SECONDS`  | `30`                         | Cooldown before HALF_OPEN probe    |
| `CIRCUIT_HALF_OPEN_PROBES`  | `2`                          | Successful probes to re-close      |
| `TELEMETRY_WINDOW`          | `50`                          | Ring buffer size per (model, task) |
| `EMA_ALPHA`                 | `0.15`                        | EMA smoothing factor               |

---

## API Reference

| Method | Path                     | Description                                 |
|--------|--------------------------|---------------------------------------------|
| GET    | `/`                      | Chat + live dashboard UI                    |
| POST   | `/api/chat`              | Route a prompt (supports `dry_run: true`)   |
| GET    | `/api/models`            | Full model registry with live health        |
| GET    | `/api/stats`             | Aggregated routing statistics               |
| GET    | `/api/health`            | Liveness + circuit-breaker snapshot         |
| GET    | `/api/telemetry`         | Dynamic parameters + recent records         |
| GET    | `/api/failover/events`   | Recent failover event log                   |
| WS     | `/ws/telemetry`          | Real-time event stream                      |

---

## Package Structure

```
v5-go-implementation/
├── main.go                          # Echo server, HTTP handlers, WebSocket
├── go.mod
├── go.sum
├── env.example                      # copy to .env and edit
├── internal/
│   ├── registry/    registry.go     # 4-tier model pool + failover chains
│   ├── classifier/  classifier.go   # Prompt splitting + task classification
│   ├── failover/    failover.go     # Circuit breakers + failover resolution
│   ├── telemetry/   telemetry.go    # Ring buffer + dynamic threshold tuner
│   ├── feedback/    feedback.go     # JSONL feedback store + analytics
│   ├── llmclient/   llmclient.go    # HTTP client for Ollama (OpenAI-compat.)
│   ├── router/      router.go       # Utility scoring + dispatch
│   └── orchestrator/ orchestrator.go # Parallel execution + event broadcast
├── static/
│   └── index.html                   # Chat + live dashboard (unchanged from v4)
├── scripts/
│   ├── start.sh
│   └── stop.sh
├── Docs/
│   ├── Architecture.md
│   └── Quickstart.md
└── output/                          # feedback.jsonl, PID file, logs
```

---

## License

MIT © 2025
