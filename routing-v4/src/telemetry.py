"""
telemetry.py  —  routing-v4
============================
Live telemetry engine with dynamic threshold optimisation.

Data model
----------
For each (model_label, task_type) pair we maintain a fixed-size ring buffer
of the most recent N call records.  From that buffer we continuously compute:

  · p50 / p95 latency        (sorted ring buffer)
  · EMA quality score        (exponential moving average)
  · EMA cost efficiency      (tokens / cost_units)
  · success rate             (fraction of non-error calls)

Dynamic threshold tuner
-----------------------
Every time a new record lands, the tuner re-evaluates the QUALITY_THRESHOLD
and COST_WEIGHT for the affected (model, task_type) pair using:

  new_threshold = clip(
      BASE_THRESHOLD + k * (observed_quality_ema - BASE_THRESHOLD),
      MIN_THRESHOLD, MAX_THRESHOLD
  )

  new_cost_weight = clip(
      BASE_COST_WEIGHT * (1 - latency_pressure),
      MIN_COST_WEIGHT, MAX_COST_WEIGHT
  )

where:
  · latency_pressure = p95_latency_ms / TARGET_LATENCY_MS
    (if p95 >> target → reduce cost weight to prefer faster/cheaper models)

All threshold adjustments are broadcast via the event queue so the router
always reads the latest values and the UI receives real-time updates.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from dataclasses import dataclass, asdict
from threading import Lock
from typing import Deque


# ── Tunables (env-overridable) ────────────────────────────────────────────────
_WINDOW         = int(os.getenv("TELEMETRY_WINDOW", "50"))
_EMA_ALPHA      = float(os.getenv("EMA_ALPHA", "0.15"))

_BASE_THRESHOLD     = 0.72
_MIN_THRESHOLD      = 0.40
_MAX_THRESHOLD      = 0.95
_BASE_COST_WEIGHT   = 0.40
_MIN_COST_WEIGHT    = 0.10
_MAX_COST_WEIGHT    = 0.70
_TARGET_LATENCY_MS  = 3_000.0   # ms — target p95 latency


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class TelemetryRecord:
    model_label:  str
    task_type:    str
    latency_ms:   int
    out_tokens:   int
    cost_units:   float
    quality_eval: float   # 0–1 heuristic
    success:      bool    # False if the call returned an error string
    timestamp:    float = 0.0

    def __post_init__(self) -> None:
        if self.timestamp == 0.0:
            self.timestamp = time.time()


@dataclass
class DynamicParams:
    """Current per-(model, task_type) dynamic routing parameters."""
    model_label:       str
    task_type:         str
    quality_threshold: float
    cost_weight:       float
    quality_ema:       float
    p50_latency_ms:    float
    p95_latency_ms:    float
    success_rate:      float
    sample_count:      int
    last_updated:      float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["last_updated"] = self.last_updated
        return d


# ── Telemetry engine ──────────────────────────────────────────────────────────

class TelemetryEngine:
    """
    Thread-safe ring-buffer store + dynamic parameter calculator.
    Async-friendly: threshold updates are pushed onto an asyncio.Queue
    that the WebSocket broadcaster subscribes to.
    """

    def __init__(self) -> None:
        # (model_label, task_type) → ring buffer of TelemetryRecord
        self._buffers: dict[tuple[str, str], Deque[TelemetryRecord]] = {}
        # (model_label, task_type) → current DynamicParams
        self._params:  dict[tuple[str, str], DynamicParams] = {}
        # Global per-model EMA quality (used as fallback when task-level buffer is empty)
        self._model_quality_ema: dict[str, float] = {}
        self._lock = Lock()
        # Async event queue — consumed by the WS broadcaster in app.py
        self._event_queue: asyncio.Queue | None = None

    # ── Setup ─────────────────────────────────────────────────────────────────

    def set_event_queue(self, q: asyncio.Queue) -> None:
        self._event_queue = q

    # ── Ingest ────────────────────────────────────────────────────────────────

    def record(self, rec: TelemetryRecord) -> DynamicParams:
        """Append a record and recompute dynamic parameters. Returns updated params."""
        key = (rec.model_label, rec.task_type)
        with self._lock:
            if key not in self._buffers:
                self._buffers[key] = deque(maxlen=_WINDOW)
            self._buffers[key].append(rec)
            params = self._recompute(key)
            self._params[key] = params
            # Update global model EMA
            prev = self._model_quality_ema.get(rec.model_label, rec.quality_eval)
            self._model_quality_ema[rec.model_label] = (
                _EMA_ALPHA * rec.quality_eval + (1.0 - _EMA_ALPHA) * prev
            )
        # Non-blocking push to event queue (fire-and-forget)
        if self._event_queue is not None:
            try:
                self._event_queue.put_nowait({
                    "type":   "threshold_update",
                    "params": params.to_dict(),
                })
            except asyncio.QueueFull:
                pass
        return params

    # ── Query ─────────────────────────────────────────────────────────────────

    def get_threshold(self, model_label: str, task_type: str) -> float:
        key = (model_label, task_type)
        with self._lock:
            p = self._params.get(key)
        return p.quality_threshold if p else _BASE_THRESHOLD

    def get_cost_weight(self, model_label: str, task_type: str) -> float:
        key = (model_label, task_type)
        with self._lock:
            p = self._params.get(key)
        return p.cost_weight if p else _BASE_COST_WEIGHT

    def get_all_params(self) -> list[dict]:
        with self._lock:
            return [p.to_dict() for p in self._params.values()]

    def get_model_quality_ema(self, model_label: str) -> float:
        with self._lock:
            return self._model_quality_ema.get(model_label, 1.0)

    def recent_records(self, limit: int = 100) -> list[dict]:
        """Flat list of the most recent records across all buffers."""
        with self._lock:
            all_recs: list[TelemetryRecord] = []
            for buf in self._buffers.values():
                all_recs.extend(buf)
        all_recs.sort(key=lambda r: r.timestamp)
        tail = all_recs[-limit:]
        return [asdict(r) for r in tail]

    # ── Internal ──────────────────────────────────────────────────────────────

    def _recompute(self, key: tuple[str, str]) -> DynamicParams:
        model_label, task_type = key
        buf = list(self._buffers[key])
        n   = len(buf)

        # Quality EMA
        q_ema = buf[0].quality_eval
        for r in buf[1:]:
            q_ema = _EMA_ALPHA * r.quality_eval + (1.0 - _EMA_ALPHA) * q_ema

        # Latency percentiles
        latencies = sorted(r.latency_ms for r in buf)
        p50 = latencies[int(n * 0.50)] if n else 0
        p95 = latencies[min(n - 1, int(n * 0.95))] if n else 0

        # Success rate
        success_rate = sum(1 for r in buf if r.success) / n if n else 1.0

        # --- Dynamic quality threshold ---
        # If observed quality is consistently above baseline → relax threshold
        # If observed quality drops → tighten threshold
        delta    = q_ema - _BASE_THRESHOLD
        new_thr  = _BASE_THRESHOLD + 0.5 * delta
        new_thr  = max(_MIN_THRESHOLD, min(_MAX_THRESHOLD, new_thr))

        # --- Dynamic cost weight ---
        # If p95 latency is high → lower cost weight (prefer speed over cost savings)
        latency_pressure = p95 / _TARGET_LATENCY_MS
        cost_w = _BASE_COST_WEIGHT * (1.0 - min(0.5, latency_pressure * 0.3))
        cost_w = max(_MIN_COST_WEIGHT, min(_MAX_COST_WEIGHT, cost_w))

        prev = self._params.get(key)
        return DynamicParams(
            model_label=model_label,
            task_type=task_type,
            quality_threshold=round(new_thr, 4),
            cost_weight=round(cost_w, 4),
            quality_ema=round(q_ema, 4),
            p50_latency_ms=float(p50),
            p95_latency_ms=float(p95),
            success_rate=round(success_rate, 3),
            sample_count=n,
            last_updated=time.time(),
        )


# Module-level singleton
telemetry_engine = TelemetryEngine()
