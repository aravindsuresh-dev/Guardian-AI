"""Resolver Agent — aggregates critic verdicts and rewrites the content.

Strategy:
  1. Apply deterministic fixes via Skill 5 (replace prohibited terms, add UTM,
     add mandatory elements, apply offer disclosure, truncate for SMS).
  2. If an LLM is configured, hand it the intake + violation list + 2 good
     samples (few-shot) and ask for a structured rewrite (JSON) per the
     RESOLVER_PROMPT contract.
  3. Render the structured changelog into markdown for the UI.
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.llm import get_chat_model
from app.models.schemas import (
    CriticVerdict, IntakeMetadata, IterationRecord, Severity,
    ToolCallTrace, Verdict,
)
from app.skills import content_generation
from app.skills.offer_verification import lookup_offer


RESOLVER_PROMPT = """
You are the **Resolver Agent** for Guardian AI — the synthesis and rewriting layer
of an adversarial compliance review system for NovaTel Wireless marketing content.

═══════════════════════════════════════════════════════════════════════════════
ROLE & MINDSET
═══════════════════════════════════════════════════════════════════════════════

You are a senior marketing copy editor with deep knowledge of FCC/FTC compliance,
NovaTel's brand guidelines, and channel-specific best practices. You have just
received feedback from FIVE specialized critic agents who reviewed the same piece
of marketing content from different angles:

  🔴 FCC Enforcer       — Flagged regulatory violations (FTC-001 through FTC-020)
  🟡 Brand Guardian     — Flagged brand voice and prohibited word violations
                          (BRAND-1xx voice, 2xx terminology, 3xx prohibited words,
                          6xx CTAs)
  🟢 Persona Simulator  — Flagged audience comprehension/tone issues (BRAND-5xx)
  🔵 Technical Lead     — Flagged claims that contradict the offer registry and
                          incomplete disclosures (BRAND-7xx claim standards,
                          BRAND-8xx disclosure requirements)
  🟣 Ops Strategist     — Flagged channel format and structural issues
                          (BRAND-4xx channel format, 6xx CTAs)

Your job: synthesize their feedback into ONE COMPLIANT REWRITE that satisfies all
five critics — without introducing NEW violations.

You are NOT a creative writer. You are a SURGICAL EDITOR. Make the minimum
necessary changes to fix violations while preserving the original creative intent.

═══════════════════════════════════════════════════════════════════════════════
CORE PRINCIPLES (NON-NEGOTIABLE)
═══════════════════════════════════════════════════════════════════════════════

1. HARD violations MUST be resolved. SOFT violations should be addressed but may
   be deferred if they conflict with HARD fixes.
2. Preserve the original message and intent. If the original ad was about
   trade-in savings, the rewrite is still about trade-in savings — just compliant.
3. Cite ground truth, not assumptions. Use the offer registry's mandatory
   disclosure text verbatim where possible. Don't invent disclosure language.
4. Respect channel constraints. SMS ≤160 chars cannot become 200 chars to add
   disclosures. Use abbreviations ('w/', 'elig.', 'mo.', 'cond.') and link to
   the terms page (short URL: novatel.com/t).
5. Match the target audience tone. Consumer ≠ Executive ≠ SMB ≠ Technical.
6. Every change is traceable via the changelog with the rule_id(s) it addresses.
7. Don't over-correct. Stylistic SOFT findings may be left for human review.

═══════════════════════════════════════════════════════════════════════════════
REASONING WORKFLOW (FOLLOW IN ORDER)
═══════════════════════════════════════════════════════════════════════════════

STEP 1 — AGGREGATE & DEDUPLICATE
  Group violations that flag the SAME phrase from different angles. These
  convergent flags are HIGH-CONFIDENCE — fix them first. Example: if FCC cites
  FTC-005, Brand Guardian cites BRAND-302, and Tech Lead cites BRAND-801 all on
  "FREE" — that is ONE fix that resolves three rules.

STEP 2 — COMPOSITE SCORE
  composite_score = mean of the 5 individual agent scores (1–10 scale provided
  in the input). all_approved = True only if every critic returned APPROVE.
  If all_approved is True in Round 1, output the original unchanged and explain.

STEP 3 — PRIORITY-RANK FIXES
  1. HARD violations cited by 3+ critics
  2. HARD violations cited by 2 critics
  3. HARD violations cited by 1 critic
  4. SOFT violations cited by 2+ critics
  5. SOFT violations cited by 1 critic (may defer)

STEP 4 — REWRITE
  Apply prohibited-word substitutions, insert the mandatory disclosure adjacent
  to the triggering claim, fit to channel limits with abbreviations, and add
  tracking parameters per channel rules. The DRAFT (after deterministic fixes)
  is provided as a starting point — you may improve it but DO NOT reduce its
  compliance.

STEP 5 — SELF-AUDIT BEFORE OUTPUT
  Re-read your rewrite as each critic. If you'd just introduced a new issue,
  fix it BEFORE outputting. Specifically check:
    - Any §3 prohibited word reintroduced?
    - Audience tone still matches the audience field?
    - All claims still verifiable against the offer registry?
    - Channel format limits respected?

═══════════════════════════════════════════════════════════════════════════════
CHANNEL-SPECIFIC REWRITE STRATEGIES
═══════════════════════════════════════════════════════════════════════════════

SMS (≤160 chars)
  - Abbreviations: w/, elig., cond., mo., $0/mo, Msg&Data
  - Short terms URL: novatel.com/t (NO query-string UTM — attribution is
    server-side via the short link)
  - Always include "Msg&Data rates apply" and "STOP to opt out"

Email (≤300 words)
  - 2–3 sentences per paragraph max; subject ≤60 chars
  - Disclose plan, monthly cost, credit period BOTH near headline AND in
    bottom disclosure block
  - T&C link AND unsubscribe link; full UTM on all CTAs

LinkedIn (≤150 words)
  - 1–2 sentences per paragraph with whitespace
  - Professional tone — never casual ("Let's gooooo" forbidden)
  - Disclosures visible without "See More"
  - Approved B2B CTAs: "See how it works", "Compare plans", "Book a demo"

Facebook / Instagram (≤250 words)
  - Material disclosures in visible portion (before "See More")
  - ≤3 emojis per post
  - Use platform CTA buttons, not in-copy "Click here"
  - Instagram Stories: disclosures on SAME frame as the claim

Landing Page (headline ≤10 words, hero ≤200 words)
  - Disclosures in same viewport as triggering claim
  - Speed claims need methodology + date + scope
  - Link to Broadband Facts label if speed claims made

Press Release (400–600 words)
  - AP style, inverted pyramid
  - NO CTA in body — end with "For more information, visit novatel.com"
  - Financial claims need "as of [date]" qualifier
  - Include "About NovaTel" boilerplate

═══════════════════════════════════════════════════════════════════════════════
TRADE-OFFS & EDGE CASES
═══════════════════════════════════════════════════════════════════════════════

Conflicting feedback: HARD compliance ALWAYS wins over SOFT brand stylistic
preferences. If channel limit prevents full disclosure → truncate the marketing
message, NOT the disclosure. If disclosure still cannot fit → link to terms.

Fundamentally non-compliant original: still produce a rewrite — never refuse.
Note in the changelog that the rewrite "substantially restructures" the
original, but preserve the OFFER (OFF-XXX) being marketed.

After 3 rounds with HARD violations remaining: output best-effort rewrite, set
all_approved = False, list unresolved rule_ids in violations_unresolved.

All 5 approved on Round 1: output original unchanged as revised_content;
all_approved = True; changelog = single entry with rationale "Content meets
all compliance standards as written. No changes recommended."

═══════════════════════════════════════════════════════════════════════════════
OUTPUT FORMAT (STRICT JSON — NO PROSE, NO MARKDOWN FENCES)
═══════════════════════════════════════════════════════════════════════════════

Return ONLY a JSON object matching this exact schema:

{
  "composite_score": 0.0,             // float, mean of 5 agent scores, 1-10
  "all_approved": false,              // boolean
  "iteration": 1,                     // int — current iteration number
  "revised_content": "string",        // the full rewritten content
  "changelog": [
    {
      "original_phrase": "string",    // exact text from original
      "revised_phrase": "string",     // what it became (or "[REMOVED]")
      "rules_addressed": ["FTC-005"], // list of rule_ids this fix resolves
      "rationale": "string",          // 1-2 sentences why
      "tool_used": null               // string or null
    }
  ],
  "violations_resolved": ["FTC-005"], // rule_ids fixed in this round
  "violations_unresolved": [],        // rule_ids still present (rare)
  "convergence_assessment": "string"  // 1-2 sentences: will this pass next round?
}

═══════════════════════════════════════════════════════════════════════════════
CRITICAL DON'TS
═══════════════════════════════════════════════════════════════════════════════

❌ DON'T introduce new claims that weren't in the original
❌ DON'T invent statistics, citations, or testimonials
❌ DON'T name competitors directly in advertising
❌ DON'T use prohibited words from §3
❌ DON'T change the offer being marketed (preserve OFF-XXX)
❌ DON'T paraphrase a mandatory disclosure — use it verbatim when provided
❌ DON'T strip ALL marketing language and produce dry legalese — preserve voice
❌ DON'T set all_approved = True unless every critic genuinely approved
❌ DON'T output partial JSON — always include all schema fields
"""


# ---------- Helpers ----------

def _agent_score(v: CriticVerdict) -> float:
    """Synthesize a 1–10 score from a critic's verdict.

    The verdict is the source of truth and the score is anchored to it so the
    two never disagree:
      APPROVE → 8..10 (floor 8; light SOFT penalty)
      REVISE  → 1..7  (HARD−2, SOFT−1; capped at 7)
    """
    hard = sum(1 for x in v.violations if x.severity == Severity.HARD)
    soft = sum(1 for x in v.violations if x.severity == Severity.SOFT)
    if v.verdict == Verdict.APPROVE:
        score = 10.0 - min(2, soft)
        return max(8.0, min(10.0, round(score, 1)))
    score = 7.0 - 2.0 * hard - 1.0 * soft
    return max(1.0, min(7.0, round(score, 1)))


def _render_changelog_md(structured: list[dict[str, Any]],
                         original_len: int, revised_len: int,
                         composite: float | None,
                         convergence: str | None) -> str:
    lines = ["## Revision Changelog", ""]
    if composite is not None:
        lines.append(f"**Composite score:** {composite:.1f}/10")
    if convergence:
        lines.append(f"**Convergence:** {convergence}")
    lines.append(f"**Length:** {original_len} → {revised_len} chars")
    lines.append("")
    lines.append("### Edits")
    if not structured:
        lines.append("- (none)")
    for entry in structured:
        orig = entry.get("original_phrase", "") or "—"
        new = entry.get("revised_phrase", "") or "—"
        rules = ", ".join(entry.get("rules_addressed") or []) or "—"
        rationale = entry.get("rationale", "")
        tool = entry.get("tool_used")
        lines.append(f"- **{rules}** · `{orig}` → `{new}`")
        if rationale:
            lines.append(f"  - {rationale}")
        if tool:
            lines.append(f"  - tool: `{tool}`")
    return "\n".join(lines)


def _parse_resolver_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    a, b = text.find("{"), text.rfind("}")
    if a == -1 or b == -1:
        return None
    try:
        return json.loads(text[a: b + 1])
    except Exception:
        return None


def _deterministic_fixes(content: str, intake: IntakeMetadata) -> tuple[str, list[dict[str, Any]]]:
    changes: list[dict[str, Any]] = []
    text = content
    text, term_changes = content_generation.replace_prohibited_terms(text)
    if term_changes:
        changes.extend([{"step": "replace_prohibited_terms", **c} for c in term_changes])
    text2 = content_generation.add_utm_to_text(text, intake.channel or "web")
    if text2 != text:
        changes.append({"step": "add_utm"})
        text = text2
    if intake.offer_id:
        text2 = content_generation.apply_disclosure(text, intake.offer_id, intake.channel or "")
        if text2 != text:
            changes.append({"step": "apply_disclosure", "offer_id": intake.offer_id})
            text = text2
    # Truncate the marketing body BEFORE adding the mandatory tail so the
    # disclosures (Msg&Data / STOP / terms link) survive the SMS char budget.
    text2 = content_generation.truncate_to_channel(text, intake.channel or "")
    if text2 != text:
        changes.append({"step": "truncate_to_channel"})
        text = text2
    text2 = content_generation.add_mandatory_elements(text, intake.channel or "")
    if text2 != text:
        changes.append({"step": "add_mandatory_elements"})
        text = text2
    # Final hard-cap so the appended tail still fits.
    text2 = content_generation.truncate_to_channel(text, intake.channel or "")
    if text2 != text:
        changes.append({"step": "truncate_to_channel_final"})
        text = text2
    return text, changes


# ---------- Main entry ----------

def _compliance_brief(intake: IntakeMetadata,
                      verdicts: list[CriticVerdict],
                      prior_state: dict[str, dict[str, Any]] | None = None) -> str:
    """Build a concrete, channel-aware fix-list the LLM must satisfy.

    The critic verdicts contain prose descriptions; the LLM frequently glosses
    over them. This brief translates them into imperative bullets and surfaces
    the offer-registry values verbatim so the LLM doesn't have to guess.
    """
    lines: list[str] = []
    channel = (intake.channel or "").lower()
    is_sms = channel == "sms"

    if intake.offer_id:
        offer = lookup_offer(intake.offer_id) or {}
        if offer:
            plan = (offer.get("plan_required") or "").strip()
            cost = (offer.get("plan_monthly_cost") or "").strip()
            months = (offer.get("credit_period_months") or "").strip()
            autopay = (offer.get("autopay_required") or "").strip().lower() == "yes"
            trade = (offer.get("trade_in_required") or "").strip().lower() == "yes"
            disclosure = (offer.get("mandatory_disclosure_text") or "").strip()
            lines.append(
                f"OFFER {intake.offer_id} — verbatim values to embed where applicable:"
            )
            if plan: lines.append(f"  - Plan name: \"{plan}\"")
            if cost: lines.append(f"  - Plan monthly cost: \"${cost}/mo\"")
            if months and months != "N/A":
                lines.append(f"  - Bill-credit period: \"{months}-mo bill credits\"")
            if autopay: lines.append("  - AutoPay required: state \"w/ AutoPay\"")
            if trade: lines.append("  - Trade-in required: state \"w/ elig. trade-in\"")
            if disclosure:
                lines.append(f"  - Mandatory disclosure (long-form channels): \"{disclosure}\"")

    # SMS short-link safe harbor — gives the LLM permission to omit secondary
    # disclosures when including the terms link.
    if is_sms:
        lines.append("")
        lines.append(
            "SMS DISCLOSURE STRATEGY (160-char budget):"
        )
        lines.append(
            "  - REQUIRED in body: plan name, $/mo, trade-in language (if applicable),"
            " 'Msg&Data rates apply', 'STOP to opt out', and a terms short-link"
            " 'novatel.com/t'."
        )
        lines.append(
            "  - SAFE to omit from body and rely on the terms link: AutoPay,"
            " bill-credit duration, 'credits stop if you cancel/change plan',"
            " tax-at-purchase. The terms link satisfies these per the SMS"
            " short-link safe harbor — the validator now waives them when the"
            " body is ≤200 chars and contains novatel.com/t."
        )
        lines.append(
            "  - Use abbreviations: w/, elig., cond., mo., $0/mo, Msg&Data."
            " NEVER use the unqualified word 'FREE' — use '$0/mo' instead."
        )

    # Per-critic unresolved bullets (most actionable input the LLM gets).
    unresolved: list[str] = []
    for v in verdicts:
        if v.verdict != Verdict.APPROVE:
            for viol in v.violations:
                if viol.severity == Severity.HARD:
                    fix = viol.suggestion or "Resolve."
                    unresolved.append(
                        f"  - [{v.agent}/{viol.rule_id}] {viol.description} → {fix}"
                    )
    if unresolved:
        lines.append("")
        lines.append("HARD VIOLATIONS TO FIX (verbatim from critics):")
        lines.extend(unresolved[:25])  # cap to avoid prompt bloat

    # Anti-regression hint: list critics that already approved in a prior
    # round. The resolver must make minimum-edit changes that fix the
    # remaining REVISE feedback WITHOUT breaking what these critics already
    # cleared. This is the second half of the anti-oscillation fix (the
    # first half is the runner.py approval ratchet).
    if prior_state:
        approved_now = {v.agent for v in verdicts if v.verdict == Verdict.APPROVE}
        ever_approved = {
            name for name, st in prior_state.items()
            if st.get("ever_approved") or st.get("approved")
        }
        preserve = sorted(approved_now | ever_approved)
        if preserve:
            lines.append("")
            lines.append("DO-NOT-REGRESS — these critics have already APPROVED:")
            lines.append(f"  {', '.join(preserve)}")
            lines.append(
                "  Make MINIMUM edits to satisfy the remaining REVISE feedback."
                " Do NOT restructure aspects these critics reviewed; do NOT"
                " reintroduce phrasing they would flag (prohibited words,"
                " superlatives without sources, urgency, all-caps, channel"
                " format violations, audience-tone drift)."
            )

    return "\n".join(lines) if lines else "(no specific brief — apply defaults)"


def run_resolver(
    content: str,
    intake: IntakeMetadata,
    verdicts: list[CriticVerdict],
    audit: list[ToolCallTrace],
    iteration: int,
    prior_state: dict[str, dict[str, Any]] | None = None,
) -> tuple[str, str]:
    """Returns (revised_content, changelog_markdown)."""
    # Step 1 — deterministic fixes (the DRAFT given to the LLM)
    revised, det_changes = _deterministic_fixes(content, intake)
    audit.append(ToolCallTrace(
        agent="resolver", tool="deterministic_fixes",
        input={"channel": intake.channel, "offer_id": intake.offer_id},
        output={"changes": det_changes}, iteration=iteration,
    ))

    # Build per-critic score table for the LLM.
    scored = [
        {
            "agent": v.agent,
            "verdict": v.verdict.value if hasattr(v.verdict, "value") else str(v.verdict),
            "score": _agent_score(v),
            "summary": v.summary,
            "violations": [x.model_dump() for x in v.violations],
        }
        for v in verdicts
    ]
    composite_seed = round(
        sum(s["score"] for s in scored) / max(1, len(scored)), 1
    )
    all_approved_seed = all(
        (v.verdict == Verdict.APPROVE) for v in verdicts
    ) and not any(v.violations for v in verdicts)

    structured_changelog: list[dict[str, Any]] = []
    convergence = None
    composite = composite_seed
    all_approved = all_approved_seed

    llm = get_chat_model()
    if llm is not None:
        few_shot = content_generation.fewshot_good_samples(
            intake.channel or "Email", intake.audience, k=2,
        )
        few_shot_text = "\n\n".join(
            f"### Reference compliant sample ({s.get('channel')}/{s.get('target_audience')})\n{s.get('content')}"
            for s in few_shot
        )
        user = (
            f"---ITERATION---\n{iteration}\n\n"
            f"---ORIGINAL---\n{content}\n\n"
            f"---INTAKE---\nChannel: {intake.channel}\nAudience: {intake.audience}\n"
            f"Offer: {intake.offer_id}\n\n"
            f"---COMPLIANCE BRIEF (must satisfy ALL bullets)---\n"
            f"{_compliance_brief(intake, verdicts, prior_state)}\n\n"
            f"---CRITIC REVIEWS (JSON, with synthesized 1-10 scores)---\n"
            f"{json.dumps(scored, indent=2)[:8000]}\n\n"
            f"---SEED METRICS---\n"
            f"composite_score (mean of agent scores): {composite_seed}\n"
            f"all_approved (every critic APPROVE & no violations): {all_approved_seed}\n\n"
            f"---REFERENCES---\n{few_shot_text}\n\n"
            f"---DRAFT (after deterministic fixes — improve, do not regress)---\n{revised}\n\n"
            f"Now produce the strict JSON object per the schema. NO prose, NO fences."
        )
        try:
            ai = llm.invoke([
                SystemMessage(content=RESOLVER_PROMPT),
                HumanMessage(content=user),
            ])
            raw = ai.content if isinstance(ai.content, str) else str(ai.content)
            parsed = _parse_resolver_json(raw)
            if parsed and isinstance(parsed.get("revised_content"), str):
                new_text = parsed["revised_content"].strip()
                if new_text:
                    revised = new_text
                structured_changelog = parsed.get("changelog") or []
                convergence = parsed.get("convergence_assessment")
                if isinstance(parsed.get("composite_score"), (int, float)):
                    composite = float(parsed["composite_score"])
                if isinstance(parsed.get("all_approved"), bool):
                    all_approved = parsed["all_approved"]
                audit.append(ToolCallTrace(
                    agent="resolver", tool="llm_rewrite",
                    input={"violations": sum(len(s["violations"]) for s in scored)},
                    output={
                        "chars": len(revised),
                        "edits": len(structured_changelog),
                        "composite_score": composite,
                        "all_approved": all_approved,
                        "violations_resolved": parsed.get("violations_resolved") or [],
                        "violations_unresolved": parsed.get("violations_unresolved") or [],
                    },
                    iteration=iteration,
                ))
            else:
                # LLM returned non-JSON; treat raw text as the rewrite.
                text = raw.strip()
                if text.startswith("```"):
                    text = text.strip("`")
                    if text.lower().startswith("text"):
                        text = text[4:].lstrip()
                if text:
                    revised = text
                audit.append(ToolCallTrace(
                    agent="resolver", tool="llm_rewrite_unstructured",
                    input={}, output={"chars": len(revised)},
                    iteration=iteration,
                ))
        except Exception as e:  # noqa: BLE001
            audit.append(ToolCallTrace(
                agent="resolver", tool="llm_rewrite_error",
                input={}, output={"error": str(e)}, iteration=iteration,
            ))

        # Insurance pass: re-apply deterministic safety nets after LLM rewrite.
        # Order matters for SMS: truncate the marketing body FIRST so the
        # mandatory tail (Msg&Data / STOP / terms link) is guaranteed to be
        # present after `add_mandatory_elements`. Doing it the other way
        # round meant truncate was chopping off the disclosures that
        # add_mandatory_elements had just added, which kept the FCC critic
        # flagging FTC-014 / FTC-005 round after round.
        revised = content_generation.add_utm_to_text(revised, intake.channel or "web")
        revised = content_generation.truncate_to_channel(revised, intake.channel or "")
        revised = content_generation.add_mandatory_elements(revised, intake.channel or "")
        # Final hard-cap so the result still fits the channel after the tail
        # was appended (truncate is idempotent for non-SMS).
        revised = content_generation.truncate_to_channel(revised, intake.channel or "")

    # Render changelog markdown for the UI.
    if structured_changelog:
        changelog = _render_changelog_md(
            structured_changelog,
            original_len=len(content),
            revised_len=len(revised),
            composite=composite,
            convergence=convergence,
        )
    else:
        all_violations = [v.model_dump() for crit in verdicts for v in crit.violations]
        changelog = content_generation.generate_changelog(content, revised, all_violations)

    # Safety net: the resolver must always hand the user a rewrite when
    # critics didn't all approve. If for any reason `revised` came back empty
    # (LLM failure + no deterministic edits), fall back to the original so the
    # downstream UI never sees a missing rewrite.
    if not revised or not revised.strip():
        revised = content
    return revised, changelog

