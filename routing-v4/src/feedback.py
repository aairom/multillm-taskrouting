"""
feedback.py  —  routing-v4
Append-only JSONL store for routing records.
Enhanced with per-model statistics, failover tracking, and threshold history.
"""

from __future__ import annotations
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict


@dataclass
class RoutingRecord:
    timestamp:      str
    task_type:      str
    complexity:     float
    tier:           int
    model_used:     str
    latency_ms:     int
    cost_units:     float
    quality_eval:   float
    prompt_len:     int
    failover_used:  bool   = False
    failover_from:  str    = ""
    failover_reason: str   = ""


class FeedbackStore:
    """Append-only JSONL store with richer per-model analytics."""

    def __init__(self, path: str = "output/feedback.jsonl") -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._records: list[RoutingRecord] = self._load()

    def _load(self) -> list[RoutingRecord]:
        if not self._path.exists():
            return []
        records = []
        with self._path.open() as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        d = json.loads(line)
                        # Backfill missing fields from older records
                        d.setdefault("failover_used",   False)
                        d.setdefault("failover_from",   "")
                        d.setdefault("failover_reason", "")
                        records.append(RoutingRecord(**d))
                    except Exception:
                        pass
        return records

    def record(
        self,
        task_type:       str,
        complexity:      float,
        tier:            int,
        model_used:      str,
        latency_ms:      int,
        output_tokens:   int,
        cost_per_1k:     float,
        prompt_len:      int,
        failover_used:   bool = False,
        failover_from:   str  = "",
        failover_reason: str  = "",
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
            failover_used=failover_used,
            failover_from=failover_from,
            failover_reason=failover_reason,
        )
        self._records.append(rec)
        with self._path.open("a") as fh:
            fh.write(json.dumps(asdict(rec)) + "\n")

    @staticmethod
    def _heuristic_quality(latency_ms: int, output_tokens: int) -> float:
        if output_tokens == 0:
            return 0.0
        tps = output_tokens / max(1, latency_ms / 1000)
        return min(1.0, 0.5 + tps / 60)

    def summary(self) -> dict:
        if not self._records:
            return {"total_calls": 0}
        total_cost     = sum(r.cost_units   for r in self._records)
        avg_quality    = sum(r.quality_eval for r in self._records) / len(self._records)
        avg_latency    = sum(r.latency_ms   for r in self._records) / len(self._records)
        failover_count = sum(1 for r in self._records if r.failover_used)

        by_tier: dict[int, int] = {}
        for r in self._records:
            by_tier[r.tier] = by_tier.get(r.tier, 0) + 1

        by_model: dict[str, dict] = defaultdict(
            lambda: {"calls": 0, "total_latency_ms": 0, "total_cost": 0.0, "total_quality": 0.0}
        )
        for r in self._records:
            s = by_model[r.model_used]
            s["calls"]            += 1
            s["total_latency_ms"] += r.latency_ms
            s["total_cost"]       += r.cost_units
            s["total_quality"]    += r.quality_eval

        model_stats = {}
        for label, s in by_model.items():
            c = s["calls"]
            model_stats[label] = {
                "calls":       c,
                "avg_latency": round(s["total_latency_ms"] / c),
                "avg_cost":    round(s["total_cost"] / c, 6),
                "avg_quality": round(s["total_quality"] / c, 3),
            }

        return {
            "total_calls":    len(self._records),
            "total_cost":     round(total_cost, 6),
            "avg_quality":    round(avg_quality, 3),
            "avg_latency_ms": round(avg_latency),
            "failover_count": failover_count,
            "calls_by_tier":  by_tier,
            "by_model":       model_stats,
        }
