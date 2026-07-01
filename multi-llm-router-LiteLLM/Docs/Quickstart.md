# Quickstart — Multi-LLM Task Router (LiteLLM Edition)

> Get up and running in under 5 minutes.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | `python3 --version` |
| Ollama | Latest | [ollama.ai](https://ollama.ai) — must be running (`ollama serve`) |
| Disk space | ~8 GB | For all 4 models |

---

## Step 1 — Pull Ollama models

```bash
ollama pull granite4.1:3b          # Tier 1 — IBM Granite  (docs, QA)
ollama pull llama3.2:latest         # Tier 2 — Meta LLaMA   (code, general)
ollama pull gemma3:4b               # Tier 3 — Google Gemma (reasoning)
ollama pull mistral-small3.2:latest # Tier 4 — Mistral AI   (security, arch)
```

Verify Ollama is running:

```bash
curl http://localhost:11434/api/tags
```

---

## Step 2 — Set up the Python environment

```bash
cd multi-llm-router-LiteLLM

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

LiteLLM will be installed automatically. It communicates with Ollama via
the `ollama/<model-name>` provider prefix.

---

## Step 3 — Configure environment

```bash
cp .env.example .env
```

Edit `.env` if you want to change model names or the Ollama URL:

```bash
OLLAMA_BASE_URL=http://localhost:11434
LLM_LIGHT=granite4.1:3b
LLM_MEDIUM=llama3.2:latest
LLM_BALANCED=gemma3:4b
LLM_HEAVY=mistral-small3.2:latest
```

---

## Step 4a — Run the demo scenario (terminal, no server needed)

Use the dedicated [`scripts/demo.sh`](../scripts/demo.sh) script — it handles
venv creation, dependency install, and `.env` bootstrap automatically:

```bash
chmod +x scripts/demo.sh
./scripts/demo.sh
```

Expected output:

```
┌──────────────────────────────────────────────────────────────┐
│  Multi-LLM Task Router — LiteLLM Edition  demo              │
│  Gateway: LiteLLM AI Router → Ollama (localhost:11434)      │
│                                                              │
│  Tip: set DRY_RUN=1 to inspect routing without LLM calls    │
└──────────────────────────────────────────────────────────────┘

================================================================================
  Multi-LLM Task Router  [LiteLLM Edition]  —  Demonstration Scenario
================================================================================

Prompt:
  Write the API reference documentation for our REST /users endpoints AND
  implement the OAuth2 Bearer-token middleware in Python FastAPI.

LiteLLM Gateway → Ollama at: http://localhost:11434

Model tier mapping (LiteLLM alias → Ollama model):
  model::light         (IBM Granite  )  →  ollama/granite4.1:3b
  model::medium        (Meta LLaMA   )  →  ollama/llama3.2:latest
  model::balanced      (Google Gemma )  →  ollama/gemma3:4b
  model::heavy         (Mistral AI   )  →  ollama/mistral-small3.2:latest

Detected 2 sub-task(s):
  [1] TaskProfile(type='documentation', complexity=0.258, tier=LOW, tokens≈19)
  [2] TaskProfile(type='code_generation', complexity=0.612, tier=MEDIUM, tokens≈14)

Routing decisions:
  Task Type              Complexity  Tier       Label                Provider              U
  ------------------------------------------------------------------------------
  documentation               0.258  LOW        model::light         IBM Granite     +0.5533
  code_generation             0.612  MEDIUM     model::balanced      Google Gemma    +0.3718

Executing sub-tasks via LiteLLM → Ollama…
```

**Dry-run mode** — inspect routing only, no LLM calls:

```bash
DRY_RUN=1 ./scripts/demo.sh
```

Expected dry-run banner:

```
┌──────────────────────────────────────────────────────────────┐
│  DRY RUN MODE — routing table shown, no LLM calls made      │
└──────────────────────────────────────────────────────────────┘
```

You can also invoke the scenario directly without the script:

```bash
# Activate venv first
source .venv/bin/activate
python app.py --mode demo
DRY_RUN=1 python app.py --mode demo
```

---

## Step 4b — Start the FastAPI server

```bash
# Using the provided script (detached mode):
chmod +x scripts/start.sh scripts/stop.sh
./scripts/start.sh

# Or directly:
python app.py --mode server --port 8080
```

The console prints the server URL:

```
╔══════════════════════════════════════════════════════════╗
║   Multi-LLM Task Router — LiteLLM Edition               ║
╠══════════════════════════════════════════════════════════╣
║   API:       http://localhost:8080                       ║
║   Docs:      http://localhost:8080/docs                  ║
║   Health:    http://localhost:8080/health                ║
║   Feedback:  http://localhost:8080/feedback              ║
╚══════════════════════════════════════════════════════════╝
```

---

## Step 5 — Call the API

### Route a prompt

```bash
curl -s -X POST http://localhost:8080/route \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Write the API docs AND implement the OAuth2 middleware",
    "dry_run": false
  }' | python3 -m json.tool
```

### Dry-run (routing only, no LLM calls)

```bash
curl -s -X POST http://localhost:8080/route \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Summarise this article AND design a caching architecture", "dry_run": true}' \
  | python3 -m json.tool
```

### Get routing statistics

```bash
curl -s http://localhost:8080/feedback | python3 -m json.tool
```

---

## Stop the server

```bash
./scripts/stop.sh
```

---

## Scripts reference

| Script | Purpose | Key option |
|---|---|---|
| `scripts/demo.sh` | Run the worked scenario in the terminal (no server needed) | `DRY_RUN=1` to skip LLM calls |
| `scripts/start.sh` | Start the FastAPI server in detached mode | `PORT=8090` to change port |
| `scripts/stop.sh` | Gracefully stop the running server | — |

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Connection refused` on port 11434 | Start Ollama: `ollama serve` |
| `model not found` error | Pull the model: `ollama pull <model-name>` |
| LiteLLM `ReadTimeout` | Increase `OLLAMA_TIMEOUT` in `.env` |
| `ModuleNotFoundError: litellm` | Activate venv and run `pip install -r requirements.txt` |
| Port 8080 already in use | `PORT=8090 ./scripts/start.sh` |
| `demo.sh: permission denied` | `chmod +x scripts/demo.sh` |

---

## Key differences from `multi-llm-router`

1. **LiteLLM Router** replaces the raw `httpx` client — all calls go through
   `litellm.Router.acompletion()` which adds retries, cooldowns and fallbacks
   transparently.
2. Model names use the `ollama/<name>` **provider prefix** instead of the
   Ollama `/api/generate` endpoint directly.
3. Responses follow the **OpenAI chat completion format**
   (`response.choices[0].message.content`) — drop-in compatible with any
   OpenAI-spec client.
4. To swap a tier to a cloud model, only change `.env` — e.g.:
   ```
   LLM_HEAVY=gpt-4o
   OPENAI_API_KEY=sk-...
   ```
