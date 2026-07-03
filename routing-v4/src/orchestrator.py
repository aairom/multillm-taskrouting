"""
orchestrator.py  —  routing-v4
================================
Ties together: splitting → routing (with failover) → parallel execution
→ telemetry recording → feedback persistence → WebSocket broadcast.

Every completed sub-task emits a routing_event to the async event queue
so the front-end receives a real-time update for each individual LLM call.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

from src.splitter import split_and_classify
from src.router import dispatch, _utility, STATIC_TASK_THRESHOLDS, BASE_QUALITY_THRESHOLD
from src.llm_client import call_model, TIER_TO_MODEL
from src.feedback import FeedbackStore
from src.failover_manager import failover_manager, FailoverEvent
from src.telemetry import telemetry_engine, TelemetryRecord
from src.task_classifier import TaskProfile
from src.cost_registry import ModelSpec


@dataclass
class SubTaskResult:
    profile:        TaskProfile
    model:          ModelSpec
    response:       str
    latency_ms:     int
    out_tokens:     int
    # Routing metadata
    utility_score:  float
    quality_score:  float
    threshold:      float
    ollama_model:   str
    cost_units:     float
    # Failover metadata
    failover_used:  bool              = False
    failover_from:  str               = ""
    failover_reason: str              = ""
    # Dynamic params that were active when this call was routed
    dyn_threshold:  float             = 0.0
    dyn_cost_weight: float            = 0.0


@dataclass
class OrchestratorResult:
    prompt:      str
    sub_results: list[SubTaskResult]
    merged:      str
    total_ms:    int

    def routing_table(self) -> list[dict]:
        return [
            {
                "task_type":      r.profile.task_type.value,
                "complexity":     r.profile.complexity,
                "tier":           r.profile.tier.name,
                "model":          r.model.label,
                "provider":       r.model.provider,
                "ollama_model":   r.ollama_model,
                "utility":        round(r.utility_score, 4),
                "quality":        round(r.quality_score, 4),
                "threshold":      r.threshold,
                "latency_ms":     r.latency_ms,
                "out_tokens":     r.out_tokens,
                "cost_units":     r.cost_units,
                "failover_used":  r.failover_used,
                "failover_from":  r.failover_from,
                "failover_reason": r.failover_reason,
                "dyn_threshold":  r.dyn_threshold,
                "dyn_cost_weight": r.dyn_cost_weight,
                "response":       r.response,
            }
            for r in self.sub_results
        ]

    def to_ui_payload(self) -> dict:
        return {
            "prompt":    self.prompt,
            "total_ms":  self.total_ms,
            "merged":    self.merged,
            "sub_tasks": self.routing_table(),
        }


class Orchestrator:
    def __init__(
        self,
        feedback_store: Optional[FeedbackStore] = None,
        event_queue:    Optional[asyncio.Queue]  = None,
    ) -> None:
        self._store   = feedback_store or FeedbackStore()
        self._eq      = event_queue
        if event_queue:
            telemetry_engine.set_event_queue(event_queue)

    def set_event_queue(self, q: asyncio.Queue) -> None:
        self._eq = q
        telemetry_engine.set_event_queue(q)

    async def handle(self, prompt: str) -> OrchestratorResult:
        t_start  = time.perf_counter()
        profiles = split_and_classify(prompt)
        routing  = dispatch(profiles)

        # Broadcast routing plan before any LLM call
        await self._emit({
            "type":     "routing_plan",
            "prompt":   prompt,
            "sub_tasks": [
                {
                    "task_type":  p.task_type.value,
                    "complexity": p.complexity,
                    "tier":       p.tier.name,
                    "model":      m.label,
                    "provider":   m.provider,
                    "failover":   fe.fallback_label if fe else None,
                }
                for _, (p, m, fe) in routing.items()
            ],
        })

        async def _exec(
            key: str,
            profile: TaskProfile,
            model: ModelSpec,
            failover_event: Optional[FailoverEvent],
        ) -> SubTaskResult:

            # Emit "in_progress" event
            await self._emit({
                "type":       "subtask_start",
                "key":        key,
                "task_type":  profile.task_type.value,
                "model":      model.label,
                "provider":   model.provider,
                "failover":   failover_event.fallback_label if failover_event else None,
            })

            response, latency, tokens = await call_model(
                model_label=model.label,
                prompt=profile.raw_text,
                max_tokens=min(2048, profile.token_estimate * 3),
            )

            lat_ms  = int(latency * 1000)
            success = not response.startswith("[LiteLLM ERROR")

            # Feed telemetry engine (triggers threshold recomputation)
            quality = FeedbackStore._heuristic_quality(lat_ms, tokens)
            tel_rec = TelemetryRecord(
                model_label=model.label,
                task_type=profile.task_type.value,
                latency_ms=lat_ms,
                out_tokens=tokens,
                cost_units=round(model.cost_per_1k * tokens / 1000, 6),
                quality_eval=quality,
                success=success,
            )
            dyn_params = telemetry_engine.record(tel_rec)

            u          = _utility(model, profile)
            q          = model.quality_score(profile.complexity)
            thr        = STATIC_TASK_THRESHOLDS.get(profile.task_type.value, BASE_QUALITY_THRESHOLD)
            ollama_name = TIER_TO_MODEL.get(model.label, model.label)
            cost        = round(model.cost_per_1k * tokens / 1000, 6)

            self._store.record(
                task_type=profile.task_type.value,
                complexity=profile.complexity,
                tier=model.tier,
                model_used=model.label,
                latency_ms=lat_ms,
                output_tokens=tokens,
                cost_per_1k=model.cost_per_1k,
                prompt_len=len(profile.raw_text),
                failover_used=failover_event is not None,
                failover_from=failover_event.primary_label if failover_event else "",
                failover_reason=failover_event.reason if failover_event else "",
            )

            result = SubTaskResult(
                profile=profile,
                model=model,
                response=response,
                latency_ms=lat_ms,
                out_tokens=tokens,
                utility_score=round(u, 4),
                quality_score=round(q, 4),
                threshold=thr,
                ollama_model=ollama_name,
                cost_units=cost,
                failover_used=failover_event is not None,
                failover_from=failover_event.primary_label if failover_event else "",
                failover_reason=failover_event.reason if failover_event else "",
                dyn_threshold=dyn_params.quality_threshold,
                dyn_cost_weight=dyn_params.cost_weight,
            )

            # Emit "complete" event with full metadata
            await self._emit({
                "type":         "subtask_complete",
                "key":          key,
                "task_type":    profile.task_type.value,
                "model":        model.label,
                "provider":     model.provider,
                "tier":         model.tier,
                "latency_ms":   lat_ms,
                "out_tokens":   tokens,
                "cost_units":   cost,
                "quality":      round(q, 4),
                "utility":      round(u, 4),
                "threshold":    thr,
                "dyn_threshold": dyn_params.quality_threshold,
                "dyn_cost_weight": dyn_params.cost_weight,
                "success":      success,
                "failover_used": failover_event is not None,
                "failover_from": failover_event.primary_label if failover_event else "",
                "failover_reason": failover_event.reason if failover_event else "",
                "health":       failover_manager.health_snapshot(),
            })

            return result

        sub_results = list(await asyncio.gather(
            *[_exec(k, p, m, fe) for k, (p, m, fe) in routing.items()]
        ))

        merged   = self._merge(sub_results)
        total_ms = int((time.perf_counter() - t_start) * 1000)

        await self._emit({
            "type":     "request_complete",
            "total_ms": total_ms,
            "merged":   merged,
        })

        return OrchestratorResult(
            prompt=prompt,
            sub_results=sub_results,
            merged=merged,
            total_ms=total_ms,
        )

    def handle_sync(self, prompt: str) -> OrchestratorResult:
        return asyncio.run(self.handle(prompt))

    async def _emit(self, payload: dict) -> None:
        if self._eq is not None:
            try:
                self._eq.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    @staticmethod
    def _merge(results: list[SubTaskResult]) -> str:
        sections = []
        for r in results:
            label  = r.profile.task_type.value.replace("_", " ").title()
            fo_tag = f" ⚡ failover from {r.failover_from}" if r.failover_used else ""
            header = (
                f"## {label}  "
                f"_(via {r.model.label} [{r.model.provider}]{fo_tag}, {r.latency_ms} ms)_"
            )
            sections.append(f"{header}\n\n{r.response.strip()}")
        return "\n\n---\n\n".join(sections)
