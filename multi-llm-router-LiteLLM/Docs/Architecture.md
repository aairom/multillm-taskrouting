# Architecture — Multi-LLM Task Router (LiteLLM Edition)

> **Version:** 1.0.0  
> **Backend:** Ollama (local) via LiteLLM AI Gateway Router

---

## High-Level Architecture

```mermaid
flowchart TD
    subgraph Client
        U["User / HTTP Client\nPOST /route"]
    end

    subgraph FastAPI["FastAPI  (app.py)"]
        EP["Route Endpoint\n/route"]
    end

    subgraph Pipeline["Routing Pipeline"]
        SP["Splitter\nsplit_and_classify()"]
        CL["Task Classifier\nclassify()"]
        RO["Router\nU = β·Q − α·C\nrouter.py"]
    end

    subgraph Gateway["LiteLLM AI Gateway Router\nllm_client.py"]
        LR["litellm.Router\nacompletion()"]
        RT["Retry / Cooldown\nFallback Chain"]
    end

    subgraph Ollama["Ollama (localhost:11434)"]
        M1["granite4.1:3b\nmodel::light"]
        M2["llama3.2:latest\nmodel::medium"]
        M3["gemma3:4b\nmodel::balanced"]
        M4["mistral-small3.2\nmodel::heavy"]
    end

    subgraph Output
        OR["Orchestrator\n_merge()"]
        FS["FeedbackStore\noutput/feedback.jsonl"]
        RS["FastAPI Response"]
    end

    U --> EP
    EP --> SP
    SP --> CL
    CL --> RO
    RO --> LR
    LR --> RT
    RT --> M1
    RT --> M2
    RT --> M3
    RT --> M4
    M1 & M2 & M3 & M4 -->|asyncio.gather| OR
    OR --> RS
    OR --> FS
    RS --> U
```

---

## Component Responsibilities

| Component | File | Responsibility |
|---|---|---|
| **FastAPI App** | `app.py` | HTTP entry point, request/response models, demo runner |
| **Splitter** | `src/splitter.py` | Split compound prompts on conjunction markers |
| **Task Classifier** | `src/task_classifier.py` | Keyword + phrase detection → `TaskProfile` (type, complexity, tier) |
| **Router** | `src/router.py` | Utility-function model selection `U = β·Q − α·C` |
| **LLM Client** | `src/llm_client.py` | **LiteLLM Router** singleton — maps tier aliases to `ollama/<model>` |
| **Orchestrator** | `src/orchestrator.py` | `asyncio.gather` parallel execution + response merge |
| **Cost Registry** | `src/cost_registry.py` | Abstract 4-tier model specs (quality curves, costs, `capable_types`) |
| **Feedback Store** | `src/feedback.py` | Append-only JSONL metrics store |
| **demo.sh** | `scripts/demo.sh` | Self-contained terminal demo — venv bootstrap + `DRY_RUN` support |
| **start.sh** | `scripts/start.sh` | Launch FastAPI server in detached mode (`nohup`) |
| **stop.sh** | `scripts/stop.sh` | Graceful `SIGTERM` shutdown via PID file |

---

## Data Flow Sequence

```mermaid
sequenceDiagram
    participant C as Client
    participant A as app.py
    participant O as Orchestrator
    participant SP as Splitter
    participant CL as Classifier
    participant RO as Router
    participant LR as LiteLLM Router
    participant OL as Ollama

    C->>A: POST /route { prompt }
    A->>O: handle(prompt)
    O->>SP: split_and_classify(prompt)
    SP->>CL: classify(clause_1)
    SP->>CL: classify(clause_2)
    CL-->>SP: TaskProfile × N
    SP-->>O: [TaskProfile, ...]
    O->>RO: dispatch([profiles])
    RO-->>O: {key: (profile, ModelSpec)} × N
    O->>LR: acompletion("model::light", ...) [parallel]
    O->>LR: acompletion("model::heavy", ...) [parallel]
    LR->>OL: ollama/granite4.1:3b
    LR->>OL: ollama/mistral-small3.2
    OL-->>LR: responses
    LR-->>O: SubTaskResult × N
    O-->>A: OrchestratorResult (merged)
    A-->>C: RouteResponse (JSON)
```

---

## LiteLLM Gateway Integration

```mermaid
flowchart LR
    subgraph App["Application Layer"]
        OR["Orchestrator\nrouter.acompletion()"]
    end

    subgraph LiteLLM["LiteLLM Router (llm_client.py)"]
        RL["model_list\n4 tier aliases"]
        RS["simple-shuffle\nrouting strategy"]
        RR["Retry engine\n(num_retries=2)"]
        RC["Cooldown tracker\n(allowed_fails=3)"]
    end

    subgraph Ollama["Ollama (local)"]
        O1["granite4.1:3b"]
        O2["llama3.2:latest"]
        O3["gemma3:4b"]
        O4["mistral-small3.2"]
    end

    OR -->|"model='model::light'"| RL
    RL --> RS
    RS --> RR
    RR --> RC
    RC -->|"ollama/granite4.1:3b"| O1
    RC -->|"ollama/llama3.2:latest"| O2
    RC -->|"ollama/gemma3:4b"| O3
    RC -->|"ollama/mistral-small3.2"| O4
```

The **utility-based router** (`router.py`) decides **which tier** to use.  
The **LiteLLM Router** (`llm_client.py`) handles **how to call** that tier reliably.

---

## Complexity Scoring

```
final_score = min(1.0,  base_score  +  token_factor  +  depth_penalty)

  base_score    from keyword/phrase matching  (task-type specific)
  token_factor  = min(0.15,  log10(tokens) × 0.05)
  depth_penalty = min(0.20,  count(multi-step markers) × 0.04)

  tier:  LOW    [0.00 – 0.34]
         MEDIUM [0.35 – 0.64]
         HIGH   [0.65 – 1.00]
```

## Utility Function

```
U = β·Q − α·C    (β = 0.60, α = 0.40)

  Q = model.quality_score(complexity)  ∈ [0, 1]
  C = model.cost_per_1k                ∈ [0, 1]  (normalised; Mistral = 1.0)
```

The model with the **highest U** that also passes the per-task quality threshold wins.
