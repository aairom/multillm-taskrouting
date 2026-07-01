"""
feedback.py
Records routing decisions and outcome signals.
Used to surface per-tier quality statistics and to guide future tuning.
"""

from __future__ import annotations
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class RoutingRecord:
    timestamp:    str    # ISO-8601
    task_type:    str
    complexity:   float
    tier:         int
    model_used:   str
    latency_ms:   int
    cost_units:   float   # cost_per_1k × output_tokens / 1000
    quality_eval: float   # auto-eval heuristic: 0.0 – 1.0
    prompt_len:   int     # character count of original prompt


class FeedbackStore:
    """Append-only JSONL store for routing records."""

    def __init__(self, path: str = "output/feedback.jsonl") -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._records: list[RoutingRecord] = self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> list[RoutingRecord]:
        if not self._path.exists():
            return []
        records = []
        with self._path.open() as fh:
            for line in fh:
                line = line.strip()
                if line:
                    records.append(RoutingRecord(**json.loads(line)))
        return records

    def record(
        self,
        task_type:    str,
        complexity:   float,
        tier:         int,
        model_used:   str,
        latency_ms:   int,
        output_tokens: int,
        cost_per_1k:  float,
        prompt_len:   int,
    ) -> None:
        quality_eval = self._heuristic_quality(latency_ms, output_tokens)
        cost_units   = cost_per_1k * output_tokens / 1000.0

        rec = RoutingRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            task_type=task_type,
            complexity=round(complexity, 3),
            tier=tier,
            model_used=model_used,
            latency_ms=latency_ms,
            cost_units=round(cost_units, 6),
            quality_eval=round(quality_eval, 3),
            prompt_len=prompt_len,
        )
        self._records.append(rec)
        with self._path.open("a") as fh:
            fh.write(json.dumps(asdict(rec)) + "\n")

    # ── Analytics ─────────────────────────────────────────────────────────────

    @staticmethod
    def _heuristic_quality(latency_ms: int, output_tokens: int) -> float:
        """
        Rough auto-eval: reward high token output at low latency.
        Real systems replace this with a judge-LLM or human rating.
        """
        if output_tokens == 0:
            return 0.0
        tokens_per_second = output_tokens / max(1, latency_ms / 1000)
        return min(1.0, 0.5 + tokens_per_second / 60)

    def summary(self) -> dict:
        if not self._records:
            return {"total_calls": 0}
        total_cost = sum(r.cost_units for r in self._records)
        avg_quality = sum(r.quality_eval for r in self._records) / len(self._records)
        by_tier: dict[int, int] = {}
        for r in self._records:
            by_tier[r.tier] = by_tier.get(r.tier, 0) + 1
        return {
            "total_calls":  len(self._records),
            "total_cost":   round(total_cost, 6),
            "avg_quality":  round(avg_quality, 3),
            "calls_by_tier": by_tier,
        }
