"""
cost_registry.py
Defines the abstract model pool with 4 tiers spanning 4 different LLM providers.
No real model names are hard-coded here — only symbolic tier labels and
capability profiles.  The concrete model names live in llm_client.py / .env.

Provider mapping:
  model::light    →  IBM Granite   (granite4.1:3b)
  model::medium   →  Meta LLaMA   (llama3.2:latest)
  model::balanced →  Google Gemma  (gemma3:4b)
  model::heavy    →  Mistral AI    (mistral-small3.2:latest)
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Callable


@dataclass
class ModelSpec:
    label:         str
    tier:          int                       # 1 = light … 4 = heavy
    provider:      str                       # human-readable provider name
    cost_per_1k:   float                     # normalised: 1.0 = most expensive
    max_tokens:    int                       # context window
    capable_types: set[str]                  # TaskType values handled well
    quality_score: Callable[[float], float]  # complexity → expected quality [0,1]

    def __repr__(self) -> str:
        return (
            f"ModelSpec(label={self.label!r}, tier={self.tier}, "
            f"provider={self.provider!r}, cost={self.cost_per_1k})"
        )


# ── Synthetic 4-tier registry ─────────────────────────────────────────────────
#
# quality_score(complexity) characteristics:
#   light    — degrades fast above 0.4 (small model, poor at deep reasoning)
#   medium   — solid mid-range; slight improvement at higher complexity
#   balanced — strong baseline, plateaus well — ideal for structured tasks
#   heavy    — near-ceiling at all complexity levels; only model for security tasks
#
MODEL_REGISTRY: list[ModelSpec] = [
    ModelSpec(
        label="model::light",
        tier=1,
        provider="IBM Granite",
        cost_per_1k=0.05,
        max_tokens=16_384,
        capable_types={
            "documentation", "summarisation", "qa_simple",
        },
        # fast deterioration above complexity 0.5
        quality_score=lambda c: max(0.0, 1.0 - c * 1.4),
    ),
    ModelSpec(
        label="model::medium",
        tier=2,
        provider="Meta LLaMA",
        cost_per_1k=0.28,
        max_tokens=32_768,
        capable_types={
            "code_generation", "documentation",
            "qa_simple", "summarisation",
        },
        # solid performer; modest quality gain with complexity
        quality_score=lambda c: 0.72 + c * 0.08,
    ),
    ModelSpec(
        label="model::balanced",
        tier=3,
        provider="Google Gemma",
        cost_per_1k=0.35,
        max_tokens=32_768,
        capable_types={
            "code_generation", "code_review",
            "documentation", "qa_simple",
            "summarisation", "reasoning",
        },
        # strong reasoning; quality improves steadily with complexity
        quality_score=lambda c: 0.78 + c * 0.12,
    ),
    ModelSpec(
        label="model::heavy",
        tier=4,
        provider="Mistral AI",
        cost_per_1k=1.00,
        max_tokens=128_000,
        capable_types={
            "code_generation", "code_review",
            "reasoning", "documentation",
            "summarisation", "qa_simple",
        },
        # near-ceiling quality at any complexity
        quality_score=lambda c: 0.90 + c * 0.10,
    ),
]
