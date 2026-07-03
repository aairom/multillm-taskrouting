"""
router.py  —  routing-v4
=========================
Core routing logic enhanced with:
  · Dynamic quality thresholds from the telemetry engine
  · Failover-aware model resolution via the failover manager
  · Per-task utility function  U = β(t)·Q − α(t)·C
    where α and β are continuously adjusted per (model, task_type) pair
"""

from __future__ import annotations

from src.cost_registry import MODEL_REGISTRY, MODEL_BY_LABEL, TASK_FAILOVER_PRIORITY, ModelSpec
from src.task_classifier import TaskProfile
from src.failover_manager import failover_manager, FailoverEvent
from src.telemetry import telemetry_engine

# ── Static fallback parameters (used before telemetry has data) ───────────────
BASE_QUALITY_THRESHOLD = 0.72
BASE_COST_WEIGHT       = 0.40
BASE_QUALITY_WEIGHT    = 0.60

STATIC_TASK_THRESHOLDS: dict[str, float] = {
    "documentation":   0.60,
    "summarisation":   0.55,
    "qa_simple":       0.55,
    "code_generation": 0.72,
    "code_review":     0.85,
    "reasoning":       0.80,
}

SECURITY_OVERRIDES: set[str] = {"code_review"}


# ── Utility function ──────────────────────────────────────────────────────────

def _utility(model: ModelSpec, profile: TaskProfile) -> float:
    """
    U = β·Q − α·C   with dynamic α and β from the telemetry engine.
    """
    alpha = telemetry_engine.get_cost_weight(model.label, profile.task_type.value)
    beta  = 1.0 - alpha
    q     = model.quality_score(profile.complexity)
    c     = model.cost_per_1k
    return beta * q - alpha * c


def _effective_threshold(model_label: str, task_type: str) -> float:
    """
    Blend the static task-level threshold with the live telemetry threshold.
    The dynamic value wins once there are enough samples.
    """
    static_thr  = STATIC_TASK_THRESHOLDS.get(task_type, BASE_QUALITY_THRESHOLD)
    dynamic_thr = telemetry_engine.get_threshold(model_label, task_type)
    return round((static_thr + dynamic_thr) / 2.0, 4)


# ── Primary routing ───────────────────────────────────────────────────────────

def route(profile: TaskProfile) -> tuple[ModelSpec, FailoverEvent | None]:
    """
    Return (selected_model, failover_event_or_None) for the given TaskProfile.

    Selection rules:
      1. Security overrides → always tier-4 (then failover if circuit open)
      2. Filter by capability + context window
      3. Filter by blended quality threshold
      4. Best utility wins
      5. Safety net: highest quality model if no candidate passes threshold
      6. Resolve failover if the chosen model's circuit is not callable
    """
    ttype = profile.task_type.value

    if ttype in SECURITY_OVERRIDES:
        primary = next(m for m in MODEL_REGISTRY if m.tier == 4)
        return failover_manager.resolve(primary, ttype)

    threshold = _effective_threshold("", ttype)  # task-level threshold (no model prefix)

    candidates = [
        m for m in MODEL_REGISTRY
        if ttype in m.capable_types
        and m.max_tokens >= profile.token_estimate
        and m.quality_score(profile.complexity) >= threshold
    ]

    if not candidates:
        candidates = sorted(
            MODEL_REGISTRY,
            key=lambda m: m.quality_score(profile.complexity),
            reverse=True,
        )

    primary = max(candidates, key=lambda m: _utility(m, profile))
    return failover_manager.resolve(primary, ttype)


def dispatch(
    profiles: list[TaskProfile],
) -> dict[str, tuple[TaskProfile, ModelSpec, FailoverEvent | None]]:
    """
    Route each sub-task independently.
    Returns mapping of unique_key → (profile, selected_model, failover_event).
    """
    result: dict[str, tuple[TaskProfile, ModelSpec, FailoverEvent | None]] = {}
    type_counts: dict[str, int] = {}

    for profile in profiles:
        key   = profile.task_type.value
        count = type_counts.get(key, 0)
        type_counts[key] = count + 1
        unique_key = key if count == 0 else f"{key}_{count}"
        model, failover_event = route(profile)
        result[unique_key] = (profile, model, failover_event)

    return result
