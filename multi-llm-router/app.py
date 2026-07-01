#!/usr/bin/env python3
"""
app.py  —  Multi-LLM Task Router  (demo application)

Runs a FastAPI server with two endpoints:
  POST /route      →  route and execute a prompt
  GET  /feedback   →  routing statistics

Demonstrates the scenario:
  "Write the API reference documentation AND implement the OAuth2 middleware"

  Sub-task A (Documentation)  → model::light  (cheap, fast)
  Sub-task B (Code Generation) → model::heavy  (powerful, expensive)
"""

from __future__ import annotations
import asyncio
import json
import os
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Ensure the project root is on sys.path when launched from any directory
sys.path.insert(0, str(Path(__file__).parent))

from src.orchestrator import Orchestrator
from src.feedback import FeedbackStore
from src.splitter import split_and_classify
from src.router import dispatch, route
from src.task_classifier import classify

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Multi-LLM Task Router",
    description=(
        "Theoretical demo: routes sub-tasks to the cheapest model tier "
        "that meets a quality threshold.  Backend: Ollama (local)."
    ),
    version="1.0.0",
)

feedback_store = FeedbackStore(path="output/feedback.jsonl")
orchestrator   = Orchestrator(feedback_store=feedback_store)


# ── Request / Response models ─────────────────────────────────────────────────
class RouteRequest(BaseModel):
    prompt: str
    dry_run: bool = False   # if True, classify + route only; do NOT call LLMs


class SubTaskSummary(BaseModel):
    task_type:   str
    complexity:  float
    tier:        str
    model:       str
    latency_ms:  int | None
    out_tokens:  int | None
    cost_units:  float | None
    response:    str | None


class RouteResponse(BaseModel):
    prompt:         str
    sub_tasks:      list[SubTaskSummary]
    merged_output:  str | None
    total_ms:       int | None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/route", response_model=RouteResponse)
async def route_prompt(req: RouteRequest):
    """
    Route a prompt (optionally compound) to the appropriate LLM tier(s).

    Set dry_run=true to inspect the routing decision without calling any LLM.
    """
    if req.dry_run:
        profiles = split_and_classify(req.prompt)
        routing  = dispatch(profiles)
        sub_tasks = [
            SubTaskSummary(
                task_type=p.task_type.value,
                complexity=p.complexity,
                tier=p.tier.name,
                model=m.label,
                latency_ms=None,
                out_tokens=None,
                cost_units=None,
                response=None,
            )
            for _, (p, m) in routing.items()
        ]
        return RouteResponse(
            prompt=req.prompt,
            sub_tasks=sub_tasks,
            merged_output=None,
            total_ms=None,
        )

    try:
        result = await orchestrator.handle(req.prompt)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    sub_tasks = [
        SubTaskSummary(
            task_type=r.profile.task_type.value,
            complexity=r.profile.complexity,
            tier=r.profile.tier.name,
            model=r.model.label,
            latency_ms=r.latency_ms,
            out_tokens=r.out_tokens,
            cost_units=round(r.model.cost_per_1k * r.out_tokens / 1000, 6),
            response=r.response,
        )
        for r in result.sub_results
    ]

    return RouteResponse(
        prompt=result.prompt,
        sub_tasks=sub_tasks,
        merged_output=result.merged,
        total_ms=result.total_ms,
    )


@app.get("/feedback")
async def get_feedback():
    """Return aggregated routing statistics from the feedback store."""
    return JSONResponse(content=feedback_store.summary())


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Demo scenario (run directly) ─────────────────────────────────────────────

DEMO_PROMPT = (
    "Write the API reference documentation for our REST /users endpoints "
    "AND implement the OAuth2 Bearer-token middleware in Python FastAPI."
)


def run_demo_scenario() -> None:
    """
    Run the worked scenario from the command line without starting the server.
    Demonstrates how the same prompt is split across 4 LLM providers:
      documentation → IBM Granite (model::light)
      code          → Meta LLaMA / Google Gemma / Mistral (medium / balanced / heavy)
    """
    from src.router import _utility
    from src.llm_client import TIER_TO_MODEL

    W = 80
    print("=" * W)
    print("  Multi-LLM Task Router  —  Demonstration Scenario  (4 providers)")
    print("=" * W)
    print(f"\nPrompt:\n  {DEMO_PROMPT}\n")

    # ── Model mapping in use ──────────────────────────────────────────────────
    print("Model tier mapping:")
    from src.cost_registry import MODEL_REGISTRY
    for m in MODEL_REGISTRY:
        real = TIER_TO_MODEL.get(m.label, "?")
        print(f"  {m.label:<20s}  {m.provider:<14s}  →  {real}")
    print()

    # ── Step 1: Split & classify ──────────────────────────────────────────────
    profiles = split_and_classify(DEMO_PROMPT)
    print(f"Detected {len(profiles)} sub-task(s):")
    for i, p in enumerate(profiles, 1):
        print(f"  [{i}] {p}")

    # ── Step 2: Route ─────────────────────────────────────────────────────────
    routing = dispatch(profiles)
    print("\nRouting decisions:")
    print(f"  {'Task Type':<22} {'Complexity':>10}  {'Tier':<10} {'Label':<20} {'Provider':<14} {'U':>8}")
    print("  " + "-" * (W - 2))
    for key, (p, m) in routing.items():
        u = _utility(m, p)
        print(
            f"  {p.task_type.value:<22} {p.complexity:>10.3f}  "
            f"{p.tier.name:<10} {m.label:<20} {m.provider:<14} {u:>+8.4f}"
        )

    # ── Step 3: Execute ───────────────────────────────────────────────────────
    print(f"\nExecuting sub-tasks via Ollama…  (set DRY_RUN=1 to skip LLM calls)\n")
    if os.getenv("DRY_RUN") == "1":
        print("  [DRY RUN] LLM calls skipped.")
        return

    result = orchestrator.handle_sync(DEMO_PROMPT)

    # ── Step 4: Display ───────────────────────────────────────────────────────
    print("\n" + "=" * W)
    print("  ROUTING TABLE")
    print("=" * W)
    print(
        f"  {'Task Type':<22} {'Label':<20} {'Provider':<14} {'Latency':>9}  "
        f"{'Tokens':>7}  {'Cost':>10}"
    )
    print("  " + "-" * (W - 2))
    for row in result.routing_table():
        # resolve provider from registry
        provider = next(
            (m.provider for m in MODEL_REGISTRY if m.label == row["model"]), "?"
        )
        print(
            f"  {row['task_type']:<22} {row['model']:<20} {provider:<14} "
            f"{row['latency_ms']:>7} ms  "
            f"{row['out_tokens']:>7}  "
            f"{row['cost_units']:>10.6f}"
        )

    print(f"\n  Total wall-clock: {result.total_ms} ms")

    print("\n" + "=" * 70)
    print("  MERGED RESPONSE")
    print("=" * 70)
    print(result.merged)

    stats = feedback_store.summary()
    print("\n" + "=" * 70)
    print("  FEEDBACK SUMMARY")
    print("=" * 70)
    print(json.dumps(stats, indent=2))


# ── Entry points ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Multi-LLM Task Router")
    parser.add_argument(
        "--mode",
        choices=["server", "demo"],
        default="demo",
        help="server: start FastAPI server  |  demo: run scenario in terminal",
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    if args.mode == "server":
        uvicorn.run("app:app", host=args.host, port=args.port, reload=False)
    else:
        run_demo_scenario()
