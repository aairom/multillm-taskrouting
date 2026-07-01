# Quickstart

Get the Multi-LLM Task Router running locally in under 5 minutes.

The application uses **4 LLM providers** running via Ollama (no cloud API keys required):

| Tier | Provider | Model | Role |
|------|----------|-------|------|
| 1 — light | **IBM Granite** | `granite4.1:3b` | Docs, summaries, QA |
| 2 — medium | **Meta LLaMA** | `llama3.2:latest` | General code, CRUD |
| 3 — balanced | **Google Gemma** | `gemma3:4b` | Reasoning, tests, analysis |
| 4 — heavy | **Mistral AI** | `mistral-small3.2:latest` | Security, auth, architecture |

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | ≥ 3.11 | `python3 --version` |
| Ollama | latest | [ollama.com](https://ollama.com) — must be running |
| (optional) curl / httpie | any | for manual API testing |

---

## 1. Pull the required Ollama models

```bash
# Tier 1 — IBM Granite 4.1 3B  (fast, cheap — docs / summaries / QA)
ollama pull granite4.1:3b

# Tier 2 — Meta LLaMA 3.2  (general-purpose — code, CRUD, SQL)
ollama pull llama3.2

# Tier 3 — Google Gemma 3 4B  (balanced reasoning — tests, analysis)
ollama pull gemma3:4b

# Tier 4 — Mistral Small 3.2  (security-aware — auth, architecture, code review)
ollama pull mistral-small3.2
```

Verify Ollama is reachable:

```bash
curl http://localhost:11434/api/tags
```

---

## 2. Clone / enter the project

```bash
cd multi-llm-router
```

---

## 3. Configure environment

```bash
cp .env.example .env
# Edit .env if your model names differ (e.g. llama3.2:3b instead of llama3.2:latest)
```

---

## 4a. Run the demo scenario (terminal, no server)

```bash
DRY_RUN=1 ./scripts/demo.sh   # inspect routing only — no LLM calls
./scripts/demo.sh              # full run — calls all 4 Ollama models in parallel
```

Expected output (dry run):

```
================================================================================
  Multi-LLM Task Router  —  Demonstration Scenario  (4 providers)
================================================================================

Prompt:
  Write the API reference documentation for our REST /users endpoints
  AND implement the OAuth2 Bearer-token middleware in Python FastAPI.

Model tier mapping:
  model::light          IBM Granite     →  granite4.1:3b
  model::medium         Meta LLaMA      →  llama3.2:latest
  model::balanced       Google Gemma    →  gemma3:4b
  model::heavy          Mistral AI      →  mistral-small3.2:latest

Detected 2 sub-task(s):
  [1] TaskProfile(type='documentation', complexity=0.260, tier=LOW, tokens≈16)
  [2] TaskProfile(type='code_generation', complexity=0.609, tier=MEDIUM, tokens≈15)

Routing decisions:
  Task Type              Complexity  Tier       Label                Provider       U
  ------------------------------------------------------------------------------
  documentation               0.260  LOW        model::light         IBM Granite   +0.3616
  code_generation             0.609  MEDIUM     model::balanced      Google Gemma  +0.3718

  [DRY RUN] LLM calls skipped.
```

---

## 4b. Start the FastAPI server

```bash
./scripts/launch.sh
```

Console output:

```
  ✅  Server running  → http://localhost:8080
  📋  API docs        → http://localhost:8080/docs
  📊  Feedback stats  → http://localhost:8080/feedback
```

---

## 5. Call the API

### Dry-run (inspect routing, no LLM calls)

```bash
curl -s -X POST http://localhost:8080/route \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Write the API docs AND implement OAuth2 middleware",
    "dry_run": true
  }' | python3 -m json.tool
```

### Full execution

```bash
curl -s -X POST http://localhost:8080/route \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Write the API docs AND implement OAuth2 middleware",
    "dry_run": false
  }' | python3 -m json.tool
```

### Security override scenario (always routes to Mistral)

```bash
curl -s -X POST http://localhost:8080/route \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Summarise the architecture AND review the auth code for vulnerabilities",
    "dry_run": true
  }' | python3 -m json.tool
```

Expected routing:
- `summarisation` → `model::light` (IBM Granite)
- `code_review` → `model::heavy` (Mistral Small 3.2) — _security override, always Tier 4_

### Feedback statistics

```bash
curl http://localhost:8080/feedback | python3 -m json.tool
```

---

## 6. Stop the server

```bash
./scripts/shutdown.sh
```

---

## Custom prompts

Any compound prompt works — the splitter looks for `AND`, `and also`, `additionally`, `plus`, `as well as`:

```bash
curl -s -X POST http://localhost:8080/route \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Summarise the README additionally write a Python class for user authentication",
    "dry_run": true
  }' | python3 -m json.tool
```

---

## Environment variables reference

| Variable | Default | Provider | Purpose |
|---|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | — | Ollama API base URL |
| `OLLAMA_TIMEOUT` | `120` | — | HTTP timeout (seconds) |
| `LLM_LIGHT` | `granite4.1:3b` | IBM Granite | Model for Tier 1 |
| `LLM_MEDIUM` | `llama3.2:latest` | Meta LLaMA | Model for Tier 2 |
| `LLM_BALANCED` | `gemma3:4b` | Google Gemma | Model for Tier 3 |
| `LLM_HEAVY` | `mistral-small3.2:latest` | Mistral AI | Model for Tier 4 |
| `DRY_RUN` | `0` | — | `1` = skip LLM calls |
