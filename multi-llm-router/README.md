# Multi-LLM Task Router

> **Theoretical + runnable demo** of an intelligent task dispatcher that routes LLM sub-tasks to the cheapest model tier that meets a quality threshold.

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![Ollama](https://img.shields.io/badge/backend-Ollama-black)](https://ollama.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)

---

## What it does

A single compound user prompt — e.g.  
_"Write the API reference docs **AND** implement the OAuth2 Bearer-token middleware"_  
— is automatically:

1. **Split** into independent sub-tasks (`DOCUMENTATION`, `CODE_GENERATION`)
2. **Classified** with a complexity score `[0, 1]`
3. **Routed** to the cheapest model tier that meets a minimum quality threshold
4. **Executed in parallel** via Ollama
5. **Merged** into a single structured response

Result: the documentation sub-task goes to the fast/cheap `model::light` tier; the OAuth2 code generation goes to the powerful `model::heavy` tier — paying only for what each task actually needs.

---

## Architecture

```
User prompt
    │
    ▼
┌──────────────────┐
│  Task Splitter   │  splits on AND / also / additionally
└────────┬─────────┘
         │  N × clauses
         ▼
┌──────────────────┐
│   Classifier     │  keyword signals + depth markers → complexity score
└────────┬─────────┘
         │  N × TaskProfile
         ▼
┌──────────────────┐    ┌─────────────────────┐
│     Router       │◄───│  Cost Model Registry│
│  U = 0.6Q − 0.4C│    │  model::light/medium│
└────────┬─────────┘    │  /heavy             │
         │              └─────────────────────┘
    ┌────┴────────────────┐
    │                     │
    ▼                     ▼
model::light         model::heavy
(Tier 1 — cheap)    (Tier 3 — powerful)
    │                     │
    └──────────┬──────────┘
               ▼
        ┌─────────────┐
        │  Aggregator │  merge + section headers
        └──────┬──────┘
               ▼
        ┌─────────────┐
        │  Feedback   │  record cost, latency, quality
        └─────────────┘
```

See [`Docs/Architecture.md`](Docs/Architecture.md) for Mermaid diagrams (class, sequence, flow).

---

## Project structure

```
multi-llm-router/
├── app.py                  # FastAPI server + CLI demo entry point
├── src/
│   ├── task_classifier.py  # TaskType enum, complexity scoring, TaskProfile
│   ├── cost_registry.py    # ModelSpec registry (symbolic tiers only)
│   ├── router.py           # Utility-maximising routing algorithm
│   ├── splitter.py         # Compound prompt splitter
│   ├── orchestrator.py     # Async pipeline: split → route → execute → merge
│   ├── llm_client.py       # Thin async Ollama client
│   └── feedback.py         # JSONL feedback store + analytics
├── scripts/
│   ├── launch.sh           # Start server in detached mode
│   ├── shutdown.sh         # Graceful stop
│   └── demo.sh             # Run the scenario in terminal
├── Docs/
│   ├── Architecture.md     # Mermaid architecture diagrams
│   └── Quickstart.md       # 5-minute setup guide
├── requirements.txt
├── .env.example
└── output/                 # Generated: server.log, feedback.jsonl
```

---

## Quickstart

```bash
# 1. Pull all 4 provider models via Ollama
ollama pull granite4.1:3b && ollama pull llama3.2 && ollama pull gemma3:4b && ollama pull mistral-small3.2

# 2. Configure
cp .env.example .env

# 3a. Terminal demo (dry-run — no LLM calls)
DRY_RUN=1 ./scripts/demo.sh

# 3b. Terminal demo (full — calls Ollama)
./scripts/demo.sh

# 3c. API server
./scripts/launch.sh
# → http://localhost:8080/docs
```

See [`Docs/Quickstart.md`](Docs/Quickstart.md) for full instructions including curl examples.

---

## Routing algorithm

```
For each sub-task:
  1. Filter models that (a) support the task type and (b) fit the token budget.
  2. Filter models with quality_score(complexity) ≥ 0.72.
  3. Among candidates, pick max(U) where U = 0.6 × Q − 0.4 × C.
  4. If no candidate passes step 2, fall back to the highest-quality model.

Special case: code_review tasks always go to Tier 4 — Mistral AI (security override).
```

| Tier | Label | Provider | Ollama model | Cost (norm.) | Best for |
|------|-------|----------|--------------|--------------|----------|
| 1 | `model::light` | IBM Granite | `granite4.1:3b` | 0.05 | Docs, summaries, simple QA |
| 2 | `model::medium` | Meta LLaMA | `llama3.2:latest` | 0.20 | CRUD code, general code gen |
| 3 | `model::balanced` | Google Gemma | `gemma3:4b` | 0.35 | Reasoning, tests, analysis |
| 4 | `model::heavy` | Mistral AI | `mistral-small3.2:latest` | 1.00 | Security, auth, architecture |

---

## Demo scenario output (dry-run)

```
================================================================================
  Multi-LLM Task Router  —  Demonstration Scenario  (4 providers)
================================================================================

Model tier mapping:
  model::light          IBM Granite     →  granite4.1:3b
  model::medium         Meta LLaMA      →  llama3.2:latest
  model::balanced       Google Gemma    →  gemma3:4b
  model::heavy          Mistral AI      →  mistral-small3.2:latest

Detected 2 sub-task(s):
  [1] TaskProfile(type='documentation',   complexity=0.260, tier=LOW,    tokens≈16)
  [2] TaskProfile(type='code_generation', complexity=0.609, tier=MEDIUM, tokens≈15)

Routing decisions:
  Task Type              Complexity  Tier       Label                Provider       U
  ────────────────────────────────────────────────────────────────────────────────────
  documentation               0.260  LOW        model::light         IBM Granite   +0.3616
  code_generation             0.609  MEDIUM     model::medium        Meta LLaMA    +0.3160
```

- **Documentation** → `model::light` → `granite4.1:3b` (IBM Granite) — cheapest sufficient model for prose
- **Code generation** → `model::balanced` → `gemma3:4b` (Google Gemma) — higher reasoning quality wins over LLaMA at this complexity
- **Security / `code_review`** → always forced to `model::heavy` → `mistral-small3.2:latest` (Mistral AI)

---

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/route` | Route and execute a prompt (`dry_run: true` skips LLM calls) |
| `GET` | `/feedback` | Aggregated routing statistics |
| `GET` | `/health` | Health check |
| `GET` | `/docs` | Swagger UI |

---

## License

MIT — see [LICENSE](LICENSE).  
This project is a **theoretical demonstration**; no production LLM API keys are exposed or required.
