"""
failover_manager.py  —  routing-v4
==================================
Advanced model failover with per-model circuit breakers.

Circuit breaker states
----------------------
  CLOSED     — normal operation; calls pass through
  OPEN       — blocked after too many failures; all calls bounce immediately
  HALF_OPEN  — cooldown elapsed; a limited number of probe calls are allowed
               to test recovery

Health score
------------
Exponential moving average of binary success/failure events.
  health_score ∈ [0.0, 1.0]  (1.0 = perfect, 0.0 = complete failure)

Failover resolution
-------------------
When route() wants model M but M's circuit is OPEN:
  1. Walk M's failover_chain in order.
  2. Pick the first entry whose circuit is not OPEN.
  3. If all are OPEN, pick the model with the highest health_score as last resort.
  4. Emit a FailoverEvent so the orchestrator / telemetry can record it.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import Optional

from src.cost_registry import MODEL_REGISTRY, MODEL_BY_LABEL, ModelSpec


# ── Tunable defaults (overridable via env) ────────────────────────────────────
_FAILURE_THRESHOLD = int(os.getenv("CIRCUIT_FAILURE_THRESHOLD", "3"))
_COOLDOWN_SECONDS  = int(os.getenv("CIRCUIT_COOLDOWN_SECONDS",  "30"))
_HALF_OPEN_PROBES  = int(os.getenv("CIRCUIT_HALF_OPEN_PROBES",  "2"))
_HEALTH_EMA_ALPHA  = 0.20   # smoothing factor for health score EMA


class CircuitState(Enum):
    CLOSED    = "CLOSED"
    OPEN      = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass
class FailoverEvent:
    """Emitted whenever a failover substitution is made."""
    primary_label:  str             # the originally requested model
    fallback_label: str             # the model actually used
    reason:         str             # e.g. "light_circuit_open"
    timestamp:      float = field(default_factory=time.time)


@dataclass
class CircuitBreakerState:
    label:            str
    state:            CircuitState = CircuitState.CLOSED
    consecutive_fails: int         = 0
    last_failure_ts:  float        = 0.0
    half_open_probes: int          = 0
    health_score:     float        = 1.0   # EMA
    _lock:            Lock         = field(default_factory=Lock, repr=False, compare=False)

    # ── State machine ─────────────────────────────────────────────────────────

    def record_success(self) -> None:
        with self._lock:
            self._update_health(1.0)
            if self.state == CircuitState.HALF_OPEN:
                self.half_open_probes += 1
                if self.half_open_probes >= _HALF_OPEN_PROBES:
                    self._close()
            elif self.state == CircuitState.CLOSED:
                self.consecutive_fails = 0

    def record_failure(self) -> None:
        with self._lock:
            self._update_health(0.0)
            self.consecutive_fails += 1
            self.last_failure_ts = time.time()
            if self.state in (CircuitState.CLOSED, CircuitState.HALF_OPEN):
                if self.consecutive_fails >= _FAILURE_THRESHOLD:
                    self._open()
            # A single failure in HALF_OPEN resets back to OPEN
            if self.state == CircuitState.HALF_OPEN:
                self._open()

    def is_callable(self) -> bool:
        """True if a call is allowed right now."""
        with self._lock:
            if self.state == CircuitState.CLOSED:
                return True
            if self.state == CircuitState.OPEN:
                if time.time() - self.last_failure_ts >= _COOLDOWN_SECONDS:
                    self._half_open()
                    return True     # let the probe through
                return False
            # HALF_OPEN: allow up to _HALF_OPEN_PROBES concurrent probes
            return True

    def snapshot(self) -> dict:
        return {
            "label":             self.label,
            "state":             self.state.value,
            "consecutive_fails": self.consecutive_fails,
            "health_score":      round(self.health_score, 3),
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _update_health(self, outcome: float) -> None:
        self.health_score = (
            _HEALTH_EMA_ALPHA * outcome
            + (1.0 - _HEALTH_EMA_ALPHA) * self.health_score
        )

    def _open(self) -> None:
        self.state = CircuitState.OPEN
        self.half_open_probes = 0

    def _half_open(self) -> None:
        self.state = CircuitState.HALF_OPEN
        self.half_open_probes = 0

    def _close(self) -> None:
        self.state = CircuitState.CLOSED
        self.consecutive_fails = 0
        self.half_open_probes = 0


# ── Singleton manager ─────────────────────────────────────────────────────────

class FailoverManager:
    """
    Single global object tracking circuit-breaker state for every model.
    Thread-safe; safe to call from async contexts (no blocking I/O).
    """

    def __init__(self) -> None:
        self._circuits: dict[str, CircuitBreakerState] = {
            m.label: CircuitBreakerState(label=m.label)
            for m in MODEL_REGISTRY
        }
        self._events: list[FailoverEvent] = []
        self._lock = Lock()

    # ── Public API ────────────────────────────────────────────────────────────

    def record_success(self, model_label: str) -> None:
        cb = self._circuits.get(model_label)
        if cb:
            cb.record_success()

    def record_failure(self, model_label: str) -> None:
        cb = self._circuits.get(model_label)
        if cb:
            cb.record_failure()

    def is_callable(self, model_label: str) -> bool:
        cb = self._circuits.get(model_label)
        return cb.is_callable() if cb else True

    def resolve(
        self,
        primary: ModelSpec,
        task_type: str,
    ) -> tuple[ModelSpec, Optional[FailoverEvent]]:
        """
        Return (model_to_use, failover_event_or_None).

        If the primary's circuit is callable → return primary directly.
        Otherwise walk its failover_chain until a callable model is found.
        Last resort: pick the model with the highest health score.
        """
        if self.is_callable(primary.label):
            return primary, None

        # Walk the explicit failover chain
        for fallback_label, reason in primary.failover_chain:
            fb_model = MODEL_BY_LABEL.get(fallback_label)
            if fb_model and self.is_callable(fallback_label):
                event = FailoverEvent(
                    primary_label=primary.label,
                    fallback_label=fallback_label,
                    reason=reason,
                )
                with self._lock:
                    self._events.append(event)
                return fb_model, event

        # Last resort: highest health score among all models
        best = max(
            MODEL_REGISTRY,
            key=lambda m: self._circuits[m.label].health_score,
        )
        event = FailoverEvent(
            primary_label=primary.label,
            fallback_label=best.label,
            reason="all_chains_exhausted",
        )
        with self._lock:
            self._events.append(event)
        return best, event

    def health_snapshot(self) -> list[dict]:
        return [cb.snapshot() for cb in self._circuits.values()]

    def recent_events(self, limit: int = 20) -> list[dict]:
        with self._lock:
            tail = self._events[-limit:]
        return [
            {
                "primary":   e.primary_label,
                "fallback":  e.fallback_label,
                "reason":    e.reason,
                "timestamp": e.timestamp,
            }
            for e in tail
        ]


# Module-level singleton
failover_manager = FailoverManager()
