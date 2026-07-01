"""
router.py
Core routing logic: selects the cheapest model that meets the quality threshold
for each TaskProfile, using a utility function U = β·Q − α·C.
"""

from __future__ import annotations
from src.cost_registry import MODEL_REGISTRY, ModelSpec
from src.task_classifier import TaskProfile

# ── Tunable parameters ────────────────────────────────────────────────────────
QUALITY_THRESHOLD = 0.72   # default minimum acceptable quality score
COST_WEIGHT       = 0.40   # α — penalise cost
QUALITY_WEIGHT    = 0.60   # β — reward quality

# Per-task-type quality thresholds.
# Documentation / summaries tolerate lower quality from a cheap model;
# code and reasoning tasks require a higher bar.
TASK_QUALITY_THRESHOLDS: dict[str, float] = {
    "documentation":   0.60,   # light model acceptable for prose
    "summarisation":   0.55,   # even more lenient for summaries
    "qa_simple":       0.55,
    "code_generation": 0.72,
    "code_review":     0.85,   # security: high bar
    "reasoning":       0.80,
}

# Task types that require the heaviest tier (Tier 4) regardless of complexity score.
# code_review always goes to Mistral (security-aware, largest context)
SECURITY_OVERRIDES: set[str] = {"code_review"}


def _utility(model: ModelSpec, profile: TaskProfile) -> float:
    """
    Utility  U = β·Q − α·C
      Q = model.quality_score(complexity)   ∈ [0, 1]
      C = model.cost_per_1k (normalised)    ∈ [0, 1]
    A higher U means the model is preferred.
    """
    q = model.quality_score(profile.complexity)
    c = model.cost_per_1k
    return QUALITY_WEIGHT * q - COST_WEIGHT * c


def route(profile: TaskProfile) -> ModelSpec:
    """
    Return the optimal ModelSpec for the given TaskProfile.

    Selection rules (in order):
      1. Model must support the task type.
      2. Model context window must fit the estimated token budget.
      3. Model quality_score must meet QUALITY_THRESHOLD
         (unless it's a security override — then tier 3 is forced).
      4. Among qualifying candidates, the one with the highest utility wins.
      5. If no candidate passes the threshold, fall back to the highest-quality model.
    """
    ttype = profile.task_type.value

    # Force tier-4 (heaviest) for security-sensitive task types
    if ttype in SECURITY_OVERRIDES:
        heavy = next(m for m in MODEL_REGISTRY if m.tier == 4)
        return heavy

    threshold = TASK_QUALITY_THRESHOLDS.get(ttype, QUALITY_THRESHOLD)

    candidates = [
        m for m in MODEL_REGISTRY
        if ttype in m.capable_types
        and m.max_tokens >= profile.token_estimate
        and m.quality_score(profile.complexity) >= threshold
    ]

    if not candidates:
        # Safety net: pick highest-quality model regardless of cost
        candidates = sorted(
            MODEL_REGISTRY,
            key=lambda m: m.quality_score(profile.complexity),
            reverse=True,
        )

    return max(candidates, key=lambda m: _utility(m, profile))


def dispatch(profiles: list[TaskProfile]) -> dict[str, tuple[TaskProfile, ModelSpec]]:
    """
    Route each sub-task independently.

    Returns a mapping of task_type → (profile, selected_model).
    When multiple sub-tasks share the same type, a suffix is appended.
    """
    result: dict[str, tuple[TaskProfile, ModelSpec]] = {}
    type_counts: dict[str, int] = {}

    for profile in profiles:
        key = profile.task_type.value
        count = type_counts.get(key, 0)
        type_counts[key] = count + 1
        unique_key = key if count == 0 else f"{key}_{count}"
        result[unique_key] = (profile, route(profile))

    return result
