"""
llm_client.py  —  LiteLLM-powered async LLM client
Backend: Ollama (local) accessed via the LiteLLM AI Gateway Router.

LiteLLM Router advantages over raw httpx calls:
  • Automatic retries with exponential back-off
  • Per-model cooldown after repeated failures
  • Transparent fallback chain across deployments
  • OpenAI-compatible response format (response.choices[0].message.content)
  • Pluggable routing strategies (simple-shuffle, latency-based, cost-based …)

Model tier mapping (all via Ollama, overridable via env):
  model::light    →  ollama/granite4.1:3b          IBM Granite  (docs, QA, summaries)
  model::medium   →  ollama/llama3.2:latest         Meta LLaMA   (code, CRUD, general)
  model::balanced →  ollama/gemma3:4b               Google Gemma (reasoning, analysis)
  model::heavy    →  ollama/mistral-small3.2:latest  Mistral AI   (security, auth, arch)
"""

from __future__ import annotations
import asyncio
import os
import time

import litellm
from litellm import Router

# ── Silence verbose LiteLLM logs ─────────────────────────────────────────────
litellm.success_callback = []
litellm.set_verbose = False
# Suppress "model not in built-in cost map" warnings for local Ollama models
import logging
logging.getLogger("LiteLLM").setLevel(logging.ERROR)

# ── Ollama base URL ────────────────────────────────────────────────────────────
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_TIMEOUT  = int(os.getenv("OLLAMA_TIMEOUT", "120"))

# ── Tier → Ollama model name (overridable via env) ────────────────────────────
_TIER_MODELS: dict[str, str] = {
    "model::light":    os.getenv("LLM_LIGHT",    "granite4.1:3b"),
    "model::medium":   os.getenv("LLM_MEDIUM",   "llama3.2:latest"),
    "model::balanced": os.getenv("LLM_BALANCED", "gemma3:4b"),
    "model::heavy":    os.getenv("LLM_HEAVY",    "mistral-small3.2:latest"),
}

# ── LiteLLM Router model_list ─────────────────────────────────────────────────
# Each entry maps a symbolic tier alias (model_name) to a concrete Ollama model.
# The `ollama/<name>` prefix tells LiteLLM to route through the Ollama backend.
# Adding multiple entries per model_name enables load-balancing and failover.
def _build_model_list() -> list[dict]:
    return [
        {
            "model_name": tier_label,
            "litellm_params": {
                "model": f"ollama/{ollama_model}",
                "api_base": OLLAMA_BASE_URL,
                "timeout": OLLAMA_TIMEOUT,
            },
        }
        for tier_label, ollama_model in _TIER_MODELS.items()
    ]


# ── Singleton router (created once at module import) ──────────────────────────
# routing_strategy="simple-shuffle" (default): randomly picks among deployments
# that share the same model_name (useful when you add multiple Ollama nodes).
# Swap to "latency-based-routing" for production multi-node setups.
_router = Router(
    model_list=_build_model_list(),
    routing_strategy="simple-shuffle",
    num_retries=2,
    retry_after=2,          # seconds between retries
    allowed_fails=3,        # cooldown after this many consecutive failures
    cooldown_time=30,       # cooldown duration in seconds
    set_verbose=False,
)

# Public accessor — allows tests to inject a custom router
def get_router() -> Router:
    return _router


async def call_model(
    model_label: str,
    prompt: str,
    max_tokens: int = 1024,
) -> tuple[str, float, int]:
    """
    Call a model tier via the LiteLLM Router.

    Parameters
    ----------
    model_label : str
        Symbolic tier alias, e.g. ``"model::light"``.
    prompt : str
        User / task prompt text.
    max_tokens : int
        Upper bound on generated tokens.

    Returns
    -------
    (response_text, latency_seconds, output_tokens)
    """
    messages = [{"role": "user", "content": prompt}]

    t0 = time.perf_counter()
    try:
        response = await _router.acompletion(
            model=model_label,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.3,
        )
        latency = time.perf_counter() - t0

        text   = response.choices[0].message.content or ""
        tokens = (
            response.usage.completion_tokens
            if response.usage
            else max(1, len(text) // 4)
        )
        return text, latency, tokens

    except Exception as exc:  # noqa: BLE001
        latency = time.perf_counter() - t0
        real_model = _TIER_MODELS.get(model_label, model_label)
        return (
            f"[LiteLLM ERROR — {real_model}: {exc}]",
            latency,
            0,
        )


def call_model_sync(
    model_label: str,
    prompt: str,
    max_tokens: int = 1024,
) -> tuple[str, float, int]:
    """Synchronous wrapper around call_model for non-async contexts."""
    return asyncio.run(call_model(model_label, prompt, max_tokens))


# ── Convenience: expose the tier→model mapping for display ────────────────────
TIER_TO_MODEL: dict[str, str] = _TIER_MODELS
