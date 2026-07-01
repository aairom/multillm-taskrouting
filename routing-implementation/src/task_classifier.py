"""
task_classifier.py
Classifies a text prompt into a TaskProfile: type, complexity score, and token estimate.
"""

from __future__ import annotations
import math
import re
from dataclasses import dataclass, field
from enum import Enum


class TaskType(Enum):
    DOCUMENTATION   = "documentation"    # READMEs, API docs, inline comments
    CODE_GENERATION = "code_generation"  # new functions / modules / classes
    CODE_REVIEW     = "code_review"      # diff analysis, security audit
    REASONING       = "reasoning"        # architecture, design decisions
    QA_SIMPLE       = "qa_simple"        # factual lookups, definitions
    SUMMARISATION   = "summarisation"    # condense / shorten text


class ComplexityTier(Enum):
    LOW    = 1   # score 0.00 – 0.34
    MEDIUM = 2   # score 0.35 – 0.64
    HIGH   = 3   # score 0.65 – 1.00


@dataclass
class TaskProfile:
    raw_text:       str
    task_type:      TaskType
    complexity:     float          # 0.0 → 1.0
    tier:           ComplexityTier
    token_estimate: int
    sub_tasks:      list["TaskProfile"] = field(default_factory=list)

    def __repr__(self) -> str:
        return (
            f"TaskProfile(type={self.task_type.value!r}, "
            f"complexity={self.complexity}, tier={self.tier.name}, "
            f"tokens≈{self.token_estimate})"
        )


# ── Keyword signal table: (keywords, base_complexity_score) ───────────────────
_SIGNALS: dict[TaskType, tuple[list[str], float]] = {
    TaskType.DOCUMENTATION:   (
        ["write the api", "api reference", "write docs", "write documentation",
         "document", "readme", "docstring", "comment",
         "explain", "describe"], 0.20),
    TaskType.CODE_GENERATION: (
        ["implement", "create function", "write code", "build",
         "develop", "middleware", "endpoint", "class", "module"], 0.55),
    TaskType.CODE_REVIEW:     (
        ["review", "audit", "security", "vulnerability",
         "diff", "check", "analyse code", "analyze code"], 0.60),
    TaskType.REASONING:       (
        ["architecture", "design", "trade-off", "compare",
         "evaluate", "pros and cons", "should i", "best approach"], 0.80),
    TaskType.QA_SIMPLE:       (
        ["what is", "how does", "define", "tell me", "when was"], 0.10),
    TaskType.SUMMARISATION:   (
        ["summarise", "summarize", "tldr", "shorten",
         "brief", "condense", "overview"], 0.15),
}

# Multi-word phrases that force a specific TaskType regardless of keyword scoring.
_PHRASE_OVERRIDES: list[tuple[str, TaskType]] = [
    ("api reference",       TaskType.DOCUMENTATION),
    ("write the api",       TaskType.DOCUMENTATION),
    ("write docs",          TaskType.DOCUMENTATION),
    ("write documentation", TaskType.DOCUMENTATION),
    ("code review",         TaskType.CODE_REVIEW),
    ("security audit",      TaskType.CODE_REVIEW),
]


def _token_estimate(text: str) -> int:
    """Rough GPT-style tokenisation: ~4 chars per token."""
    return max(1, len(text) // 4)


def _depth_penalty(text: str) -> float:
    """
    Extra score for multi-step / conditional reasoning markers.
    Each hit adds 0.04, capped at 0.20.
    """
    markers = [
        "step 1", "first,", "then,", "finally,",
        "however,", "alternatively,", "trade-off",
        "on the other hand", "in addition", "furthermore",
    ]
    lower = text.lower()
    hits = sum(1 for m in markers if m in lower)
    return min(0.20, hits * 0.04)


def classify(text: str) -> TaskProfile:
    """Return a TaskProfile for the given text snippet."""
    best_type, base_score = TaskType.QA_SIMPLE, 0.10
    lower = text.lower()

    # Phase 1: phrase-level overrides (highest priority)
    for phrase, forced_type in _PHRASE_OVERRIDES:
        if phrase in lower:
            best_type = forced_type
            base_score = dict(_SIGNALS)[forced_type][1]
            break
    else:
        # Phase 2: single-keyword scoring (only if no phrase matched)
        for ttype, (keywords, score) in _SIGNALS.items():
            if any(k in lower for k in keywords):
                if score > base_score:
                    best_type, base_score = ttype, score

    tokens       = _token_estimate(text)
    token_factor = min(0.15, math.log10(max(1, tokens)) * 0.05)
    depth        = _depth_penalty(text)
    final_score  = min(1.0, base_score + token_factor + depth)

    tier = (ComplexityTier.LOW    if final_score < 0.35 else
            ComplexityTier.MEDIUM if final_score < 0.65 else
            ComplexityTier.HIGH)

    return TaskProfile(
        raw_text=text,
        task_type=best_type,
        complexity=round(final_score, 3),
        tier=tier,
        token_estimate=tokens,
    )
