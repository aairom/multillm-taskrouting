"""
orchestrator.py  —  enriched for the Chat UI
Ties together splitting, routing, parallel execution, and aggregation.
Returns full routing metadata (utility score, quality score, ollama model)
so the UI can display the decision rationale alongside each response.
"""

from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass, field

from src.splitter import split_and_classify
from src.router import dispatch, _utility, TASK_QUALITY_THRESHOLDS, QUALITY_THRESHOLD
from src.llm_client import call_model, TIER_TO_MODEL
from src.feedback import FeedbackStore
from src.task_classifier import TaskProfile
from src.cost_registry import ModelSpec


@dataclass
class SubTaskResult:
    profile:       TaskProfile
    model:         ModelSpec
    response:      str
    latency_ms:    int
    out_tokens:    int
    # ── routing metadata exposed to the UI ──────────────────────────────────
    utility_score: float        # U = β·Q − α·C
    quality_score: float        # model.quality_score(complexity)
    threshold:     float        # per-task quality threshold applied
    ollama_model:  str          # concrete ollama model name used
    cost_units:    float        # normalised cost for this call


@dataclass
class OrchestratorResult:
    prompt:       str
    sub_results:  list[SubTaskResult]
    merged:       str
    total_ms:     int

    def routing_table(self) -> list[dict]:
        return [
            {
                "task_type":    r.profile.task_type.value,
                "complexity":   r.profile.complexity,
                "tier":         r.profile.tier.name,
                "model":        r.model.label,
                "provider":     r.model.provider,
                "ollama_model": r.ollama_model,
                "utility":      round(r.utility_score, 4),
                "quality":      round(r.quality_score, 4),
                "threshold":    r.threshold,
                "latency_ms":   r.latency_ms,
                "out_tokens":   r.out_tokens,
                "cost_units":   r.cost_units,
                "response":     r.response,
            }
            for r in self.sub_results
        ]

    def to_ui_payload(self) -> dict:
        """Full payload for the chat UI — includes per-subtask routing details."""
        return {
            "prompt":      self.prompt,
            "total_ms":    self.total_ms,
            "merged":      self.merged,
            "sub_tasks":   self.routing_table(),
        }


class Orchestrator:
    def __init__(self, feedback_store: FeedbackStore | None = None) -> None:
        self._store = feedback_store or FeedbackStore()

    async def handle(self, prompt: str) -> OrchestratorResult:
        """
        Full pipeline:
          1. Split + classify
          2. Route via utility function U = β·Q − α·C
          3. Execute all sub-tasks in parallel via LiteLLM Router
          4. Aggregate + record
        """
        t_start = time.perf_counter()
        profiles = split_and_classify(prompt)
        routing  = dispatch(profiles)

        async def _exec(key: str, profile: TaskProfile, model: ModelSpec) -> SubTaskResult:
            response, latency, tokens = await call_model(
                model_label=model.label,
                prompt=profile.raw_text,
                max_tokens=min(2048, profile.token_estimate * 3),
            )
            lat_ms      = int(latency * 1000)
            u           = _utility(model, profile)
            q           = model.quality_score(profile.complexity)
            thr         = TASK_QUALITY_THRESHOLDS.get(profile.task_type.value, QUALITY_THRESHOLD)
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
            )
            return SubTaskResult(
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
            )

        sub_results = list(await asyncio.gather(
            *[_exec(k, p, m) for k, (p, m) in routing.items()]
        ))

        merged   = self._merge(sub_results)
        total_ms = int((time.perf_counter() - t_start) * 1000)

        return OrchestratorResult(
            prompt=prompt,
            sub_results=sub_results,
            merged=merged,
            total_ms=total_ms,
        )

    def handle_sync(self, prompt: str) -> OrchestratorResult:
        return asyncio.run(self.handle(prompt))

    @staticmethod
    def _merge(results: list[SubTaskResult]) -> str:
        sections = []
        for r in results:
            label  = r.profile.task_type.value.replace("_", " ").title()
            header = (
                f"## {label}  "
                f"_(via {r.model.label} [{r.model.provider}], {r.latency_ms} ms)_"
            )
            sections.append(f"{header}\n\n{r.response.strip()}")
        return "\n\n---\n\n".join(sections)
