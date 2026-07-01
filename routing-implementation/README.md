# LLM Routing Chat UI

> A web-based chat interface that makes **intelligent LLM routing visible** — from theory to practice.
> Built on **LiteLLM AI Gateway → Ollama** with a FastAPI backend and a zero-dependency browser UI.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![LiteLLM](https://img.shields.io/badge/LiteLLM-Gateway-green.svg)](https://github.com/BerriAI/litellm)
[![Ollama](https://img.shields.io/badge/backend-Ollama-orange.svg)](https://ollama.ai)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-teal.svg)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## What it demonstrates

Every message you send goes through the full routing pipeline — and the **Routing Card** in the UI shows you exactly what happened:

| What you see | What it means |
|---|---|
| **Task badges** (Documentation · Code Generation · Reasoning…) | How the classifier labelled each sub-task |
| **Complexity bar** (0–100%) | The computed complexity score |
| **Model badge** (T1 · T2 · T3 · T4) | Which tier was selected and why |
| **U = 0.60·Q − 0.40·C** formula | The utility score that drove the decision |
| **Latency / Tokens / Cost** | Real execution metrics from Ollama |
| **Response tabs** | Individual model output + merged result |

### Routing pipeline (same logic as `multi-llm-router-LiteLLM`)

```
Prompt → Split (AND / additionally …) → Classify → U = β·Q − α·C → LiteLLM Router → Ollama
```

---

## Model Tiers

| Badge | Label | Provider | Ollama Model | Strengths |
|---|---|---|---|---|
| T1 🟢 | `model::light` | IBM Granite | `granite4.1:3b` | Docs, summaries, QA |
| T2 🔵 | `model::medium` | Meta LLaMA | `llama3.2:latest` | Code, CRUD, general |
| T3 🟣 | `model::balanced` | Google Gemma | `gemma3:4b` | Reasoning, analysis |
| T4 🔴 | `model::heavy` | Mistral AI | `mistral-small3.2:latest` | Security, auth, arch |

---

## Quickstart

### 1. Pull Ollama models

```bash
ollama pull granite4.1:3b
ollama pull llama3.2:latest
ollama pull gemma3:4b
ollama pull mistral-small3.2:latest
```

### 2. Start the chat UI

```bash
cd routing-implementation
chmod +x scripts/demo.sh scripts/start.sh scripts/stop.sh
./scripts/demo.sh
```

The script bootstraps the venv, installs deps, starts the server, and prints the URL.
It **auto-detects a free port** starting at 8080 — if 8080 is taken it tries 8081, 8082 … and tells you which port it picked:

```
[demo] Port 8080 busy — using 8081 instead.
[demo] Starting server on port 8081...
[demo] Waiting for server... ready

╔═══════════════════════════════════════════════════════════╗
║   🔀  LLM Routing Chat UI — Ready                        ║
╠═══════════════════════════════════════════════════════════╣
║   -> Open in browser:  http://localhost:8081             ║
║                                                          ║
║   Stop server:  ./scripts/stop.sh                       ║
╚═══════════════════════════════════════════════════════════╝

  Open:  http://localhost:8081
  Logs:  output/server.log
  Stop:  ./scripts/stop.sh
```

Open the URL printed in the console (8080 or whichever free port was selected).

> **Force a specific port:** `PORT=9090 ./scripts/demo.sh`

### 3. Try these prompts

```
Write the API reference documentation for our REST /users endpoints

Implement an OAuth2 Bearer-token middleware in Python FastAPI

Write the API docs AND implement the OAuth2 middleware

What is the best architecture for a microservices payment gateway? Evaluate the trade-offs

Summarise the key benefits of message queues AND implement a RabbitMQ consumer in Python

Do a security audit of this JWT validation code AND write a README for the project
```

### 4. Stop the server

```bash
./scripts/stop.sh
```

---

## Project Structure

```
routing-implementation/
├── app.py                      # FastAPI: serves UI + /api/chat, /api/models, /api/stats
├── requirements.txt
├── .env.example
├── static/
│   └── index.html              # ★ Self-contained chat UI (routing visualiser)
├── src/
│   ├── task_classifier.py      # Keyword → TaskProfile (type, complexity, tier)
│   ├── splitter.py             # Conjunction-based prompt splitting
│   ├── cost_registry.py        # 4-tier model registry
│   ├── router.py               # U = β·Q − α·C selection
│   ├── llm_client.py           # LiteLLM Router singleton → Ollama
│   ├── orchestrator.py         # ★ Enriched: returns utility/quality scores to UI
│   └── feedback.py             # JSONL metrics store
├── scripts/
│   ├── demo.sh                 # ★ Bootstrap + start server + print URL
│   ├── start.sh                # Start server in detached mode
│   └── stop.sh                 # Graceful shutdown
├── Docs/
│   ├── Architecture.md
│   └── Quickstart.md
└── output/                     # feedback.jsonl, server.log
```

---

## API

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Chat UI |
| `POST` | `/api/chat` | Route prompt → routing metadata + LLM responses |
| `GET` | `/api/models` | Model registry (tiers, providers, quality curves) |
| `GET` | `/api/stats` | Session routing statistics |
| `GET` | `/health` | Liveness probe |
| `GET` | `/api/docs` | Interactive API documentation |

### `POST /api/chat` payload

```json
{ "prompt": "Write the API docs AND implement OAuth2", "dry_run": false }
```

### Response shape

```json
{
  "prompt": "...",
  "total_ms": 1840,
  "merged": "## Documentation ...\n\n---\n\n## Code Generation ...",
  "sub_tasks": [
    {
      "task_type": "documentation",
      "complexity": 0.258,
      "tier": "LOW",
      "model": "model::light",
      "provider": "IBM Granite",
      "ollama_model": "granite4.1:3b",
      "utility": 0.3616,
      "quality": 0.6388,
      "threshold": 0.60,
      "latency_ms": 312,
      "out_tokens": 214,
      "cost_units": 0.0000107,
      "response": "..."
    }
  ]
}
```

---

## License

MIT © 2026
