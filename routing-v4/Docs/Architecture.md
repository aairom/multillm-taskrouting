# Architecture — routing-v4

## System Architecture

```mermaid
flowchart TD
    User["👤 User / Browser"]
    UI["🖥 Chat + Dashboard UI\n(static/index.html)"]
    WS["🔌 WebSocket\n/ws/telemetry"]
    API["⚡ FastAPI\napp.py"]
    Orch["🎛 Orchestrator\norchestrator.py"]
    Split["✂️ Splitter\nsplitter.py"]
    Class["🔍 Classifier\ntask_classifier.py"]
    Router["🧠 Router\nrouter.py"]
    FM["🔒 Failover Manager\nfailover_manager.py"]
    TE["📈 Telemetry Engine\ntelemetry.py"]
    LLM["🤖 LiteLLM Router\nllm_client.py"]
    Ollama["🦙 Ollama\n(local LLMs)"]
    FB["📝 Feedback Store\nfeedback.py"]
    CR["📦 Cost Registry\ncost_registry.py"]

    User -->|HTTP POST /api/chat| API
    User -->|WebSocket| WS
    WS <-->|real-time events| UI
    API --> Orch
    Orch --> Split --> Class
    Class --> Router
    Router --> CR
    Router --> FM
    Router --> TE
    FM -->|resolve failover| LLM
    Orch -->|parallel calls| LLM
    LLM -->|acompletion| Ollama
    Ollama -->|response| LLM
    LLM -->|record success/fail| FM
    Orch -->|record metrics| TE
    Orch -->|persist| FB
    TE -->|threshold_update event| WS
    Orch -->|subtask_complete event| WS
```

---

## Failover Architecture

```mermaid
stateDiagram-v2
    [*] --> CLOSED: Model registered
    CLOSED --> OPEN: consecutive_fails >= threshold
    OPEN --> HALF_OPEN: cooldown elapsed
    HALF_OPEN --> CLOSED: probe_success_count >= required
    HALF_OPEN --> OPEN: any probe fails

    note right of OPEN
        All calls bounce immediately.
        Failover chain activated.
    end note
    note right of HALF_OPEN
        Limited probe calls allowed.
        Testing for recovery.
    end note
```

### Failover Chains

| Primary | Failover 1 | Failover 2 | Reason tags |
|---|---|---|---|
| `model::light` | `model::medium` | `model::balanced` | `light_degraded`, `light_circuit_open` |
| `model::medium` | `model::balanced` | `model::heavy` | `medium_degraded`, `medium_circuit_open` |
| `model::balanced` | `model::heavy` | `model::medium` | `balanced_degraded`, `balanced_circuit_open` |
| `model::heavy` | `model::balanced` | `model::medium` | `heavy_degraded`, `heavy_circuit_open` |

---

## Dynamic Threshold Optimisation

```mermaid
flowchart LR
    Call["LLM Call\nCompleted"]
    Ring["Ring Buffer\n(last N calls)"]
    EMA["EMA Calculator\nquality_ema = α·q + (1-α)·prev"]
    Perc["Percentile\np50/p95 latency"]
    Thr["Threshold Adjuster\nthr = base + 0.5·(ema - base)"]
    CW["Cost-Weight Adjuster\ncw = base · (1 - latency_pressure)"]
    Router["Router\nuses dynamic thr & cost-weight"]
    WS["WebSocket\nbroadcast threshold_update"]

    Call --> Ring
    Ring --> EMA
    Ring --> Perc
    EMA --> Thr
    Perc --> CW
    Thr --> Router
    CW --> Router
    Thr --> WS
    CW --> WS
```

### Formula Details

| Parameter | Formula | Range |
|---|---|---|
| `quality_ema` | `α·q_new + (1−α)·q_prev` | [0, 1] |
| `quality_threshold` | `base + 0.5·(ema − base)` | [0.40, 0.95] |
| `latency_pressure` | `p95_ms / TARGET_LATENCY_MS` | [0, ∞) |
| `cost_weight` | `base × (1 − min(0.5, pressure × 0.3))` | [0.10, 0.70] |
| Utility `U` | `β·Q − α·C` where `α = cost_weight`, `β = 1−α` | (−∞, +∞) |

---

## WebSocket Event Flow

```mermaid
sequenceDiagram
    participant Browser
    participant Server
    participant Orchestrator
    participant TelemetryEngine

    Browser->>Server: WS connect /ws/telemetry
    Server-->>Browser: init (models, health, dyn_params, stats)

    Browser->>Server: POST /api/chat
    Server->>Orchestrator: handle(prompt)
    Orchestrator-->>Server: routing_plan event
    Server-->>Browser: {type: "routing_plan", sub_tasks: [...]}

    loop per sub-task (parallel)
        Orchestrator-->>Server: subtask_start
        Server-->>Browser: {type: "subtask_start", key, model}
        Orchestrator->>Ollama: LLM call
        Ollama-->>Orchestrator: response
        Orchestrator->>TelemetryEngine: record(TelemetryRecord)
        TelemetryEngine-->>Server: threshold_update event
        Server-->>Browser: {type: "threshold_update", params}
        Orchestrator-->>Server: subtask_complete
        Server-->>Browser: {type: "subtask_complete", metrics, health}
    end

    Orchestrator-->>Server: request_complete
    Server-->>Browser: {type: "request_complete", total_ms, merged}
    Server-->>Browser: HTTP 200 (full JSON payload)
```
