./multi-llm-router/scripts/demo.sh

Running the documentation-vs-code routing scenario…
(Set DRY_RUN=1 to skip LLM calls and inspect routing only)

================================================================================
  Multi-LLM Task Router  —  Demonstration Scenario  (4 providers)
================================================================================

Prompt:
  Write the API reference documentation for our REST /users endpoints AND implement the OAuth2 Bearer-token middleware in Python FastAPI.

Model tier mapping:
  model::light          IBM Granite     →  granite4.1:3b
  model::medium         Meta LLaMA      →  llama3.2:latest
  model::balanced       Google Gemma    →  gemma3:4b
  model::heavy          Mistral AI      →  mistral-small3.2:latest

Detected 2 sub-task(s):
  [1] TaskProfile(type='documentation', complexity=0.26, tier=LOW, tokens≈16)
  [2] TaskProfile(type='code_generation', complexity=0.609, tier=MEDIUM, tokens≈15)

Routing decisions:
  Task Type              Complexity  Tier       Label                Provider              U
  ------------------------------------------------------------------------------
  documentation               0.260  LOW        model::light         IBM Granite     +0.3616
  code_generation             0.609  MEDIUM     model::balanced      Google Gemma    +0.3718

Executing sub-tasks via Ollama…  (set DRY_RUN=1 to skip LLM calls)


================================================================================
  ROUTING TABLE
================================================================================
  Task Type              Label                Provider         Latency   Tokens        Cost
  ------------------------------------------------------------------------------
  documentation          model::light         IBM Granite       2839 ms       48    0.002400
  code_generation        model::balanced      Google Gemma     15279 ms       45    0.015750

  Total wall-clock: 15327 ms

======================================================================
  MERGED RESPONSE
======================================================================
## Documentation  _(via model::light, 2839 ms)_

# REST API Reference: `/users` Endpoints

Our RESTful API provides a set of endpoints under the `/users` resource to manage user-related operations. Below is a detailed description of each endpoint, including supported HTTP methods, request/response

---

## Code Generation  _(via model::balanced, 15279 ms)_

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import CredentialsTokenAuthentication
import jwt

# Replace with your secret key (keep this secure!)
JWT_SECRET = "your-secret-

======================================================================
  FEEDBACK SUMMARY
======================================================================
{
  "total_calls": 2,
  "total_cost": 0.01815,
  "avg_quality": 0.665,
  "calls_by_tier": {
    "1": 1,
    "3": 1
  }
}