#!/usr/bin/env python3
"""
app.py  —  routing-v4
======================
FastAPI backend with real-time WebSocket telemetry streaming.

HTTP endpoints
--------------
  GET  /                  → chat + dashboard UI (static/index.html)
  POST /api/chat          → route prompt, execute LLMs, return enriched JSON
  GET  /api/models        → model registry (tiers, failover chains)
  GET  /api/stats         → aggregated routing feedback statistics
  GET  /api/health        → liveness + circuit-breaker snapshot
  GET  /api/telemetry     → current dynamic parameters (all model × task pairs)
  GET  /api/failover/events → recent failover events log

WebSocket
---------
  WS   /ws/telemetry      → real-time event stream:
    routing_plan         — sub-task breakdown before any LLM call
    subtask_start        — individual sub-task begins execution
    subtask_complete     — individual sub-task done (with full metrics)
    threshold_update     — dynamic params changed (from telemetry engine)
    request_complete     — all sub-tasks done, merged response ready
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent))

from src.orchestrator import Orchestrator
from src.feedback import FeedbackStore
from src.failover_manager import failover_manager
from src.telemetry import telemetry_engine
from src.cost_registry import MODEL_REGISTRY
from src.llm_client import TIER_TO_MODEL

# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    orchestrator.set_event_queue(_shared_queue)
    asyncio.create_task(_queue_forwarder())
    yield

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="routing-v4 — Advanced Multi-LLM Router",
    description=(
        "Advanced model failovers · Dynamic threshold optimisation · "
        "Real-time visual dashboard via WebSocket"
    ),
    version="4.0.0",
    docs_url="/api/docs",
    lifespan=lifespan,
)

# ── Shared state ──────────────────────────────────────────────────────────────
feedback_store = FeedbackStore(path="output/feedback.jsonl")
# Per-request event queue — updated by the orchestrator, drained by WS connections
# We use a broadcast pattern: each connected WS client gets its own queue.
_ws_clients: set[asyncio.Queue] = set()
_ws_lock = asyncio.Lock()

orchestrator = Orchestrator(feedback_store=feedback_store)


async def _broadcast(payload: dict) -> None:
    """Push a payload to all connected WebSocket clients."""
    if not _ws_clients:
        return
    msg = json.dumps(payload)
    dead: list[asyncio.Queue] = []
    async with _ws_lock:
        for q in _ws_clients:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            _ws_clients.discard(q)


# Inject the broadcast function into the telemetry engine
class _BroadcastQueue(asyncio.Queue):
    """Thin wrapper that calls _broadcast whenever an item is pushed."""
    def put_nowait(self, item):  # type: ignore[override]
        if isinstance(item, dict):
            asyncio.get_event_loop().call_soon_threadsafe(
                lambda: asyncio.ensure_future(_broadcast(item))
            )

# We give the orchestrator a shared queue that fans out to _broadcast
_shared_queue: asyncio.Queue = asyncio.Queue(maxsize=500)


async def _queue_forwarder() -> None:
    """Background task: drain _shared_queue → broadcast to all WS clients."""
    while True:
        try:
            item = await asyncio.wait_for(_shared_queue.get(), timeout=1.0)
            await _broadcast(item if isinstance(item, dict) else json.loads(item))
        except asyncio.TimeoutError:
            continue
        except Exception:
            pass


# ── Static UI ─────────────────────────────────────────────────────────────────
STATIC_DIR = Path(__file__).parent / "static"


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_ui():
    html = (STATIC_DIR / "index.html").read_text()
    return HTMLResponse(content=html)


# ── Request models ────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    prompt: str
    dry_run: bool = False


# ── API endpoints ─────────────────────────────────────────────────────────────

@app.post("/api/chat")
async def chat(req: ChatRequest):
    """Route a prompt through the full pipeline and return enriched JSON."""
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt must not be empty.")

    if req.dry_run:
        from src.splitter import split_and_classify
        from src.router import dispatch, _utility, STATIC_TASK_THRESHOLDS, BASE_QUALITY_THRESHOLD
        profiles = split_and_classify(req.prompt)
        routing  = dispatch(profiles)
        sub_tasks = []
        for key, (p, m, fe) in routing.items():
            sub_tasks.append({
                "task_type":    p.task_type.value,
                "complexity":   p.complexity,
                "tier":         p.tier.name,
                "model":        m.label,
                "provider":     m.provider,
                "ollama_model": TIER_TO_MODEL.get(m.label, m.label),
                "utility":      round(_utility(m, p), 4),
                "quality":      round(m.quality_score(p.complexity), 4),
                "threshold":    STATIC_TASK_THRESHOLDS.get(p.task_type.value, BASE_QUALITY_THRESHOLD),
                "dyn_threshold": telemetry_engine.get_threshold(m.label, p.task_type.value),
                "dyn_cost_weight": telemetry_engine.get_cost_weight(m.label, p.task_type.value),
                "failover_used":  fe is not None,
                "failover_from":  fe.primary_label if fe else "",
                "failover_reason": fe.reason if fe else "",
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
    """Full model registry with failover chains and live health scores."""
    health_map = {h["label"]: h for h in failover_manager.health_snapshot()}
    return JSONResponse(content=[
        {
            "label":           m.label,
            "tier":            m.tier,
            "provider":        m.provider,
            "ollama_model":    TIER_TO_MODEL.get(m.label, "?"),
            "cost_per_1k":     m.cost_per_1k,
            "max_tokens":      m.max_tokens,
            "capable_types":   list(m.capable_types),
            "quality_at_low":  round(m.quality_score(0.1), 3),
            "quality_at_high": round(m.quality_score(0.9), 3),
            "failover_chain":  [
                {"label": fl, "reason": fr}
                for fl, fr in m.failover_chain
            ],
            "health": health_map.get(m.label, {}),
        }
        for m in MODEL_REGISTRY
    ])


@app.get("/api/stats")
async def get_stats():
    """Aggregated routing feedback statistics."""
    return JSONResponse(content=feedback_store.summary())


@app.get("/api/health")
async def health():
    """Liveness + per-model circuit-breaker snapshot."""
    return JSONResponse(content={
        "status":   "ok",
        "version":  "4.0.0",
        "gateway":  "LiteLLM Router → Ollama",
        "circuits": failover_manager.health_snapshot(),
    })


@app.get("/api/telemetry")
async def get_telemetry():
    """Current dynamic parameters for all observed (model, task_type) pairs."""
    return JSONResponse(content={
        "params":        telemetry_engine.get_all_params(),
        "recent_records": telemetry_engine.recent_records(50),
        "failover_events": failover_manager.recent_events(20),
    })


@app.get("/api/failover/events")
async def get_failover_events():
    """Recent failover event log."""
    return JSONResponse(content=failover_manager.recent_events(50))


# ── WebSocket  /ws/telemetry ──────────────────────────────────────────────────

@app.websocket("/ws/telemetry")
async def ws_telemetry(ws: WebSocket):
    """
    Real-time event stream.
    Each connected client receives its own queue populated by the orchestrator.
    Initial burst: model registry + current health + current dynamic params.
    """
    await ws.accept()
    client_queue: asyncio.Queue = asyncio.Queue(maxsize=200)
    async with _ws_lock:
        _ws_clients.add(client_queue)

    try:
        # Send initial snapshot
        health_map = {h["label"]: h for h in failover_manager.health_snapshot()}
        await ws.send_text(json.dumps({
            "type": "init",
            "models": [
                {
                    "label":     m.label,
                    "tier":      m.tier,
                    "provider":  m.provider,
                    "cost":      m.cost_per_1k,
                    "health":    health_map.get(m.label, {}),
                    "failover_chain": [fl for fl, _ in m.failover_chain],
                }
                for m in MODEL_REGISTRY
            ],
            "dynamic_params": telemetry_engine.get_all_params(),
            "stats":          feedback_store.summary(),
        }))

        while True:
            try:
                msg = await asyncio.wait_for(client_queue.get(), timeout=5.0)
                await ws.send_text(msg if isinstance(msg, str) else json.dumps(msg))
            except asyncio.TimeoutError:
                # Send heartbeat to keep connection alive
                await ws.send_text(json.dumps({
                    "type":    "heartbeat",
                    "health":  failover_manager.health_snapshot(),
                    "stats":   feedback_store.summary(),
                    "dyn_params": telemetry_engine.get_all_params(),
                }))
    except WebSocketDisconnect:
        pass
    finally:
        async with _ws_lock:
            _ws_clients.discard(client_queue)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="routing-v4 — Advanced Multi-LLM Router")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8080)
    args = p.parse_args()
    uvicorn.run("app:app", host=args.host, port=args.port, reload=False)
