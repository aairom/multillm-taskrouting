# Multi-LLM Task Router — Architecture

This document describes the theoretical and implemented architecture of an intelligent task router that dispatches LLM sub-tasks to the cheapest model tier that meets a quality threshold.

The implementation uses **4 real LLM providers** running locally via Ollama, demonstrating that the routing layer is completely provider-agnostic.

---

## System Architecture

```mermaid
graph TD
    U([User / Caller]) --> I[Task Intake & Splitter]
    I --> C[Complexity Analyzer]
    C --> R{Router / Dispatcher}
    CR[(Cost Model Registry)] -.->|consult| R

    R -->|score LOW| T1["Tier 1 · model::light
IBM Granite 4.1 3B
granite4.1:3b
Fast · Cheap · Docs · QA"]

    R -->|score MEDIUM| T2["Tier 2 · model::medium
Meta LLaMA 3.2
llama3.2:latest
General Code · CRUD · SQL"]

    R -->|score BALANCED| T3["Tier 3 · model::balanced
Google Gemma 3 4B
gemma3:4b
Reasoning · Tests · Analysis"]

    R -->|score HIGH| T4["Tier 4 · model::heavy
Mistral Small 3.2
mistral-small3.2:latest
Security · OAuth · Architecture"]

    T1 --> AG[Response Aggregator]
    T2 --> AG
    T3 --> AG
    T4 --> AG
    AG --> FB[Feedback Store]
    FB -.->|update weights| R
    AG --> U

    style T1 fill:#dcfce7,stroke:#16a34a
    style T2 fill:#dbeafe,stroke:#1e40af
    style T3 fill:#fef9c3,stroke:#b45309
    style T4 fill:#fee2e2,stroke:#b91c1c
    style R  fill:#fff7ed,stroke:#d97706
    style CR fill:#f7f8fa,stroke:#9ca3af,stroke-dasharray:4
```

---

## Provider Diversity

The 4 tiers deliberately span 4 independent LLM providers to demonstrate that routing is **provider-agnostic**. The symbolic labels (`model::light`, `model::medium`, `model::balanced`, `model::heavy`) are resolved to real model names at runtime via environment variables.

| Tier | Symbolic Label | Provider | Ollama Model | Specialisation |
|------|---------------|----------|--------------|----------------|
| 1 | `model::light` | **IBM Granite** | `granite4.1:3b` | Docs, summaries, simple QA |
| 2 | `model::medium` | **Meta LLaMA** | `llama3.2:latest` | General code, CRUD, SQL |
| 3 | `model::balanced` | **Google Gemma** | `gemma3:4b` | Reasoning, tests, analysis |
| 4 | `model::heavy` | **Mistral AI** | `mistral-small3.2:latest` | Security, auth, architecture |

---

## Component Breakdown

```mermaid
classDiagram
    class TaskIntake {
        +split_and_classify(prompt: str) list[TaskProfile]
        -_detect_split_points(text: str) list[str]
    }

    class TaskProfile {
        +raw_text: str
        +task_type: TaskType
        +complexity: float
        +tier: ComplexityTier
        +token_estimate: int
    }

    class Classifier {
        +classify(text: str) TaskProfile
        -_token_estimate(text: str) int
        -_depth_penalty(text: str) float
    }

    class Router {
        +route(profile: TaskProfile) ModelSpec
        +dispatch(profiles: list) dict
        -_utility(model, profile) float
    }

    class CostRegistry {
        +MODEL_REGISTRY: list[ModelSpec]
    }

    class ModelSpec {
        +label: str
        +tier: int
        +provider: str
        +cost_per_1k: float
        +max_tokens: int
        +capable_types: set[str]
        +quality_score: Callable
    }

    class Orchestrator {
        +handle_request(prompt: str) str
    }

    class FeedbackStore {
        +record(r: RoutingRecord)
        +avg_quality_by_tier(task_type: str) dict
        +summary() dict
    }

    TaskIntake --> Classifier
    TaskIntake --> TaskProfile
    Router --> CostRegistry
    Router --> TaskProfile
    Router --> ModelSpec
    Orchestrator --> TaskIntake
    Orchestrator --> Router
    Orchestrator --> FeedbackStore
```

---

## Routing Decision Flow

```mermaid
flowchart LR
    P([Prompt]) --> SP{Split?}
    SP -->|single intent| CL[Classify]
    SP -->|compound AND/ALSO| CL2[Classify each clause]
    CL --> SC[Score: type + depth + tokens]
    CL2 --> SC
    SC --> T{Tier?}
    T -->|score < 0.35| L1[LOW → model::light\nIBM Granite 4.1 3B]
    T -->|0.35 ≤ score < 0.55| L2[MEDIUM → model::medium\nMeta LLaMA 3.2]
    T -->|0.55 ≤ score < 0.65| L3[BALANCED → model::balanced\nGoogle Gemma 3 4B]
    T -->|score ≥ 0.65| L4[HIGH → model::heavy\nMistral Small 3.2]
    L1 --> QG{Quality ≥ threshold?}
    L2 --> QG
    L3 --> QG
    L4 --> QG
    QG -->|Yes| EX[Execute]
    QG -->|No| UP[Upgrade tier]
    UP --> EX
    EX --> MG[Merge responses]
    MG --> OUT([Output])
```

---

## Worked Scenario — Documentation vs. Code Split

```mermaid
sequenceDiagram
    actor User
    participant S as Splitter
    participant C as Classifier
    participant R as Router
    participant G as model::light (granite4.1:3b)
    participant L as model::medium (llama3.2)
    participant A as Aggregator

    User->>S: "Write API docs AND implement OAuth2 middleware"
    S->>C: clause A: "Write API docs…"
    S->>C: clause B: "implement OAuth2 middleware…"
    C-->>R: ProfileA {type=DOCS, complexity=0.26, tier=LOW}
    C-->>R: ProfileB {type=CODE, complexity=0.61, tier=MEDIUM}
    R->>G: dispatch ProfileA → model::light (IBM Granite)
    R->>L: dispatch ProfileB → model::medium (Meta LLaMA)
    par Parallel execution
        G-->>A: Documentation response
    and
        L-->>A: OAuth2 code response
    end
    A-->>User: Merged final response
```

> **Security scenario:** a `code_review` task is always forced to `model::heavy` (Mistral Small 3.2) via the security override — regardless of complexity score.

---

## Cost Model

| Tier | Label | Provider | Ollama Model | Relative cost / 1K tokens | Quality (low complexity) | Quality (high complexity) |
|------|-------|----------|--------------|---------------------------|--------------------------|---------------------------|
| 1 | `model::light`    | IBM Granite | `granite4.1:3b`               | 0.05 (normalised) | High | Low |
| 2 | `model::medium`   | Meta LLaMA  | `llama3.2:latest`             | 0.20 (normalised) | High | Medium |
| 3 | `model::balanced` | Google Gemma | `gemma3:4b`                  | 0.35 (normalised) | High | Medium-High |
| 4 | `model::heavy`    | Mistral AI  | `mistral-small3.2:latest`     | 1.00 (normalised) | High | High |

**Utility function:** `U = 0.6 × Quality − 0.4 × Cost`  
The router selects the model that maximises U while satisfying the per-task quality threshold.

**Per-task quality thresholds:**

| Task type | Threshold | Reason |
|-----------|-----------|--------|
| `documentation` | 0.60 | Prose tolerates lighter models |
| `summarisation` | 0.55 | Even more lenient |
| `qa_simple` | 0.55 | Factual lookups need less depth |
| `code_generation` | 0.72 | Code correctness matters |
| `reasoning` | 0.80 | Architecture requires depth |
| `code_review` | forced Tier 4 | Security override — always Mistral |
