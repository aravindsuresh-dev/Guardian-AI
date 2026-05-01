"""Generic critic agent runner.

Each critic is configured by:
  - name (CriticName literal)
  - system prompt (its red-team mandate)
  - tool bundle (subset of skills/tools.py)
  - deterministic fallback: a function that runs the same tools directly and
    builds a CriticVerdict. Used when no LLM is configured OR as a sanity
    pre-check that always runs alongside the LLM.

The LLM is instructed to return a strict JSON envelope:
  { "verdict": "APPROVE" | "REVISE",
    "summary": "...",
    "violations": [
       {"rule_id": "...", "severity": "HARD|SOFT", "description": "...",
        "span": "...", "suggestion": "..."}
    ]
  }
"""
from __future__ import annotations

import json
from typing import Any, Callable

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.messages.ai import AIMessage

from app.agents.llm import get_chat_model
from app.models.schemas import (
    CriticName, CriticVerdict, IntakeMetadata, Severity,
    ToolCallTrace, Verdict, Violation,
)
from app.skills import _data


def _valid_rule_ids() -> set[str]:
    """Union of all rule_ids the LLM is allowed to cite."""
    return (
        {r["rule_id"] for r in _data.all_regulatory_rules()}
        | {r["rule_id"] for r in _data.all_brand_rules()}
    )


# Per-critic rule lane. An LLM cite outside its critic's lane is dropped
# so that, e.g., Ops Strategist can't cite FTC-* and Brand Guardian can't
# cite FCC/FTC rules. Lanes match guardianai_agent_roles.md exactly.
def _in_lane(name: str, rule_id: str) -> bool:
    if name == "fcc_enforcer":
        # All FTC-* rules.
        return rule_id.startswith("FTC-")
    if not rule_id.startswith("BRAND-"):
        return False
    try:
        n = int(rule_id.split("-", 1)[1])
    except (ValueError, IndexError):
        return False
    if name == "brand_guardian":
        # §1 Voice (1xx), §2 Terminology (2xx), §3 Prohibited words (3xx),
        # §6 CTAs (6xx, shared with Ops Strategist).
        return 100 <= n <= 399 or 600 <= n <= 699
    if name == "ops_strategist":
        # §4 Channel format (4xx) + §6 CTAs (6xx, shared with Brand Guardian).
        return 400 <= n <= 499 or 600 <= n <= 699
    if name == "persona_simulator":
        # §5 Audience tone (5xx).
        return 500 <= n <= 599
    if name == "technical_lead":
        # §7 Claim Standards (7xx) + §8 Disclosure Requirements (8xx).
        return 700 <= n <= 899
    return True


# Deterministic-fallback rule_ids that come from registry/spec lookups
# (offer registry, channel spec, CTA/UTM registry, audience-fit table).
# These are kept unconditionally — they are provably correct.
# All OTHER fallback rule_ids come from regex/keyword heuristics
# (urgency, all-caps, superlatives, prohibited-phrase matchers, jargon
# wordlists). When an LLM is configured, those interpretive flags require
# LLM corroboration on the same rule_id before being kept — this trades a
# small amount of recall for a large precision gain.
_STRUCTURAL_FALLBACK_RULES: set[str] = {
    "FTC-005",   # free/$0 claim missing offer-registry disclosure
    "FTC-013",   # trade-in eligibility mismatch (registry)
    "FTC-014",   # SMS TCPA mandatory elements (channel spec)
    "BRAND-401", # SMS length / mandatory elements
    "BRAND-402", # LinkedIn length
    "BRAND-403", # Email length / mandatory elements
    "BRAND-404", # Facebook / Instagram length
    "BRAND-405", # landing_page length
    "BRAND-406", # press_release length
    "BRAND-501", # channel-audience mismatch (audience-fit table)
    "BRAND-603", # prohibited CTA (CTA registry)
    "BRAND-604", # missing UTM parameters
    "BRAND-701", # quantitative claim contradicts registry (Tech Lead)
    "BRAND-801", # $0/free disclosure missing required conditions (Tech Lead)
}


def _grounded_rule_ids(audit: list[ToolCallTrace], agent_name: str,
                       iteration: int) -> set[str]:
    """Collect rule_ids the agent actually fetched/observed via its tool
    calls during this iteration. An LLM cite is only honored if its rule_id
    appears in this set (or in the deterministic fallback's outputs)."""
    grounded: set[str] = set()
    for tr in audit:
        if tr.agent != agent_name or tr.iteration != iteration:
            continue
        inp = tr.input or {}
        out = tr.output
        # Direct fetch: get_rule(rule_id=X)
        rid = inp.get("rule_id") if isinstance(inp, dict) else None
        if rid and out:
            grounded.add(rid)
        # List-of-rules outputs: search_regulations, search_brand_rules,
        # list_prohibited_terms, detect_prohibited_phrases, etc.
        if isinstance(out, list):
            for item in out:
                if isinstance(item, dict):
                    item_rid = item.get("rule_id")
                    if item_rid:
                        grounded.add(item_rid)
        elif isinstance(out, dict):
            item_rid = out.get("rule_id")
            if item_rid:
                grounded.add(item_rid)
    return grounded


def _verified_rule_ids(audit: list[ToolCallTrace], agent_name: str,
                       iteration: int) -> set[str]:
    """Collect rule_ids that a deterministic tool call this iteration has
    AFFIRMED as compliant against this content (e.g. check_price_accuracy
    returned verified=True with rule_ids_implicated=[FTC-005,...]).

    LLM cites of these rule_ids are dropped because the registry/spec lookup
    already proved the content satisfies them. This is the precision lever
    that prevents the FCC critic from oscillating "REVISE FTC-005" forever
    even after the resolver fixed it.
    """
    verified: set[str] = set()
    for tr in audit:
        if tr.agent != agent_name or tr.iteration != iteration:
            continue
        out = tr.output
        if not isinstance(out, dict):
            continue
        if not out.get("verified"):
            continue
        # The tool may report which rule_ids it covers. If absent, fall back
        # to a small map of (tool_name → rule_ids) for the structural skills.
        rids = out.get("rule_ids_implicated")
        if isinstance(rids, list):
            verified.update(str(r) for r in rids if isinstance(r, str))
            continue
        tool_to_rids = {
            "check_price_accuracy": {"FTC-005", "FTC-006", "BRAND-302", "BRAND-801"},
            "check_trade_in_eligibility": {"FTC-012", "FTC-013"},
            "verify_claim": {"BRAND-701", "BRAND-202", "FTC-003", "FTC-017"},
            "validate_mandatory_elements": {"FTC-014", "BRAND-401", "BRAND-403", "BRAND-404"},
            "validate_utm": {"BRAND-604"},
            "validate_cta": {"BRAND-603"},
        }
        verified.update(tool_to_rids.get(tr.tool, set()))
    return verified


JSON_INSTRUCTION = """
You MUST respond with a single JSON object (no prose, no markdown), with this exact shape:

{
  "verdict": "APPROVE" | "REVISE",
  "summary": "1-2 sentence rationale",
  "violations": [
    {
      "rule_id": "FTC-### or BRAND-###",
      "severity": "HARD" | "SOFT",
      "description": "Why this violates the rule, citing the relevant text",
      "span": "Exact substring from the content that violates the rule",
      "suggestion": "Concrete fix"
    }
  ]
}

Only cite rule_ids you have personally verified by calling the appropriate tool.
NEVER invent rule_ids. The ONLY valid rule_ids are FTC-001..FTC-020 and
BRAND-101..BRAND-106, BRAND-201..BRAND-208, BRAND-301..BRAND-315,
BRAND-401..BRAND-406, BRAND-501..BRAND-504, BRAND-601..BRAND-604,
BRAND-701..BRAND-704, BRAND-801..BRAND-805. Any violation citing an ID
outside this set will be rejected.
If you cannot find any HARD violation, return verdict=APPROVE with violations=[]
(SOFT violations may still be listed in an APPROVE).
"""


def _format_intake(intake: IntakeMetadata) -> str:
    return (
        f"Channel: {intake.channel}\n"
        f"Audience: {intake.audience or '(unspecified)'}\n"
        f"Offer ID: {intake.offer_id or '(unspecified)'}\n"
        f"Extracted claims: {intake.extracted_claims}"
    )


def _parse_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if text.startswith("```"):
        # strip code fence
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    # Find first { and last }
    a, b = text.find("{"), text.rfind("}")
    if a == -1 or b == -1:
        return None
    try:
        return json.loads(text[a: b + 1])
    except Exception:
        return None


def _run_with_tools(
    llm,
    system_prompt: str,
    user_prompt: str,
    tools: list,
    agent_name: str,
    iteration: int,
    audit: list[ToolCallTrace],
    max_steps: int = 6,
) -> str:
    """Tool-calling loop. Returns the final assistant text (expected JSON)."""
    bound = llm.bind_tools(tools)
    msgs = [SystemMessage(content=system_prompt + "\n\n" + JSON_INSTRUCTION),
            HumanMessage(content=user_prompt)]
    tool_by_name = {t.name: t for t in tools}
    for _ in range(max_steps):
        ai: AIMessage = bound.invoke(msgs)
        msgs.append(ai)
        tool_calls = getattr(ai, "tool_calls", None) or []
        if not tool_calls:
            return ai.content if isinstance(ai.content, str) else str(ai.content)
        for tc in tool_calls:
            name = tc["name"]
            args = tc.get("args", {}) or {}
            t = tool_by_name.get(name)
            if t is None:
                result: Any = {"error": f"unknown tool {name}"}
            else:
                try:
                    result = t.invoke(args)
                except Exception as e:  # noqa: BLE001
                    result = {"error": str(e)}
            audit.append(ToolCallTrace(
                agent=agent_name, tool=name, input=args, output=result,
                iteration=iteration,
            ))
            msgs.append(ToolMessage(
                content=json.dumps(result, default=str)[:8000],
                tool_call_id=tc.get("id", name),
            ))
    return "{}"


def build_prior_state(iterations: list) -> dict[str, dict[str, Any]]:
    """Compress prior IterationRecords into a per-critic state map.

    For each critic we track:
      - ``approved``       True iff the critic returned APPROVE in the
                            most recent prior iteration AND was *also*
                            APPROVE in every iteration before that
                            (sticky once-approved, always-approved unless
                            deterministic regresses — see ratchet below).
      - ``ever_approved``  True iff the critic returned APPROVE in any
                            prior iteration.
      - ``prev_rule_ids``  Set of rule_ids the critic flagged in the
                            immediately preceding iteration (used as the
                            regression baseline).

    This is the fuel for the approval-ratchet: once a critic has
    approved, their LLM cannot re-introduce HARD violations in later
    rounds unless the deterministic structural fallback flags the same
    rule_id. Without this, critics flip APPROVE↔REVISE round-over-round
    purely on stylistic LLM re-reads.
    """
    state: dict[str, dict[str, Any]] = {}
    if not iterations:
        return state
    last_iter = iterations[-1]
    last_verdicts = getattr(last_iter, "verdicts", None) or []
    for v in last_verdicts:
        state[v.agent] = {
            "approved": v.verdict == Verdict.APPROVE,
            "ever_approved": v.verdict == Verdict.APPROVE,
            "prev_rule_ids": {viol.rule_id for viol in v.violations},
        }
    # Walk earlier iterations to set ever_approved.
    for it in iterations[:-1]:
        for v in (getattr(it, "verdicts", None) or []):
            slot = state.setdefault(v.agent, {
                "approved": False, "ever_approved": False, "prev_rule_ids": set(),
            })
            if v.verdict == Verdict.APPROVE:
                slot["ever_approved"] = True
    return state


def run_critic(
    *,
    name: CriticName,
    system_prompt: str,
    tools: list,
    fallback: Callable[[str, IntakeMetadata, list[ToolCallTrace], int], list[Violation]],
    content: str,
    intake: IntakeMetadata,
    iteration: int,
    audit: list[ToolCallTrace],
    prior_state: dict[str, dict[str, Any]] | None = None,
) -> CriticVerdict:
    """Run one critic. Always run the deterministic fallback. If an LLM is
    configured, also run it and merge violations (deduped by rule_id+span)."""
    deterministic = fallback(content, intake, audit, iteration)

    llm = get_chat_model()
    llm_violations: list[Violation] = []
    summary = ""
    verdict = Verdict.APPROVE
    if llm is not None:
        user_prompt = (
            f"Review the following marketing content. Use your tools.\n\n"
            f"---INTAKE---\n{_format_intake(intake)}\n\n"
            f"---CONTENT---\n{content}\n---END---\n"
        )
        try:
            raw = _run_with_tools(
                llm, system_prompt, user_prompt, tools,
                agent_name=name, iteration=iteration, audit=audit,
            )
            parsed = _parse_json(raw) or {}
            summary = parsed.get("summary", "")
            allowlist = _valid_rule_ids()
            for v in parsed.get("violations") or []:
                rid = (v.get("rule_id") or "").strip()
                if rid not in allowlist:
                    # Drop hallucinated rule IDs.
                    continue
                if not _in_lane(name, rid):
                    # Drop out-of-lane cite (e.g., Ops citing FTC-*).
                    continue
                try:
                    llm_violations.append(Violation(
                        rule_id=rid,
                        severity=Severity(v.get("severity", "SOFT").upper()),
                        description=v.get("description", ""),
                        span=v.get("span"),
                        suggestion=v.get("suggestion"),
                    ))
                except Exception:
                    continue
            verdict = Verdict(parsed.get("verdict", "REVISE").upper())
        except Exception as e:  # noqa: BLE001
            summary = f"(LLM error: {e}; using deterministic checks only)"

    # ---- Precision pass #1: drop ungrounded LLM cites ----
    # An LLM cite is only kept if the agent verified the rule via a tool
    # call this iteration, or the deterministic fallback already flagged it
    # (fallback flags are by definition tool-grounded code paths).
    if llm is not None and llm_violations:
        grounded = _grounded_rule_ids(audit, name, iteration)
        grounded |= {v.rule_id for v in deterministic}
        before = len(llm_violations)
        llm_violations = [v for v in llm_violations if v.rule_id in grounded]
        dropped = before - len(llm_violations)
        if dropped and not summary:
            summary = f"Dropped {dropped} ungrounded cite(s)."

    # ---- Precision pass #1.5: drop LLM cites of deterministically-verified rules ----
    # When a structural tool (check_price_accuracy, validate_mandatory_elements,
    # validate_utm, etc.) returned verified=True for the content, the LLM
    # cannot override that finding by re-citing the same rule_id. This stops
    # the FCC critic re-flagging FTC-005 forever even after the resolver
    # has actually satisfied the offer-registry disclosure.
    if llm is not None and llm_violations:
        verified = _verified_rule_ids(audit, name, iteration)
        # Subtract rules where the deterministic fallback ALSO flagged them —
        # if both code paths disagree, the fallback wins (it is the structural
        # source of truth) and we should drop the LLM cite anyway.
        verified -= {v.rule_id for v in deterministic}
        if verified:
            llm_violations = [v for v in llm_violations if v.rule_id not in verified]

    # ---- Precision pass #2: filter interpretive deterministic flags ----
    # Structural flags (registry/spec-grounded) are kept unconditionally.
    # Interpretive flags (regex/keyword heuristics) require LLM agreement
    # on the same rule_id when an LLM is configured.
    if llm is not None:
        llm_rule_ids = {v.rule_id for v in llm_violations}
        filtered_det: list[Violation] = []
        for v in deterministic:
            if v.rule_id in _STRUCTURAL_FALLBACK_RULES:
                filtered_det.append(v)
            elif v.rule_id in llm_rule_ids:
                filtered_det.append(v)
            # else: drop interpretive flag with no LLM corroboration
        deterministic = filtered_det

    # ---- Precision pass #3: approval ratchet (anti-oscillation) ----
    # Once a critic has APPROVED in a prior iteration, their LLM may not
    # re-introduce HARD violations in later rounds unless the deterministic
    # structural fallback flags the same rule_id this iteration. Stylistic
    # LLM regressions are demoted to SOFT so they no longer block APPROVE.
    # This stops the classic flip-flop where a critic approves round 1, then
    # flips to REVISE round 2 on a re-read that the deterministic checks
    # disagree with — which would then force the resolver to break what
    # another critic approved.
    if (llm is not None and prior_state and llm_violations
            and prior_state.get(name, {}).get("ever_approved")):
        det_hard_rule_ids = {
            v.rule_id for v in deterministic if v.severity == Severity.HARD
        }
        ratcheted: list[Violation] = []
        for v in llm_violations:
            if v.severity == Severity.HARD and v.rule_id not in det_hard_rule_ids:
                # Demote to SOFT — keep the signal but don't trigger REVISE.
                ratcheted.append(v.model_copy(update={"severity": Severity.SOFT}))
            else:
                ratcheted.append(v)
        llm_violations = ratcheted

    # Merge: dedupe by (rule_id, span)
    seen = set()
    merged: list[Violation] = []
    for v in deterministic + llm_violations:
        key = (v.rule_id, (v.span or "")[:60])
        if key in seen:
            continue
        seen.add(key)
        merged.append(v)

    # Recompute verdict based on HARD findings
    has_hard = any(v.severity == Severity.HARD for v in merged)
    if has_hard:
        verdict = Verdict.REVISE
    elif llm is None:
        verdict = Verdict.APPROVE

    if not summary:
        summary = (
            f"{len(merged)} violation(s) found"
            f" ({sum(v.severity == Severity.HARD for v in merged)} HARD)"
            if merged else "No violations found."
        )
    return CriticVerdict(
        agent=name, verdict=verdict, summary=summary,
        violations=merged, iteration=iteration,
    )
