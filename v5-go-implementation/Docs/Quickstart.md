# Quickstart — routing-v5 (Go Edition)

## 1. Prerequisites

- **Go 1.22+** — `go version`
- **Ollama** running locally — `ollama serve`

### Pull required models

```bash
ollama pull granite4.1:3b
ollama pull llama3.2:latest
ollama pull gemma3:4b
ollama pull mistral-small3.2:latest
```

---

## 2. Clone & configure

```bash
cd v5-go-implementation
```

Create a `.env` file (optional — defaults work with Ollama on localhost).
Copy the provided example:

```bash
cp env.example .env
```

```dotenv
PORT=8080
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_TIMEOUT=120

# Override model names if yours differ
LLM_LIGHT=granite4.1:3b
LLM_MEDIUM=llama3.2:latest
LLM_BALANCED=gemma3:4b
LLM_HEAVY=mistral-small3.2:latest
```

---

## 3. Start the server

```bash
bash scripts/start.sh
```

Output:

```
⚙️  Building routing-v5...
🚀 Starting routing-v5 on port 8080...

✅ routing-v5 is running  (PID 12345)
🌐 URL: http://localhost:8080
📋 Logs: output/routing-v5.log
```

Open **http://localhost:8080** in your browser.

---

## 4. Using the Dashboard

### Chat tab
- Type any prompt and press **Send** (or ⏎)
- Compound prompts are split automatically:  
  _"Implement OAuth2 AND write the API docs"_ → 2 sub-tasks routed to different models
- Toggle **Dry-run** to preview routing decisions without calling any LLM

### Dashboard tab
- **Latency Timeline** — bar chart of sub-task latencies coloured by tier
- **Tier Distribution** — doughnut chart of model tier usage
- **Model Health Scores** — live circuit-breaker health
- **Dynamic Thresholds** — quality thresholds auto-adjusted by telemetry EMA

### Events tab
- Live feed of every WebSocket event: `routing_plan`, `subtask_start`, `subtask_complete`, `threshold_update`

---

## 5. REST API quick reference

```bash
# Route a prompt
curl -X POST http://localhost:8080/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "What is exponential backoff?"}'

# Dry-run (no LLM calls)
curl -X POST http://localhost:8080/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "Review this code for security issues", "dry_run": true}'

# Model registry with health
curl http://localhost:8080/api/models | jq .

# Routing statistics
curl http://localhost:8080/api/stats | jq .

# Health check
curl http://localhost:8080/api/health | jq .
```

---

## 6. Stop the server

```bash
bash scripts/stop.sh
```

---

## 7. Build manually

```bash
cd v5-go-implementation
go mod tidy          # only needed once, or after changing go.mod
go build -o routing-v5 .
./routing-v5         # no CLI flags — all config via .env / env vars
```
