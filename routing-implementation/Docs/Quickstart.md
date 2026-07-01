# Quickstart — LLM Routing Chat UI

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.11+ | `python3 --version` |
| Ollama running | `ollama serve` · [ollama.ai](https://ollama.ai) |
| ~8 GB disk | For all 4 models |

---

## Step 1 — Pull Ollama models

```bash
ollama pull granite4.1:3b           # T1 IBM Granite  — docs, QA
ollama pull llama3.2:latest          # T2 Meta LLaMA   — code, general
ollama pull gemma3:4b                # T3 Google Gemma — reasoning
ollama pull mistral-small3.2:latest  # T4 Mistral AI   — security, arch
```

Verify: `curl http://localhost:11434/api/tags`

---

## Step 2 — Launch with `demo.sh`

```bash
cd routing-implementation
chmod +x scripts/demo.sh scripts/start.sh scripts/stop.sh
./scripts/demo.sh
```

The script:
1. Creates `.venv` and installs all dependencies including `litellm`
2. Copies `.env.example` → `.env`
3. Kills any stale instance tracked in `output/server.pid`
4. **Auto-detects a free port** — tries 8080, 8081 … 8089 in order; prints which port was chosen
5. Starts the FastAPI server in the background
6. Waits up to 10 s for the `/health` endpoint to respond; prints the log tail and exits with code 1 if it times out

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

Open the URL printed in the console — **the port varies** depending on what is already running on your machine.

> **Force a specific port:** `PORT=9090 ./scripts/demo.sh`

---

## Step 3 — Use the chat interface

### Single-task prompts

```
Write the API reference documentation for our REST /users endpoints
```
→ Classified as **documentation** (complexity ~26%) → routed to **T1 IBM Granite**

```
Implement an OAuth2 Bearer-token middleware in Python FastAPI
```
→ Classified as **code_generation** (complexity ~61%) → routed to **T3 Google Gemma**

### Compound prompts (split on AND)

```
Write the API docs AND implement the OAuth2 middleware
```
→ Split into 2 sub-tasks → **2 parallel Ollama calls** → routing card shows both decisions

```
Summarise the benefits of message queues AND implement a RabbitMQ consumer in Python
```

### Reasoning / architecture

```
What is the best architecture for a microservices payment gateway? Evaluate the trade-offs
```
→ Classified as **reasoning** (complexity ~83%, threshold 0.80) → routed to **T4 Mistral AI**

### Security (always T4)

```
Do a security audit of this JWT token validation code
```
→ `code_review` is a **security override** → always routed to **T4 Mistral AI** regardless of complexity

---

## Step 4 — Reading the Routing Card

Each assistant response shows a **Routing Card** (collapsible):

```
🔀 Routing Analysis — 2 sub-tasks detected          1840 ms total
┌──────────────────────────────────────────────────────────┐
│  [documentation]  [model::light]          IBM Granite    │
│  Complexity ████░░░░░░  26%  Quality 64%  ⏱ 312ms        │
│  U = 0.60 × 0.6388 − 0.40 × 0.05 = +0.3633             │
├──────────────────────────────────────────────────────────┤
│  [code_generation] [model::balanced]      Google Gemma   │
│  Complexity █████████░  61%  Quality 85%  ⏱ 1528ms       │
│  U = 0.60 × 0.8532 − 0.40 × 0.35 = +0.3719             │
└──────────────────────────────────────────────────────────┘
```

Below it, the **Response Card** has one tab per sub-task plus a **Merged** tab.

---

## Step 5 — Stop the server

```bash
./scripts/stop.sh
```

---

## Configuration

Edit `.env` to change models or the Ollama URL:

```bash
OLLAMA_BASE_URL=http://localhost:11434
LLM_LIGHT=granite4.1:3b
LLM_MEDIUM=llama3.2:latest
LLM_BALANCED=gemma3:4b
LLM_HEAVY=mistral-small3.2:latest
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Blank model sidebar | Check `GET /api/models` in browser devtools; ensure server started |
| `Connection refused` port 11434 | Run `ollama serve` |
| `model not found` | `ollama pull <model-name>` |
| LiteLLM timeout | Increase `OLLAMA_TIMEOUT` in `.env` |
| Port 8080 in use | Script auto-picks next free port; or `PORT=9090 ./scripts/demo.sh` |
| Server did not start | Script prints last 20 lines of `output/server.log` automatically |
| `demo.sh: permission denied` | `chmod +x scripts/demo.sh` |
