"""
task_classifier.py  —  routing-v4
Classifies a text prompt into a TaskProfile: type, complexity score, token estimate.
"""

from __future__ import annotations
import math
import re
from dataclasses import dataclass, field
from enum import Enum


class TaskType(Enum):
    DOCUMENTATION   = "documentation"
    CODE_GENERATION = "code_generation"
    CODE_REVIEW     = "code_review"
    REASONING       = "reasoning"
    QA_SIMPLE       = "qa_simple"
    SUMMARISATION   = "summarisation"


class ComplexityTier(Enum):
    LOW    = 1   # 0.00 – 0.34
    MEDIUM = 2   # 0.35 – 0.64
    HIGH   = 3   # 0.65 – 1.00


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


_SIGNALS: dict[TaskType, tuple[list[str], float]] = {
    TaskType.DOCUMENTATION:   (
        ["write the api", "api reference", "write docs", "write documentation",
         "document", "readme", "docstring", "comment", "explain", "describe"], 0.20),
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

_PHRASE_OVERRIDES: list[tuple[str, TaskType]] = [
    ("api reference",       TaskType.DOCUMENTATION),
    ("write the api",       TaskType.DOCUMENTATION),
    ("write docs",          TaskType.DOCUMENTATION),
    ("write documentation", TaskType.DOCUMENTATION),
    ("code review",         TaskType.CODE_REVIEW),
    ("security audit",      TaskType.CODE_REVIEW),
]


def _token_estimate(text: str) -> int:
    return max(1, len(text) // 4)


def _depth_penalty(text: str) -> float:
    markers = [
        "step 1", "first,", "then,", "finally,",
        "however,", "alternatively,", "trade-off",
        "on the other hand", "in addition", "furthermore",
    ]
    lower = text.lower()
    hits = sum(1 for m in markers if m in lower)
    return min(0.20, hits * 0.04)


def classify(text: str) -> TaskProfile:
    best_type, base_score = TaskType.QA_SIMPLE, 0.10
    lower = text.lower()

    for phrase, forced_type in _PHRASE_OVERRIDES:
        if phrase in lower:
            best_type = forced_type
            base_score = dict(_SIGNALS)[forced_type][1]
            break
    else:
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
