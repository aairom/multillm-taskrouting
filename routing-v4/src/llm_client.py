"""
llm_client.py  —  routing-v4
Failover-aware LiteLLM async client.

After every call the result is reported back to the FailoverManager so
circuit-breaker state is updated in real time.
"""

from __future__ import annotations
import asyncio
import logging
import os
import time

import litellm
from litellm import Router

from src.failover_manager import failover_manager

litellm.success_callback = []
litellm.set_verbose = False
logging.getLogger("LiteLLM").setLevel(logging.ERROR)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_TIMEOUT  = int(os.getenv("OLLAMA_TIMEOUT", "120"))

_TIER_MODELS: dict[str, str] = {
    "model::light":    os.getenv("LLM_LIGHT",    "granite4.1:3b"),
    "model::medium":   os.getenv("LLM_MEDIUM",   "llama3.2:latest"),
    "model::balanced": os.getenv("LLM_BALANCED", "gemma3:4b"),
    "model::heavy":    os.getenv("LLM_HEAVY",    "mistral-small3.2:latest"),
}

# Fallback model names (secondary deployments for LiteLLM Router)
_FALLBACK_MODELS: dict[str, str] = {
    "model::light":    os.getenv("LLM_LIGHT_FALLBACK",    "llama3.2:latest"),
    "model::medium":   os.getenv("LLM_MEDIUM_FALLBACK",   "gemma3:4b"),
    "model::balanced": os.getenv("LLM_BALANCED_FALLBACK", "llama3.2:latest"),
    "model::heavy":    os.getenv("LLM_HEAVY_FALLBACK",    "gemma3:4b"),
}


def _build_model_list() -> list[dict]:
    """
    Build LiteLLM Router model list with 2 deployments per tier label:
      - Primary deployment (the configured Ollama model)
      - Fallback deployment (secondary, different Ollama model)
    This gives LiteLLM its own layer of retry/load-balance within a tier,
    while our FailoverManager handles cross-tier failover.
    """
    entries: list[dict] = []
    for tier_label, primary_model in _TIER_MODELS.items():
        entries.append({
            "model_name": tier_label,
            "litellm_params": {
                "model":    f"ollama/{primary_model}",
                "api_base": OLLAMA_BASE_URL,
                "timeout":  OLLAMA_TIMEOUT,
            },
        })
        fallback_model = _FALLBACK_MODELS.get(tier_label)
        if fallback_model and fallback_model != primary_model:
            entries.append({
                "model_name": tier_label,
                "litellm_params": {
                    "model":    f"ollama/{fallback_model}",
                    "api_base": OLLAMA_BASE_URL,
                    "timeout":  OLLAMA_TIMEOUT,
                },
            })
    return entries


_router = Router(
    model_list=_build_model_list(),
    routing_strategy="latency-based-routing",
    num_retries=2,
    retry_after=2,
    allowed_fails=3,
    cooldown_time=30,
    set_verbose=False,
)


def get_router() -> Router:
    return _router


async def call_model(
    model_label: str,
    prompt: str,
    max_tokens: int = 1024,
) -> tuple[str, float, int]:
    """
    Call a model tier via LiteLLM Router.
    Reports success/failure to the FailoverManager for circuit-breaker tracking.

    Returns (response_text, latency_seconds, output_tokens).
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
        text    = response.choices[0].message.content or ""
        tokens  = (
            response.usage.completion_tokens
            if response.usage
            else max(1, len(text) // 4)
        )
        failover_manager.record_success(model_label)
        return text, latency, tokens

    except Exception as exc:
        latency = time.perf_counter() - t0
        failover_manager.record_failure(model_label)
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
    return asyncio.run(call_model(model_label, prompt, max_tokens))


TIER_TO_MODEL: dict[str, str] = _TIER_MODELS
