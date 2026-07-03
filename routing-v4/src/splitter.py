"""
splitter.py  —  routing-v4
Splits a compound prompt into independent clauses then classifies each one.
"""

from __future__ import annotations
import re
from src.task_classifier import classify, TaskProfile

_SPLIT_PATTERN = re.compile(
    r"(?i)\s*\b(and also|and then|additionally|plus|as well as|AND|also)\b\s*",
)


def split_and_classify(prompt: str) -> list[TaskProfile]:
    raw_clauses = _SPLIT_PATTERN.split(prompt)
    clauses = [
        c.strip()
        for c in raw_clauses
        if c and not _SPLIT_PATTERN.match(c.strip()) and len(c.strip()) > 8
    ]
    if not clauses:
        clauses = [prompt.strip()]
    return [classify(c) for c in clauses]
