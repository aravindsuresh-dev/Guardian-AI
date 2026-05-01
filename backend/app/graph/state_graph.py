"""LangGraph state machine for Guardian AI.

Flow:

  intake ──► fan-out (5 critics in parallel) ──► aggregate ──► gate
                                                                 │
                                       converged or max iters? ──┤
                                                                 ▼
                                                              resolver
                                                                 │
                                                                 ▼
                                                          (next iter or END)

We model `fan-out` by adding a node per critic that the graph runs
concurrently, then merge through reducers on `ReviewState.verdicts`.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any

from typing_extensions import TypedDict

from langgraph.graph import StateGraph, END

from app.agents.critics import CRITICS
from app.agents.intake import run_intake
from app.agents.resolver import run_resolver
from app.agents.runner import build_prior_state
from app.config import settings
from app.models.schemas import (
    CriticVerdict, IntakeMetadata, IterationRecord, Severity, ToolCallTrace,
    Verdict,
)


class ReviewState(TypedDict, total=False):
    # Inputs
    original_content: str
    channel_hint: str | None
    audience_hint: str | None
    offer_id_hint: str | None
    # Working
    intake: IntakeMetadata
    iteration: int
    current_content: str
    verdicts: Annotated[list[CriticVerdict], operator.add]
    iterations: Annotated[list[IterationRecord], operator.add]
    audit: Annotated[list[ToolCallTrace], operator.add]
    converged: bool
    on_progress: Any  # optional async callback


# ---------- Nodes ----------

def node_intake(state: ReviewState) -> dict[str, Any]:
    intake = run_intake(
        state["original_content"],
        channel_hint=state.get("channel_hint"),
        audience_hint=state.get("audience_hint"),
        offer_id_hint=state.get("offer_id_hint"),
    )
    return {
        "intake": intake,
        "iteration": 1,
        "current_content": state["original_content"],
        "verdicts": [],
        "iterations": [],
        "audit": [],
        "converged": False,
    }


def _make_critic_node(name: str):
    def node(state: ReviewState) -> dict[str, Any]:
        audit: list[ToolCallTrace] = []
        prior_state = build_prior_state(state.get("iterations") or [])
        verdict = CRITICS[name](
            content=state["current_content"],
            intake=state["intake"],
            audit=audit,
            iteration=state["iteration"],
            prior_state=prior_state,
        )
        return {"verdicts": [verdict], "audit": audit}
    return node


def _is_converged(verdicts: list[CriticVerdict]) -> bool:
    """All critics must explicitly APPROVE for the round to be considered
    converged. Severity of violations is irrelevant here — if any critic
    returned REVISE, the resolver should run and the round is not approved.
    The legacy ``block_on`` setting is retained for backward compatibility but
    no longer relaxes this check.
    """
    return all(v.verdict == Verdict.APPROVE for v in verdicts)


def node_aggregate(state: ReviewState) -> dict[str, Any]:
    iter_no = state["iteration"]
    # Filter verdicts of THIS iteration (operator.add accumulates across iters)
    this_iter = [v for v in state["verdicts"] if v.iteration == iter_no]
    converged = _is_converged(this_iter)

    record = IterationRecord(
        iteration=iter_no,
        content=state["current_content"],
        verdicts=this_iter,
    )

    if converged:
        return {
            "converged": True,
            "iterations": [record],
        }

    # Run resolver
    audit: list[ToolCallTrace] = []
    prior_state = build_prior_state(state.get("iterations") or [])
    revised, changelog = run_resolver(
        state["current_content"], state["intake"], this_iter,
        audit=audit, iteration=iter_no, prior_state=prior_state,
    )
    record.revised_content = revised
    record.changelog = changelog

    return {
        "iterations": [record],
        "current_content": revised,
        "iteration": iter_no + 1,
        "audit": audit,
        "converged": False,
    }


def gate_router(state: ReviewState) -> str:
    if state.get("converged"):
        return "end"
    if state["iteration"] > settings().max_iterations:
        return "end"
    return "loop"


# ---------- Graph builder ----------

def build_graph():
    g = StateGraph(ReviewState)

    g.add_node("intake", node_intake)
    for name in CRITICS:
        g.add_node(name, _make_critic_node(name))
    g.add_node("aggregate", node_aggregate)

    g.set_entry_point("intake")
    # fan-out: intake → all 5 critics
    for name in CRITICS:
        g.add_edge("intake", name)
        g.add_edge(name, "aggregate")
    # gate
    g.add_conditional_edges(
        "aggregate",
        gate_router,
        {"loop": "fcc_enforcer", "end": END},
    )
    # When we loop, we need ALL 5 critics again — add edges from aggregate to
    # each of the others as well so the fan-out recurs. The conditional edge
    # above only routes to one; we add explicit additional edges.
    # Simpler: add a 'reloop' node that fans out to all 5.
    return g


def build_graph_v2():
    """Use a dedicated 'fanout' node so loop re-enters all 5 critics."""
    g = StateGraph(ReviewState)

    g.add_node("intake", node_intake)
    g.add_node("fanout", lambda s: {})  # passthrough
    for name in CRITICS:
        g.add_node(name, _make_critic_node(name))
    g.add_node("aggregate", node_aggregate)

    g.set_entry_point("intake")
    g.add_edge("intake", "fanout")
    for name in CRITICS:
        g.add_edge("fanout", name)
        g.add_edge(name, "aggregate")
    g.add_conditional_edges(
        "aggregate", gate_router,
        {"loop": "fanout", "end": END},
    )
    return g.compile()


GRAPH = build_graph_v2()
