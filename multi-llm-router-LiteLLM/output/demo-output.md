./multi-llm-router-LiteLLM/scripts/demo.sh
[demo] Verifying dependencies (litellm, fastapi, uvicorn)…

[notice] A new release of pip is available: 25.0.1 -> 26.1.2
[notice] To update, run: pip install --upgrade pip

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
  Write the API reference documentation for our REST /users endpoints AND implement the OAuth2 Bearer-token middleware in Python FastAPI.

LiteLLM Gateway → Ollama at: http://localhost:11434

Model tier mapping (LiteLLM alias → Ollama model):
  model::light          (IBM Granite   )  →  ollama/granite4.1:3b
  model::medium         (Meta LLaMA    )  →  ollama/llama3.2:latest
  model::balanced       (Google Gemma  )  →  ollama/gemma3:4b
  model::heavy          (Mistral AI    )  →  ollama/mistral-small3.2:latest

Detected 2 sub-task(s):
  [1] TaskProfile(type='documentation', complexity=0.26, tier=LOW, tokens≈16)
  [2] TaskProfile(type='code_generation', complexity=0.609, tier=MEDIUM, tokens≈15)

Routing decisions:
  Task Type              Complexity  Tier       Label                Provider              U
  ------------------------------------------------------------------------------
  documentation               0.260  LOW        model::light         IBM Granite     +0.3616
  code_generation             0.609  MEDIUM     model::balanced      Google Gemma    +0.3718

Executing sub-tasks via LiteLLM → Ollama…  (set DRY_RUN=1 to skip)


================================================================================
  ROUTING TABLE  (via LiteLLM AI Gateway)
================================================================================
  Task Type              Label                Provider         Latency   Tokens        Cost
  ------------------------------------------------------------------------------
  documentation          model::light         IBM Granite       2720 ms       48    0.002400
  code_generation        model::balanced      Google Gemma      5595 ms       45    0.015750

  Total wall-clock: 5601 ms

======================================================================
  MERGED RESPONSE
======================================================================
## Documentation  _(via model::light [IBM Granite], 2720 ms)_

# API Reference: `/users` Endpoints

Our RESTful API provides a set of endpoints under the `/users` resource to manage user-related operations. Below is the detailed documentation for each endpoint, including request methods, expected input parameters,

---

## Code Generation  _(via model::balanced [Google Gemma], 5595 ms)_

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import CredentialsTokenAuthentication
import jwt  # You'll need to install this: pip install PyJWT


async def authenticate(token: str

======================================================================
  FEEDBACK SUMMARY
======================================================================
{
  "total_calls": 2,
  "total_cost": 0.01815,
  "avg_quality": 0.714,
  "calls_by_tier": {
    "1": 1,
    "3": 1
  }
}