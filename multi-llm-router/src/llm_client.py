"""
llm_client.py
Thin async LLM client.  Backend: Ollama (local).
The model label is resolved from the tier registry to the configured
Ollama model name via TIER_TO_MODEL.  Swap any entry to point at a
remote API by replacing the Ollama endpoint with an OpenAI-compatible URL.

Default 4-tier model mapping (all locally available via Ollama):
  Tier 1  model::light     →  granite4.1:3b          IBM Granite    (fast, cheap, docs/QA)
  Tier 2  model::medium    →  llama3.2:latest         Meta LLaMA     (general code, CRUD)
  Tier 3  model::balanced  →  gemma3:4b               Google Gemma   (balanced reasoning)
  Tier 4  model::heavy     →  mistral-small3.2:latest Mistral AI     (security, auth, arch)

Override via environment variables:
  LLM_LIGHT / LLM_MEDIUM / LLM_BALANCED / LLM_HEAVY
"""

from __future__ import annotations
import asyncio
import os
import time
import httpx

# ── Tier → real model mapping ─────────────────────────────────────────────────
# Tier 1 — IBM Granite 4.1 3B  : fastest, smallest — docs, summaries, QA
# Tier 2 — Meta LLaMA 3.2      : balanced, general-purpose — code, CRUD, SQL
# Tier 3 — Google Gemma 3 4B   : strong reasoning, low footprint — tests, analysis
# Tier 4 — Mistral Small 3.2   : largest, multi-lingual — security, auth, architecture
TIER_TO_MODEL: dict[str, str] = {
    "model::light":    os.getenv("LLM_LIGHT",    "granite4.1:3b"),
    "model::medium":   os.getenv("LLM_MEDIUM",   "llama3.2:latest"),
    "model::balanced": os.getenv("LLM_BALANCED", "gemma3:4b"),
    "model::heavy":    os.getenv("LLM_HEAVY",    "mistral-small3.2:latest"),
}

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_TIMEOUT  = int(os.getenv("OLLAMA_TIMEOUT", "120"))


async def call_model(
    model_label: str,
    prompt: str,
    max_tokens: int = 1024,
) -> tuple[str, float, int]:
    """
    Call the Ollama /api/generate endpoint for the given symbolic model label.

    Returns
    -------
    (response_text, latency_seconds, output_tokens)
    """
    real_model = TIER_TO_MODEL.get(model_label, TIER_TO_MODEL["model::heavy"])
    url = f"{OLLAMA_BASE_URL}/api/generate"

    payload = {
        "model":  real_model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_predict": max_tokens,
            "temperature": 0.3,
        },
    }

    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        latency = time.perf_counter() - t0
        return (
            f"[ERROR calling {real_model}: {exc}]",
            latency,
            0,
        )

    latency = time.perf_counter() - t0
    text    = data.get("response", "")
    tokens  = data.get("eval_count", len(text) // 4)
    return text, latency, tokens


def call_model_sync(
    model_label: str,
    prompt: str,
    max_tokens: int = 1024,
) -> tuple[str, float, int]:
    """Synchronous wrapper around call_model for non-async contexts."""
    return asyncio.run(call_model(model_label, prompt, max_tokens))
