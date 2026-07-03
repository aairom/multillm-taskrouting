# Bob-MultiLLM — Intelligent Multi-LLM Router Monorepo

> A progressive series of implementations exploring how to intelligently route
> LLM sub-tasks across multiple local models — from a minimal prototype to a
> production-grade Go binary with real-time telemetry.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Ollama](https://img.shields.io/badge/backend-Ollama-orange.svg)](https://ollama.ai)

---

## Project Evolution

```
multi-llm-router          → v1  Raw Ollama client, utility-based routing
multi-llm-router-LiteLLM  → v2  LiteLLM Gateway, retries, fallback chains
routing-implementation    → v3  Browser chat UI, visible routing cards
routing-v4                → v4  Circuit breakers, dynamic thresholds, live WebSocket dashboard
v5-go-implementation      → v5  Complete Go port — single binary, zero Python runtime
```

---

## Sub-Projects

### v1 — [`multi-llm-router/`](multi-llm-router/)

**Multi-LLM Task Router — Minimal prototype**

Splits a compound prompt into sub-tasks, classifies each with a complexity
score, and routes to the cheapest Ollama model tier that meets a quality
threshold using a utility function `U = 0.6·Q − 0.4·C`. Terminal demo
and a minimal FastAPI API. No web UI, no retries, no circuit breakers.

| | |
|---|---|
| **Language** | Python 3.11+ |
| **Transport** | Raw `httpx` → Ollama |
| **UI** | CLI / terminal demo |

📄 [README](multi-llm-router/README.md) · [Architecture](multi-llm-router/Docs/Architecture.md) · [Quickstart](multi-llm-router/Docs/Quickstart.md) · [Routing Pipeline](multi-llm-router/Docs/RoutingPipeline.md)

---

### v2 — [`multi-llm-router-LiteLLM/`](multi-llm-router-LiteLLM/)

**Multi-LLM Task Router — LiteLLM Edition**

Replaces the raw HTTP client with the **LiteLLM AI Gateway Router**, gaining
automatic retries, deployment cooldowns, multi-node load balancing, and
OpenAI-compatible responses. Model swaps are configuration-only (`.env`).

| | |
|---|---|
| **Language** | Python 3.11+ |
| **Transport** | LiteLLM Router → Ollama `/v1/chat/completions` |
| **UI** | CLI + FastAPI (`/route`, `/feedback`, `/health`) |

📄 [README](multi-llm-router-LiteLLM/README.md) · [Architecture](multi-llm-router-LiteLLM/Docs/Architecture.md) · [Quickstart](multi-llm-router-LiteLLM/Docs/Quickstart.md) · [Routing Pipeline](multi-llm-router-LiteLLM/Docs/RoutingPipeline.md)

---

### v3 — [`routing-implementation/`](routing-implementation/)

**LLM Routing Chat UI**

Adds a self-contained browser UI that makes routing decisions **visible** in
real time. Each response shows task badges, complexity bars, tier selection,
utility scores, latency, token counts, and cost — alongside the merged output.
Auto-detects a free port starting at 8080.

| | |
|---|---|
| **Language** | Python 3.11+ |
| **Transport** | LiteLLM Router → Ollama |
| **UI** | Browser chat with routing cards (zero external JS deps) |

📄 [README](routing-implementation/README.md) · [Architecture](routing-implementation/Docs/Architecture.md) · [Quickstart](routing-implementation/Docs/Quickstart.md)

---

### v4 — [`routing-v4/`](routing-v4/)

**Advanced Multi-LLM Router — Python/FastAPI**

Production-grade Python application with:
- **Per-model circuit breakers** (CLOSED / OPEN / HALF_OPEN) with configurable thresholds
- **Dynamic quality thresholds** — ring-buffer EMA tuner adjusts `quality_threshold`
  and `cost_weight` per `(model × task)` pair after every call
- **Real-time WebSocket dashboard** — latency timeline, tier distribution, model health,
  live threshold visualisation (Chart.js)
- **Dual-layer routing** — LiteLLM Router handles intra-tier retries; FailoverManager
  handles cross-tier failover when a circuit opens

| | |
|---|---|
| **Language** | Python 3.11+ |
| **Transport** | LiteLLM Router → Ollama |
| **UI** | Browser dashboard with WebSocket live feed |
| **New in v4** | Circuit breakers · Dynamic thresholds · WebSocket events |

📄 [README](routing-v4/README.md) · [Architecture](routing-v4/Docs/Architecture.md) · [Quickstart](routing-v4/Docs/Quickstart.md)

---

### v5 — [`v5-go-implementation/`](v5-go-implementation/)

**Advanced Multi-LLM Router — Go Edition**

Feature-complete port of v4 to idiomatic Go. Identical HTTP API, WebSocket
protocol, and routing logic — compiled to a **single self-contained binary**.
Zero Python runtime required.

| | |
|---|---|
| **Language** | Go 1.22+ |
| **Transport** | Native `net/http` → Ollama `/v1/chat/completions` |
| **UI** | Same browser dashboard as v4 (static HTML/JS, unchanged) |
| **New in v5** | Single binary · goroutines replace asyncio · no venv |

📄 [README](v5-go-implementation/README.md) · [Architecture](v5-go-implementation/Docs/Architecture.md) · [Quickstart](v5-go-implementation/Docs/Quickstart.md)

---

## Common Model Tiers (all versions)

| Tier | Label | Provider | Default Ollama Model | Strengths |
|------|-------|----------|----------------------|-----------|
| T1 🟢 | `model::light` | IBM Granite | `granite4.1:3b` | Docs, summaries, simple QA |
| T2 🔵 | `model::medium` | Meta LLaMA | `llama3.2:latest` | Code generation, CRUD, general |
| T3 🟣 | `model::balanced` | Google Gemma | `gemma3:4b` | Reasoning, analysis, tests |
| T4 🔴 | `model::heavy` | Mistral AI | `mistral-small3.2:latest` | Security, auth, architecture |

Pull all four once:

```bash
ollama pull granite4.1:3b
ollama pull llama3.2:latest
ollama pull gemma3:4b
ollama pull mistral-small3.2:latest
```

---

## Routing Algorithm (all versions)

```
For each sub-task clause:
  1. Filter models that support the task type and fit the token budget
  2. Filter models where quality_score(complexity) ≥ effective_threshold
  3. Select max(U)  where  U = β·Q − α·C
        Q = model quality at given complexity
        C = normalised cost per 1k tokens
        α = dynamic cost weight  (default 0.40, adjusted by telemetry in v4/v5)
        β = 1 − α
  4. Safety net: if no candidate passes step 2, use highest-quality model
  Special: code_review tasks always use Tier 4 (security override)
```

---

## Repository Layout

```
Bob-MultiLLM/
├── README.md                          ← you are here
├── multi-llm-router/                  ← v1  Raw Ollama, CLI demo
│   ├── README.md
│   └── Docs/  Architecture.md  Quickstart.md  RoutingPipeline.md
├── multi-llm-router-LiteLLM/          ← v2  LiteLLM Gateway
│   ├── README.md
│   └── Docs/  Architecture.md  Quickstart.md  RoutingPipeline.md
├── routing-implementation/            ← v3  Browser chat UI
│   ├── README.md
│   └── Docs/  Architecture.md  Quickstart.md
├── routing-v4/                        ← v4  Circuit breakers + live dashboard
│   ├── README.md
│   └── Docs/  Architecture.md  Quickstart.md
└── v5-go-implementation/              ← v5  Go binary, same feature set as v4
    ├── README.md
    └── Docs/  Architecture.md  Quickstart.md
```

---

## Quick Navigation

| Document | Link |
|---|---|
| v1 Architecture | [multi-llm-router/Docs/Architecture.md](multi-llm-router/Docs/Architecture.md) |
| v1 Quickstart | [multi-llm-router/Docs/Quickstart.md](multi-llm-router/Docs/Quickstart.md) |
| v2 Architecture | [multi-llm-router-LiteLLM/Docs/Architecture.md](multi-llm-router-LiteLLM/Docs/Architecture.md) |
| v2 Quickstart | [multi-llm-router-LiteLLM/Docs/Quickstart.md](multi-llm-router-LiteLLM/Docs/Quickstart.md) |
| v3 Architecture | [routing-implementation/Docs/Architecture.md](routing-implementation/Docs/Architecture.md) |
| v3 Quickstart | [routing-implementation/Docs/Quickstart.md](routing-implementation/Docs/Quickstart.md) |
| v4 Architecture | [routing-v4/Docs/Architecture.md](routing-v4/Docs/Architecture.md) |
| v4 Quickstart | [routing-v4/Docs/Quickstart.md](routing-v4/Docs/Quickstart.md) |
| v5 Architecture | [v5-go-implementation/Docs/Architecture.md](v5-go-implementation/Docs/Architecture.md) |
| v5 Quickstart | [v5-go-implementation/Docs/Quickstart.md](v5-go-implementation/Docs/Quickstart.md) |

---

## License

MIT © 2025 — see individual sub-project READMEs for details.
