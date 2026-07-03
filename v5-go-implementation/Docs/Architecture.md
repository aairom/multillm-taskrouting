# Architecture — routing-v5 (Go Edition)

## System Overview

routing-v5 is a complete port of the Python `routing-v4` application to Go.  
It preserves the exact same HTTP API, WebSocket telemetry protocol, and intelligent
routing logic — compiled to a single self-contained binary.

---

## Component Architecture

```mermaid
flowchart TD
    Client["Browser / API Client"]

    subgraph Echo["Echo HTTP Server  (main.go)"]
        POST["/api/chat"]
        WS["/ws/telemetry"]
        StaticAPI["/api/models\n/api/stats\n/api/health\n/api/telemetry"]
    end

    subgraph Orchestrator["orchestrator.Handle()"]
        Splitter["classifier.SplitAndClassify"]
        Dispatch["router.Dispatch"]
        ExecPool["goroutine pool\none per sub-task"]
        Merge["merge results"]
    end

    subgraph LLM["llmclient.CallModel"]
        Ollama["Ollama  /v1/chat/completions"]
    end

    subgraph Infrastructure
        FM["failover.Manager\ncircuit breakers"]
        Telem["telemetry.Engine\nring buffer + EMA"]
        FB["feedback.Store\noutput/feedback.jsonl"]
        EventCh["chan map event\n500-slot buffer"]
    end

    Client -->|POST /api/chat| POST
    Client <-->|WebSocket| WS
    POST --> Orchestrator
    Splitter --> Dispatch
    Dispatch -->|uses| FM
    Dispatch -->|reads thresholds| Telem
    ExecPool --> LLM
    LLM --> FM
    ExecPool --> Telem
    ExecPool --> FB
    ExecPool -->|routing events| EventCh
    Telem -->|threshold_update| EventCh
    EventCh -->|fan-out goroutine| WS
    StaticAPI -->|reads| FM
    StaticAPI -->|reads| Telem
    StaticAPI -->|reads| FB
```

---

## Dynamic Threshold Tuning

```mermaid
flowchart LR
    Call["LLM Call\ncomplete"] --> Record["telemetry.Engine.Record"]
    Record --> EMA["compute quality EMA\np50 / p95 latency\nsuccess rate"]
    EMA --> NewThr["new_threshold =\nclip(BASE + 0.5 * delta,\nMIN, MAX)"]
    EMA --> NewCW["new_cost_weight =\nclip(BASE * 1 - latency_pressure,\nMIN, MAX)"]
    NewThr --> Router["router.Dispatch\nreads updated params"]
    NewCW --> Router
    NewThr --> WS["WebSocket\nthreshold_update event"]
```

---

## Circuit Breaker State Machine

```mermaid
stateDiagram-v2
    [*] --> CLOSED
    CLOSED --> OPEN : consecutive_fails >= threshold
    OPEN --> HALF_OPEN : cooldown elapsed
    HALF_OPEN --> CLOSED : successful_probes >= limit
    HALF_OPEN --> OPEN : any failure
```

---

## WebSocket Event Sequence

```mermaid
sequenceDiagram
    participant Browser
    participant Server
    participant Orchestrator
    participant Ollama

    Browser->>Server: WS connect /ws/telemetry
    Server-->>Browser: init event (models, dynamic_params, stats)

    Browser->>Server: POST /api/chat prompt
    Server->>Orchestrator: Handle(prompt)
    Orchestrator-->>Server: emit routing_plan
    Server-->>Browser: routing_plan event

    loop Per sub-task (parallel)
        Orchestrator-->>Server: emit subtask_start
        Server-->>Browser: subtask_start event
        Orchestrator->>Ollama: POST /v1/chat/completions
        Ollama-->>Orchestrator: response
        Orchestrator-->>Server: emit subtask_complete + threshold_update
        Server-->>Browser: subtask_complete + threshold_update events
    end

    Orchestrator-->>Server: emit request_complete
    Server-->>Browser: request_complete event
    Server-->>Browser: HTTP response (full JSON)

    loop Every 5 s
        Server-->>Browser: heartbeat event
    end
```

---

## Data Flow

```
Prompt
  │
  ▼
classifier.SplitAndClassify()
  │ → []TaskProfile
  ▼
router.Dispatch()
  │ applies:  StaticTaskThresholds (blended with live telemetry EMA)
  │           Utility  U = β·Q − α·C   (β = 1 − α,  α = dynamic cost weight)
  │           failover.Manager.Resolve() for circuit-broken models
  │ → map[key]DispatchResult
  ▼
orchestrator (goroutine per sub-task)
  │ llmclient.CallModel() → Ollama
  │ telemetry.Engine.Record() → recompute thresholds
  │ feedback.Store.Record() → append to JSONL
  │ emit WebSocket events
  │ → []SubTaskResult
  ▼
merge()
  │ → Markdown merged response
  ▼
HTTP JSON response
```
