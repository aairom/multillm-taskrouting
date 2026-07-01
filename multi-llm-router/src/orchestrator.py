"""
orchestrator.py
Ties together splitting, routing, parallel execution, and aggregation.
"""

from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass

from src.splitter import split_and_classify
from src.router import dispatch
from src.llm_client import call_model
from src.feedback import FeedbackStore
from src.task_classifier import TaskProfile
from src.cost_registry import ModelSpec


@dataclass
class SubTaskResult:
    profile:     TaskProfile
    model:       ModelSpec
    response:    str
    latency_ms:  int
    out_tokens:  int


@dataclass
class OrchestratorResult:
    prompt:       str
    sub_results:  list[SubTaskResult]
    merged:       str
    total_ms:     int

    def routing_table(self) -> list[dict]:
        return [
            {
                "task_type":   r.profile.task_type.value,
                "complexity":  r.profile.complexity,
                "tier":        r.profile.tier.name,
                "model":       r.model.label,
                "latency_ms":  r.latency_ms,
                "out_tokens":  r.out_tokens,
                "cost_units":  round(r.model.cost_per_1k * r.out_tokens / 1000, 6),
            }
            for r in self.sub_results
        ]


class Orchestrator:
    def __init__(self, feedback_store: FeedbackStore | None = None) -> None:
        self._store = feedback_store or FeedbackStore()

    # ── Core ─────────────────────────────────────────────────────────────────

    async def handle(self, prompt: str) -> OrchestratorResult:
        """
        Full pipeline:
          1. Split prompt into independent sub-tasks.
          2. Classify each sub-task.
          3. Route each sub-task to the optimal model.
          4. Execute all sub-tasks in parallel.
          5. Aggregate responses.
          6. Record to feedback store.
        """
        t_start = time.perf_counter()

        # Step 1 + 2: split & classify
        profiles = split_and_classify(prompt)

        # Step 3: route
        routing = dispatch(profiles)   # key → (profile, model)

        # Step 4: parallel execution
        async def _exec(key: str, profile: TaskProfile, model: ModelSpec) -> SubTaskResult:
            response, latency, tokens = await call_model(
                model_label=model.label,
                prompt=profile.raw_text,
                max_tokens=min(2048, profile.token_estimate * 3),
            )
            lat_ms = int(latency * 1000)
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
            return SubTaskResult(profile, model, response, lat_ms, tokens)

        sub_results = await asyncio.gather(
            *[_exec(k, p, m) for k, (p, m) in routing.items()]
        )

        # Step 5: aggregate
        merged = self._merge(list(sub_results))
        total_ms = int((time.perf_counter() - t_start) * 1000)

        return OrchestratorResult(
            prompt=prompt,
            sub_results=list(sub_results),
            merged=merged,
            total_ms=total_ms,
        )

    def handle_sync(self, prompt: str) -> OrchestratorResult:
        return asyncio.run(self.handle(prompt))

    # ── Merge ────────────────────────────────────────────────────────────────

    @staticmethod
    def _merge(results: list[SubTaskResult]) -> str:
        sections = []
        for r in results:
            label = r.profile.task_type.value.replace("_", " ").title()
            header = f"## {label}  _(via {r.model.label}, {r.latency_ms} ms)_"
            sections.append(f"{header}\n\n{r.response.strip()}")
        return "\n\n---\n\n".join(sections)
