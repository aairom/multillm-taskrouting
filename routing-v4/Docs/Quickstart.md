# Quickstart — routing-v4

## Prerequisites

- **Python 3.11+**
- **Ollama** installed and running locally — [ollama.ai](https://ollama.ai)
- At least one supported model pulled

## Step 1 — Pull Ollama Models

Pull all four tier models for the full experience:

```bash
ollama pull granite4.1:3b        # Tier 1 — IBM Granite (docs, summaries)
ollama pull llama3.2:latest      # Tier 2 — Meta LLaMA  (code, general)
ollama pull gemma3:4b            # Tier 3 — Google Gemma (reasoning)
ollama pull mistral-small3.2:latest  # Tier 4 — Mistral AI  (security, heavy)
```

> **Minimal setup:** pull only `llama3.2:latest` and point all tiers at it via `.env`.

## Step 2 — Start the Server

```bash
cd routing-v4
./scripts/start.sh
```

The console will print:

```
╔══════════════════════════════════════════════════════════════╗
║   routing-v4 — Advanced Multi-LLM Router                    ║
╠══════════════════════════════════════════════════════════════╣
║   Dashboard:  http://localhost:8080                         ║
║   API docs:   http://localhost:8080/api/docs                ║
║   Health:     http://localhost:8080/api/health              ║
║   Telemetry:  ws://localhost:8080/ws/telemetry              ║
╚══════════════════════════════════════════════════════════════╝
```

## Step 3 — Open the Dashboard

Navigate to **http://localhost:8080** in your browser.

You'll see three tabs:

| Tab | What it shows |
|---|---|
| 💬 **Chat** | Send prompts; see per-subtask routing cards with live metrics |
| 📊 **Dashboard** | Latency timeline · Tier distribution · Model health · Dynamic thresholds |
| ⚡ **Events** | Real-time WebSocket event log |

## Step 4 — Try Example Prompts

```
Implement an OAuth2 middleware AND write the API reference documentation
```
→ Splits into `code_generation` (T2/T3) + `documentation` (T1)

```
Review this auth code for security vulnerabilities
```
→ Forces `code_review` → Tier 4 (security override)

```
Summarise the trade-offs between microservices and monolith AND design a migration plan
```
→ `summarisation` (T1) + `reasoning` (T3/T4)

## Configuration

Edit `routing-v4/.env` (auto-created from `.env.example` on first start):

```dotenv
# Tier model assignments
LLM_LIGHT=granite4.1:3b
LLM_MEDIUM=llama3.2:latest
LLM_BALANCED=gemma3:4b
LLM_HEAVY=mistral-small3.2:latest

# Circuit-breaker tuning
CIRCUIT_FAILURE_THRESHOLD=3
CIRCUIT_COOLDOWN_SECONDS=30
CIRCUIT_HALF_OPEN_PROBES=2

# Telemetry EMA window
TELEMETRY_WINDOW=50
EMA_ALPHA=0.15
```

## Stop the Server

```bash
./scripts/stop.sh
```

## API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Chat + Dashboard UI |
| `/api/chat` | POST | Route prompt, execute LLMs |
| `/api/models` | GET | Model registry + health + failover chains |
| `/api/stats` | GET | Aggregated feedback statistics |
| `/api/health` | GET | Liveness + circuit-breaker snapshot |
| `/api/telemetry` | GET | Current dynamic parameters |
| `/api/failover/events` | GET | Recent failover event log |
| `/ws/telemetry` | WS | Real-time event stream |
| `/api/docs` | GET | Swagger / OpenAPI |

## Dry-Run Mode

Toggle **Dry-run** in the UI (or send `dry_run: true` in the API request body) to see routing decisions without calling any LLM. Useful for testing failover logic and threshold calculations.

## Logs

```bash
tail -f routing-v4/output/server.log
```
