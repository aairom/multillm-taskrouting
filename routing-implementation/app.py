#!/usr/bin/env python3
"""
app.py  —  LLM Routing Chat UI
FastAPI backend that serves the single-page chat interface and exposes:
  GET  /              → chat UI (static/index.html)
  POST /api/chat      → route prompt, call LLMs, return enriched JSON
  GET  /api/models    → model registry (tiers, providers, ollama names)
  GET  /api/stats     → routing feedback statistics
  GET  /health        → liveness probe
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent))

from src.orchestrator import Orchestrator
from src.feedback import FeedbackStore
from src.cost_registry import MODEL_REGISTRY
from src.llm_client import TIER_TO_MODEL

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="LLM Routing Chat",
    description="Chat UI that demonstrates intelligent LLM routing via LiteLLM → Ollama",
    version="1.0.0",
    docs_url="/api/docs",
)

feedback_store = FeedbackStore(path="output/feedback.jsonl")
orchestrator   = Orchestrator(feedback_store=feedback_store)

# ── Serve the UI ──────────────────────────────────────────────────────────────
STATIC_DIR = Path(__file__).parent / "static"

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_ui():
    html = (STATIC_DIR / "index.html").read_text()
    return HTMLResponse(content=html)


# ── Request / Response models ─────────────────────────────────────────────────
class ChatRequest(BaseModel):
    prompt: str
    dry_run: bool = False


# ── API endpoints ─────────────────────────────────────────────────────────────

@app.post("/api/chat")
async def chat(req: ChatRequest):
    """
    Route a prompt through the LLM pipeline and return the full response
    with routing metadata for the UI.
    """
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt must not be empty.")

    if req.dry_run:
        from src.splitter import split_and_classify
        from src.router import dispatch, _utility, TASK_QUALITY_THRESHOLDS, QUALITY_THRESHOLD
        profiles = split_and_classify(req.prompt)
        routing  = dispatch(profiles)
        sub_tasks = []
        for key, (p, m) in routing.items():
            sub_tasks.append({
                "task_type":    p.task_type.value,
                "complexity":   p.complexity,
                "tier":         p.tier.name,
                "model":        m.label,
                "provider":     m.provider,
                "ollama_model": TIER_TO_MODEL.get(m.label, m.label),
                "utility":      round(_utility(m, p), 4),
                "quality":      round(m.quality_score(p.complexity), 4),
                "threshold":    TASK_QUALITY_THRESHOLDS.get(p.task_type.value, QUALITY_THRESHOLD),
                "latency_ms":   None,
                "out_tokens":   None,
                "cost_units":   None,
                "response":     None,
            })
        return JSONResponse(content={
            "prompt":    req.prompt,
            "total_ms":  None,
            "merged":    None,
            "sub_tasks": sub_tasks,
            "dry_run":   True,
        })

    try:
        result = await orchestrator.handle(req.prompt)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    payload = result.to_ui_payload()
    payload["dry_run"] = False
    return JSONResponse(content=payload)


@app.get("/api/models")
async def get_models():
    """Return the full model registry for the UI sidebar."""
    return JSONResponse(content=[
        {
            "label":        m.label,
            "tier":         m.tier,
            "provider":     m.provider,
            "ollama_model": TIER_TO_MODEL.get(m.label, "?"),
            "cost_per_1k":  m.cost_per_1k,
            "max_tokens":   m.max_tokens,
            "capable_types": list(m.capable_types),
            "quality_at_low":  round(m.quality_score(0.1), 3),
            "quality_at_high": round(m.quality_score(0.9), 3),
        }
        for m in MODEL_REGISTRY
    ])


@app.get("/api/stats")
async def get_stats():
    """Return aggregated routing statistics."""
    return JSONResponse(content=feedback_store.summary())


@app.get("/health")
async def health():
    return {"status": "ok", "gateway": "LiteLLM Router → Ollama"}


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="LLM Routing Chat UI")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8080)
    args = p.parse_args()
    uvicorn.run("app:app", host=args.host, port=args.port, reload=False)
