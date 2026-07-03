"""
cost_registry.py  —  routing-v4
Model pool with 4 tiers + explicit failover chain definitions per task type.

Provider mapping:
  model::light    → IBM Granite   (granite4.1:3b)
  model::medium   → Meta LLaMA   (llama3.2:latest)
  model::balanced → Google Gemma  (gemma3:4b)
  model::heavy    → Mistral AI    (mistral-small3.2:latest)

Failover chains define the ordered list of models to try when a primary fails.
Each chain entry is (model_label, reason_tag) for telemetry visibility.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ModelSpec:
    label:         str
    tier:          int                        # 1 = light … 4 = heavy
    provider:      str
    cost_per_1k:   float                      # normalised: 1.0 = most expensive
    max_tokens:    int
    capable_types: set[str]
    quality_score: Callable[[float], float]   # complexity → quality [0, 1]
    # Failover chain: ordered list of (fallback_label, reason_tag)
    failover_chain: list[tuple[str, str]] = field(default_factory=list)

    def __repr__(self) -> str:
        return (
            f"ModelSpec(label={self.label!r}, tier={self.tier}, "
            f"provider={self.provider!r}, cost={self.cost_per_1k})"
        )


# ── 4-tier registry ───────────────────────────────────────────────────────────
MODEL_REGISTRY: list[ModelSpec] = [
    ModelSpec(
        label="model::light",
        tier=1,
        provider="IBM Granite",
        cost_per_1k=0.05,
        max_tokens=16_384,
        capable_types={"documentation", "summarisation", "qa_simple"},
        quality_score=lambda c: max(0.0, 1.0 - c * 1.4),
        failover_chain=[
            ("model::medium",   "light_degraded"),
            ("model::balanced", "light_circuit_open"),
        ],
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
        quality_score=lambda c: 0.72 + c * 0.08,
        failover_chain=[
            ("model::balanced", "medium_degraded"),
            ("model::heavy",    "medium_circuit_open"),
        ],
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
        quality_score=lambda c: 0.78 + c * 0.12,
        failover_chain=[
            ("model::heavy",  "balanced_degraded"),
            ("model::medium", "balanced_circuit_open"),
        ],
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
        quality_score=lambda c: 0.90 + c * 0.10,
        failover_chain=[
            ("model::balanced", "heavy_degraded"),
            ("model::medium",   "heavy_circuit_open"),
        ],
    ),
]

# Convenience lookup
MODEL_BY_LABEL: dict[str, ModelSpec] = {m.label: m for m in MODEL_REGISTRY}

# Per-task-type preferred failover ordering (used when the primary model is unavailable)
# Maps task_type → ordered list of model labels to try (excluding the blocked primary)
TASK_FAILOVER_PRIORITY: dict[str, list[str]] = {
    "documentation":   ["model::light", "model::medium", "model::balanced", "model::heavy"],
    "summarisation":   ["model::light", "model::medium", "model::balanced", "model::heavy"],
    "qa_simple":       ["model::light", "model::medium", "model::balanced", "model::heavy"],
    "code_generation": ["model::medium", "model::balanced", "model::heavy", "model::light"],
    "code_review":     ["model::heavy", "model::balanced", "model::medium", "model::light"],
    "reasoning":       ["model::balanced", "model::heavy", "model::medium", "model::light"],
}
