"""FastAPI routes for Guardian AI."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.agents.critics import CRITICS
from app.agents.intake import run_intake
from app.agents.resolver import run_resolver
from app.agents.runner import build_prior_state
from app.config import settings
from app.graph import GRAPH
from app.models.schemas import (
    CriticVerdict, IntakeMetadata, IterationRecord, ReviewRequest,
    ReviewResponse, Severity, ToolCallTrace, Verdict,
)
from app.skills import _data, offer_verification


router = APIRouter()


# ---------- Reference data ----------

@router.get("/offers")
def list_offers() -> list[dict[str, Any]]:
    return offer_verification.list_offers()


@router.get("/samples/violation")
def violation_samples() -> dict[str, Any]:
    return _data.violation_samples()


@router.get("/samples/good")
def good_samples() -> dict[str, Any]:
    return _data.good_samples()


@router.get("/rules/regulatory")
def reg_rules() -> dict[str, Any]:
    return _data.regulatory_rules()


@router.get("/rules/brand")
def brand_rules() -> dict[str, Any]:
    return _data.brand_guidelines()


# ---------- Synchronous review ----------

@router.post("/review", response_model=ReviewResponse)
def review(req: ReviewRequest) -> ReviewResponse:
    """Run the full review graph synchronously."""
    initial = {
        "original_content": req.content,
        "channel_hint": req.channel,
        "audience_hint": req.audience,
        "offer_id_hint": req.offer_id,
    }
    final = GRAPH.invoke(initial, {"recursion_limit": 50})
    return ReviewResponse(
        final_content=final.get("current_content", req.content),
        converged=bool(final.get("converged")),
        iterations=final.get("iterations", []),
        intake=final.get("intake", IntakeMetadata()),
        audit_trail=final.get("audit", []),
    )


# ---------- WebSocket streaming review ----------

@router.websocket("/ws/review")
async def ws_review(ws: WebSocket) -> None:
    """Streams progress events as the graph runs.

    Client sends: ReviewRequest JSON.
    Server emits one JSON message per event:
      {"type": "intake", "intake": {...}}
      {"type": "critic", "verdict": {...}}
      {"type": "iteration", "iteration": {...}}
      {"type": "done", "response": {...}}
    """
    await ws.accept()
    try:
        first = await ws.receive_text()
        req = ReviewRequest(**json.loads(first))
    except Exception as e:  # noqa: BLE001
        await ws.send_text(json.dumps({"type": "error", "error": str(e)}))
        await ws.close()
        return

    # We replicate the graph manually for streaming control.
    intake = run_intake(req.content, req.channel, req.audience, req.offer_id)
    await ws.send_text(json.dumps({"type": "intake", "intake": intake.model_dump()}))

    audit: list[ToolCallTrace] = []
    iterations: list[IterationRecord] = []
    current = req.content
    converged = False
    max_iters = settings().max_iterations

    for iter_no in range(1, max_iters + 1):
        verdicts: list[CriticVerdict] = []
        # Build per-critic prior state for the approval ratchet — this stops
        # critics from flip-flopping APPROVE↔REVISE between rounds purely on
        # stylistic LLM re-reads. Once a critic has approved, only a
        # deterministic structural regression can flip them back.
        prior_state = build_prior_state(iterations)

        async def run_one(name: str) -> CriticVerdict:
            loop_audit: list[ToolCallTrace] = []
            v = await asyncio.to_thread(
                CRITICS[name],
                current, intake, loop_audit, iter_no, prior_state,
            )
            audit.extend(loop_audit)
            return v

        tasks = [asyncio.create_task(run_one(n)) for n in CRITICS]
        for coro in asyncio.as_completed(tasks):
            v = await coro
            verdicts.append(v)
            await ws.send_text(json.dumps({
                "type": "critic", "verdict": v.model_dump(mode="json"),
            }))

        # Convergence: every critic must explicitly APPROVE. Per the
        # verdict-anchored scoring (APPROVE ⇒ score ≥ 8, REVISE ⇒ score ≤ 7),
        # this is equivalent to "all critic scores ≥ 8 with no outstanding
        # violations". Any REVISE — regardless of severity — means the
        # resolver should rewrite the content.
        converged = all(v.verdict == Verdict.APPROVE for v in verdicts)

        record = IterationRecord(
            iteration=iter_no, content=current, verdicts=verdicts,
        )
        if converged:
            # All approved — no rewrite needed; emit and stop.
            iterations.append(record)
            await ws.send_text(json.dumps({
                "type": "iteration", "iteration": record.model_dump(mode="json"),
            }))
            break

        # Not converged → ALWAYS run the resolver so the user gets a rewrite,
        # even on the final allowed iteration. The user can then accept it,
        # edit it, or trigger another adversarial round from the UI.
        revised, changelog = await asyncio.to_thread(
            run_resolver, current, intake, verdicts, audit, iter_no, prior_state,
        )
        record.revised_content = revised
        record.changelog = changelog
        iterations.append(record)
        await ws.send_text(json.dumps({
            "type": "iteration", "iteration": record.model_dump(mode="json"),
        }))
        current = revised

        # Stop looping once we've used our iteration budget. The just-emitted
        # record already contains the resolver's rewrite.
        if iter_no == max_iters:
            break

    response = ReviewResponse(
        final_content=current, converged=converged,
        iterations=iterations, intake=intake, audit_trail=audit,
    )
    try:
        await ws.send_text(json.dumps({
            "type": "done", "response": response.model_dump(mode="json"),
        }))
    except WebSocketDisconnect:
        pass
    await ws.close()


# ---------- Manual single-step endpoints (optional, for UI 'Edit' flow) ----------

class EditRequest(BaseModel):
    content: str
    channel: str | None = None
    audience: str | None = None
    offer_id: str | None = None


@router.post("/intake")
def do_intake(req: EditRequest) -> IntakeMetadata:
    return run_intake(req.content, req.channel, req.audience, req.offer_id)
