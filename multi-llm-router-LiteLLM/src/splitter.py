"""
splitter.py
Splits a compound prompt into independent clauses, then classifies each one.
"""

from __future__ import annotations
import re
from src.task_classifier import classify, TaskProfile


# Conjunctions that signal independent sub-tasks within a single prompt
_SPLIT_PATTERN = re.compile(
    r"(?i)\s*\b(and also|and then|additionally|plus|as well as|AND|also)\b\s*",
)


def split_and_classify(prompt: str) -> list[TaskProfile]:
    """
    1. Split the prompt on conjunction markers.
    2. Discard separator tokens.
    3. Classify each remaining clause.
    """
    raw_clauses = _SPLIT_PATTERN.split(prompt)

    # Keep only non-separator, non-empty parts
    clauses = [
        c.strip()
        for c in raw_clauses
        if c and not _SPLIT_PATTERN.match(c.strip()) and len(c.strip()) > 8
    ]

    if not clauses:
        # Fallback: treat the whole prompt as one task
        clauses = [prompt.strip()]

    return [classify(c) for c in clauses]
