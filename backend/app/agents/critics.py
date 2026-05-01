"""The 5 critic agents and their deterministic fallback checks.

Each agent exposes:
  - SYSTEM_PROMPT
  - TOOLS (subset of skills)
  - run(content, intake, audit, iteration) -> CriticVerdict

Deterministic fallbacks ensure the system works even without an LLM key,
and serve as a sanity floor merged with the LLM verdict.
"""
from __future__ import annotations

from typing import Any

from app.agents.runner import run_critic
from app.models.schemas import (
    CriticVerdict, IntakeMetadata, Severity, ToolCallTrace, Violation,
)
from app.skills import (
    compliance_lookup, offer_verification, content_analysis, channel_validation,
)
from app.skills.tools import (
    COMPLIANCE_LOOKUP_TOOLS, OFFER_VERIFICATION_TOOLS,
    CONTENT_ANALYSIS_TOOLS, CHANNEL_VALIDATION_TOOLS,
)


def _audit(audit: list[ToolCallTrace], agent: str, iteration: int,
           tool: str, inputs: dict, output: Any) -> None:
    audit.append(ToolCallTrace(
        agent=agent, tool=tool, input=inputs, output=output, iteration=iteration,
    ))


# ============ FCC Enforcer ============

FCC_PROMPT = """You are the FCC Enforcer for Guardian AI.

Persona: a senior FCC compliance attorney auditing this content as if preparing
for an enforcement action. Cold, precise, legal-tone. Cite specific FCC/FTC
enforcement actions and AG settlements when relevant.

Mindset: \"If this ad ran tomorrow and a consumer filed a complaint, would
NovaTel face a fine? My job is to find every regulatory exposure before it ships.\"

Mission: ensure every claim meets federal regulatory standards — material
disclosures, deceptive 'free'/$0 claims, unsubstantiated speed/superlative
claims, unlimited-data claims, trade-in eligibility, BOGO conditions, SMS TCPA
requirements, and price-advertising rules.

Use these tools — and ONLY cite rule_ids you have actually fetched:
  - search_regulations / get_rule
  - lookup_offer / verify_claim / check_price_accuracy / check_trade_in_eligibility
  - validate_mandatory_elements (for SMS TCPA elements)

LANE — you OWN: ALL FTC-001 through FTC-020.
DO NOT cite any BRAND-* rule — those belong to other critics and will be
dropped from your verdict.

Severity: rules with severity=HARD must trigger verdict=REVISE.
"""

FCC_TOOLS = COMPLIANCE_LOOKUP_TOOLS + OFFER_VERIFICATION_TOOLS + [
    t for t in CHANNEL_VALIDATION_TOOLS if t.name == "validate_mandatory_elements"
]


def _fcc_fallback(content: str, intake: IntakeMetadata,
                  audit: list[ToolCallTrace], iteration: int) -> list[Violation]:
    out: list[Violation] = []
    agent = "fcc_enforcer"
    # Free / $0 disclosure check
    if intake.offer_id:
        pc = offer_verification.check_price_accuracy(content, intake.offer_id)
        _audit(audit, agent, iteration, "check_price_accuracy",
               {"offer_id": intake.offer_id}, pc)
        if pc.get("has_free_claim") and not pc.get("verified"):
            for cond in pc.get("missing_conditions", []):
                out.append(Violation(
                    rule_id="FTC-005", severity=Severity.HARD,
                    description=f"Free/$0 claim missing: {cond}",
                    suggestion="Add the missing disclosure adjacent to the $0 claim.",
                ))
        ti = offer_verification.check_trade_in_eligibility(content, intake.offer_id)
        _audit(audit, agent, iteration, "check_trade_in_eligibility",
               {"offer_id": intake.offer_id}, ti)
        for issue in ti.get("issues", []):
            out.append(Violation(
                rule_id="FTC-013", severity=Severity.HARD,
                description=issue,
                suggestion="List eligible brands and required device condition.",
            ))
    # Superlatives without citation
    for s in content_analysis.detect_superlatives(content):
        if s["needs_citation"]:
            out.append(Violation(
                rule_id="FTC-017", severity=Severity.HARD,
                description=f"Superlative '{s['term']}' without independent citation",
                span=s["span"],
                suggestion="Cite Ookla / J.D. Power / OpenSignal study within 18 months.",
            ))
    # Unlimited / no throttling
    import re
    if re.search(r"truly unlimited|no throttling|no data caps|no caps, no throttling",
                 content, re.I):
        out.append(Violation(
            rule_id="FTC-008", severity=Severity.HARD,
            description="Per se deceptive 'truly unlimited / no throttling' claim",
            suggestion="Replace with 'unlimited data; speeds may temporarily slow during congestion'",
        ))
    # SMS TCPA elements
    if (intake.channel or "").upper() == "SMS":
        v = channel_validation.validate_mandatory_elements(content, "SMS", intake.offer_id)
        _audit(audit, agent, iteration, "validate_mandatory_elements",
               {"channel": "SMS"}, v)
        for missing in v.get("missing", []):
            out.append(Violation(
                rule_id="FTC-014", severity=Severity.HARD,
                description=f"SMS missing TCPA element: {missing}",
                suggestion=f"Append '{missing}'.",
            ))
    return out


def run_fcc_enforcer(content: str, intake: IntakeMetadata,
                     audit: list[ToolCallTrace], iteration: int,
                     prior_state: dict | None = None) -> CriticVerdict:
    return run_critic(
        name="fcc_enforcer", system_prompt=FCC_PROMPT, tools=FCC_TOOLS,
        fallback=_fcc_fallback,
        content=content, intake=intake, iteration=iteration, audit=audit,
        prior_state=prior_state,
    )


# ============ Brand Guardian ============

BRAND_PROMPT = """You are the Brand Guardian for Guardian AI.

Persona: NovaTel's Chief Brand Officer who has read the 50-page brand
guidelines cover-to-cover and is the institutional memory of \"how NovaTel
sounds.\" Stylistic, editorial, brand-conscious. Reference specific brand
section numbers in your reasoning.

Mindset: \"Does this sound like NovaTel? Or does it sound like a startup
trying to sound edgy, a legacy enterprise hiding behind jargon, or a
competitor we don't want to be confused with?\"

Mission: enforce brand voice, terminology, prohibited language, and CTA
standards. You prevent brand erosion across thousands of marketing pieces.

Tools to use:
  - search_brand_rules / get_rule / list_prohibited_terms
  - detect_superlatives / detect_urgency_language / detect_all_caps
  - detect_prohibited_phrases / detect_passive_voice / score_readability
  - validate_cta / validate_utm

LANE — you OWN:
  - §1 Voice & Tone:        BRAND-101..106
  - §2 Approved Terminology: BRAND-201..208 (use BRAND-202 for unsourced
                              superlatives like 'fastest')
  - §3 Prohibited Words:    BRAND-301..315
  - §6 CTA Standards:       BRAND-601..604 (shared with Ops Strategist)

DO NOT cite:
  - Any FTC-*           → FCC Enforcer's lane
  - BRAND-401..406      → Ops Strategist (channel length / mandatory elements)
  - BRAND-501..504      → Persona Simulator (audience tone)
  - BRAND-701..704      → Technical Lead (claim standards / superlative
                          methodology in claims)
  - BRAND-801..805      → Technical Lead (disclosure requirements)
Out-of-lane cites are dropped.

Cite rule_ids only after fetching them.
"""

BRAND_TOOLS = COMPLIANCE_LOOKUP_TOOLS + CONTENT_ANALYSIS_TOOLS + [
    t for t in CHANNEL_VALIDATION_TOOLS if t.name in {"validate_cta", "validate_utm"}
]


def _brand_fallback(content: str, intake: IntakeMetadata,
                    audit: list[ToolCallTrace], iteration: int) -> list[Violation]:
    out: list[Violation] = []
    agent = "brand_guardian"
    # Prohibited terms
    prohibited = content_analysis.detect_prohibited_phrases(content, intake.channel)
    _audit(audit, agent, iteration, "detect_prohibited_phrases",
           {"channel": intake.channel}, prohibited)
    for p in prohibited:
        # skip presence-only flags for free/unlimited (handled elsewhere)
        if p["rule_id"] in {"BRAND-302", "BRAND-301"}:
            continue
        out.append(Violation(
            rule_id=p["rule_id"],
            severity=Severity(p.get("severity", "SOFT")),
            description=f"Prohibited {p['kind']}: '{p['term']}' — {p.get('condition', '')}",
            span=p.get("match"),
            suggestion="Replace with an approved alternative.",
        ))
    # Urgency
    for u in content_analysis.detect_urgency_language(content):
        out.append(Violation(
            rule_id="BRAND-102", severity=Severity.HARD,
            description=f"Urgency phrase: '{u['term']}'",
            suggestion="Remove urgency language; state the actual offer end date instead.",
        ))
    # All caps
    for ac in content_analysis.detect_all_caps(content):
        out.append(Violation(
            rule_id="BRAND-103", severity=Severity.HARD,
            description=f"All-caps {ac['kind']}: {ac['line'][:60]}",
            suggestion="Use Title Case or sentence case.",
        ))
    # Superlatives (BRAND-202: 'fastest'/etc. without third-party citation)
    for s in content_analysis.detect_superlatives(content):
        if s["needs_citation"]:
            out.append(Violation(
                rule_id="BRAND-202", severity=Severity.HARD,
                description=f"Superlative '{s['term']}' without third-party source",
                span=s["span"],
                suggestion="Cite Ookla / J.D. Power / OpenSignal / RootMetrics study (≤18 months old).",
            ))
    # CTA / UTM
    cta = channel_validation.validate_cta(content, intake.channel or "all", intake.audience)
    _audit(audit, agent, iteration, "validate_cta",
           {"channel": intake.channel, "audience": intake.audience}, cta)
    for issue in cta.get("issues", []):
        out.append(Violation(
            rule_id="BRAND-603", severity=Severity.HARD,
            description=f"Prohibited CTA: '{issue['prohibited_cta']}'",
            suggestion="Use an approved CTA from the registry.",
        ))
    utm = channel_validation.validate_utm(content)
    _audit(audit, agent, iteration, "validate_utm", {}, utm)
    for issue in utm.get("issues", []):
        out.append(Violation(
            rule_id="BRAND-604", severity=Severity.HARD,
            description=f"URL missing UTM params {issue['missing']}: {issue['url']}",
            suggestion="Add utm_source/medium/campaign.",
        ))
    # ---- BRAND-302 verification (free/$0 disclosure) -----------------
    # When the offer-verification skill confirms that all required disclosures
    # are present (or are validly waived via the SMS short-link safe harbor),
    # we record an audit row with verified=True so the runner's verified-rule
    # filter will drop any LLM cite of BRAND-302 / FTC-005. Without this row
    # in brand_guardian's audit, its LLM keeps re-flagging "$0/mo without
    # immediately adjacent material conditions" round after round even though
    # the SMS structurally satisfies the rule.
    if intake.offer_id:
        pc = offer_verification.check_price_accuracy(content, intake.offer_id)
        _audit(audit, agent, iteration, "check_price_accuracy",
               {"offer_id": intake.offer_id}, pc)
    # ---- BRAND-301 verification (Unlimited plan-name allowlist) ------
    # "Unlimited Premium" / "Unlimited Starter" / etc. are REGISTERED PLAN
    # NAMES in offers_registry.csv. The bare word "unlimited" appearing as
    # part of a plan-name reference is not a §3.301 violation — the rule
    # targets unqualified marketing claims like "truly unlimited" or
    # "unlimited everything". This audit row asserts BRAND-301 verified
    # whenever every "unlimited" occurrence is followed by a plan-tier
    # qualifier (Starter/Extra/Premium/Ultimate), so the runner drops LLM
    # cites that mistake plan-name usage for a rule violation.
    import re as _re
    tl = content.lower()
    bare_unlimited = [
        m for m in _re.finditer(r"\bunlimited\b", tl)
    ]
    if bare_unlimited:
        all_qualified = True
        for m in bare_unlimited:
            tail = tl[m.end(): m.end() + 40].lstrip()
            if not _re.match(
                r"(starter|extra|premium|ultimate|business|home)\b",
                tail,
            ):
                all_qualified = False
                break
        # Also accept the presence of an explicit deprioritization disclosure
        # ("speeds may temporarily slow", "after Xgb", etc.) within ~120 chars.
        has_deprio = bool(_re.search(
            r"speeds?\s+may\s+(?:temporarily\s+)?slow|after\s+\d+\s*gb|deprioritiz",
            tl,
        ))
        verified = all_qualified or has_deprio
        _audit(audit, agent, iteration, "check_unlimited_qualifier",
               {"channel": intake.channel},
               {
                   "verified": verified,
                   "all_plan_name_usage": all_qualified,
                   "has_deprioritization_disclosure": has_deprio,
                   "rule_ids_implicated": ["BRAND-301"],
               })
    return out


def run_brand_guardian(content: str, intake: IntakeMetadata,
                       audit: list[ToolCallTrace], iteration: int,
                       prior_state: dict | None = None) -> CriticVerdict:
    return run_critic(
        name="brand_guardian", system_prompt=BRAND_PROMPT, tools=BRAND_TOOLS,
        fallback=_brand_fallback,
        content=content, intake=intake, iteration=iteration, audit=audit,
        prior_state=prior_state,
    )


# ============ Persona Simulator ============

PERSONA_PROMPT = """You are the Persona Simulator for Guardian AI.

Persona: dynamically adopt the target audience. Speak first-person as that
persona (\"As a Small Business Owner, I...\"). Be conversational and
empathetic; surface emotional/cognitive friction, not just rule violations.

Mindset: \"I'm reading this as the actual person it's targeted at. What
confuses me? What annoys me? What would make me NOT buy?\"

Mission: surface comprehension gaps, ambiguity, and audience-tone mismatches
that rule-based agents miss. You are the anti-hallucination empathy layer —
the ONLY agent that thinks like a customer.

Use:
  - search_brand_rules (for §5 audience tone)
  - check_audience_fit / get_channel_spec
  - lookup_offer (to know what the customer would actually pay)

LANE — you OWN: BRAND-501..504 (audience tone / channel-audience fit) ONLY.
  - BRAND-501: Executive (VP+) tone
  - BRAND-502: Consumer (General) tone
  - BRAND-503: Small Business Owner tone
  - BRAND-504: Technical (IT/Ops) tone

DO NOT cite FTC-*, BRAND-1xx/2xx/3xx, BRAND-4xx, BRAND-6xx, BRAND-7xx, or
BRAND-8xx — those belong to other critics and will be dropped.

You may ALSO surface persona-level concerns without a rule_id (hidden cost
confusion, unstated assumptions, comparison ambiguity, promised-vs-delivered
gaps). For those, omit rule_id from the violation — OR attach the closest
BRAND-5xx rule if relevant.
"""

PERSONA_TOOLS = COMPLIANCE_LOOKUP_TOOLS + OFFER_VERIFICATION_TOOLS + [
    t for t in CHANNEL_VALIDATION_TOOLS
    if t.name in {"check_audience_fit", "get_channel_spec"}
]


def _persona_fallback(content: str, intake: IntakeMetadata,
                      audit: list[ToolCallTrace], iteration: int) -> list[Violation]:
    out: list[Violation] = []
    agent = "persona_simulator"
    if intake.channel and intake.audience:
        fit = channel_validation.check_audience_fit(intake.channel, intake.audience)
        _audit(audit, agent, iteration, "check_audience_fit",
               {"channel": intake.channel, "audience": intake.audience}, fit)
        if fit.get("fit") == "mismatch":
            out.append(Violation(
                rule_id="BRAND-501", severity=Severity.HARD,
                description=f"Channel-audience mismatch: {fit.get('reason')}",
                suggestion="Use a channel appropriate for this audience.",
            ))
    # Audience-specific jargon checks (SOFT)
    aud = (intake.audience or "").lower()
    jargon_map = {
        "consumer": ["deprioritization", "installment agreement", "amortized", "arpu"],
        "executive": ["cool features", "check it out", "you guys", "awesome"],
        "small business": ["digital transformation", "scalable infrastructure",
                           "end-to-end solution"],
        "technical": ["blazing fast", "magical", "just works", "no-brainer"],
    }
    for audkey, words in jargon_map.items():
        if audkey in aud:
            tl = content.lower()
            for w in words:
                if w in tl:
                    out.append(Violation(
                        rule_id="BRAND-502", severity=Severity.SOFT,
                        description=f"Audience-mismatch term for {intake.audience}: '{w}'",
                        span=w,
                        suggestion="Use audience-appropriate language.",
                    ))
    return out


def run_persona_simulator(content: str, intake: IntakeMetadata,
                          audit: list[ToolCallTrace], iteration: int,
                          prior_state: dict | None = None) -> CriticVerdict:
    return run_critic(
        name="persona_simulator", system_prompt=PERSONA_PROMPT, tools=PERSONA_TOOLS,
        fallback=_persona_fallback,
        content=content, intake=intake, iteration=iteration, audit=audit,
        prior_state=prior_state,
    )


# ============ Technical Lead ============

TECH_PROMPT = """You are the Technical Lead for Guardian AI.

Persona: a senior product manager who built the offers in the registry.
Knows every plan tier, device spec, and credit calculation by heart.
Forensic, data-driven — prefer side-by-side comparisons of marketing claim
vs. registry truth in your descriptions.

Mindset: \"Does the marketing actually describe what we sell? Or are they
promising something the product can't deliver?\"

Mission: validate every factual claim against the offer registry. Catch
math errors, over-promises, spec mismatches, price misrepresentations,
speed exaggerations, eligibility mismatches, plan-tier mismatches, credit
calculation errors, coverage overstatements, and tax omissions.

Primary tools: lookup_offer, verify_claim, find_offer_by_content,
extract_claims, check_price_accuracy, check_trade_in_eligibility.

LANE — you OWN:
  - §7 Claim Standards:        BRAND-701..704
      • BRAND-701: quantitative claims missing methodology / contradicting registry
      • BRAND-702: superlatives in CLAIMS without third-party source <18 months
      • BRAND-703: testimonials missing 'results may vary'
      • BRAND-704: comparative claims naming competitors directly
  - §8 Disclosure Requirements: BRAND-801..805
      • BRAND-801: $0/free device disclosure incomplete
      • BRAND-802: network speed claim missing methodology
      • BRAND-803: savings/comparison claim missing baseline
      • BRAND-804: BOGO disclosure incomplete
      • BRAND-805: unlimited-plan disclosure incomplete

DO NOT cite FTC-* (FCC Enforcer), BRAND-1xx/2xx/3xx (Brand Guardian),
BRAND-4xx (Ops), BRAND-5xx (Persona), or BRAND-6xx (CTAs).
For pure registry mismatches with no clean rule fit, prefer BRAND-701.
"""

TECH_TOOLS = OFFER_VERIFICATION_TOOLS + [
    t for t in CONTENT_ANALYSIS_TOOLS if t.name == "extract_claims"
]


def _tech_fallback(content: str, intake: IntakeMetadata,
                   audit: list[ToolCallTrace], iteration: int) -> list[Violation]:
    out: list[Violation] = []
    agent = "technical_lead"
    if not intake.offer_id:
        return out
    claims = content_analysis.extract_claims(content)
    _audit(audit, agent, iteration, "extract_claims", {}, claims)
    for c in claims:
        v = offer_verification.verify_claim(c["text"], intake.offer_id)
        _audit(audit, agent, iteration, "verify_claim",
               {"claim": c["text"], "offer_id": intake.offer_id}, v)
        for issue in v.get("contradicts", []):
            out.append(Violation(
                rule_id="BRAND-701", severity=Severity.HARD,
                description=f"Claim contradicts offer registry: {issue}",
                span=c["text"],
                suggestion="Bring the claim in line with the offer registry.",
            ))
        for missing in v.get("missing_conditions", []):
            # Skip price-disclosure misses (FCC Enforcer covers these via FTC-005)
            if "plan" in missing.lower() or "trade" in missing.lower() \
                    or "credit" in missing.lower() or "autopay" in missing.lower():
                continue
            out.append(Violation(
                rule_id="BRAND-801", severity=Severity.HARD,
                description=f"Claim missing required disclosure: {missing}",
                span=c["text"],
                suggestion="Add the missing disclosure or remove the claim.",
            ))
    return out


def run_technical_lead(content: str, intake: IntakeMetadata,
                       audit: list[ToolCallTrace], iteration: int,
                       prior_state: dict | None = None) -> CriticVerdict:
    return run_critic(
        name="technical_lead", system_prompt=TECH_PROMPT, tools=TECH_TOOLS,
        fallback=_tech_fallback,
        content=content, intake=intake, iteration=iteration, audit=audit,
        prior_state=prior_state,
    )


# ============ Ops Strategist ============

OPS_PROMPT = """You are the Ops Strategist for Guardian AI.

Persona: a marketing operations manager who has shipped 10,000 campaigns
and knows every channel's idiosyncrasies — character limits, paragraph
styles, mandatory elements, CTA conventions, UTM tracking. Pragmatic,
checklist-oriented, operationally focused.

Mindset: \"Even if the message is compliant and on-brand, will it actually
WORK in this channel? Will it render correctly on mobile? Are the right
disclosures there? Is every URL trackable?\"

Mission: audit structural and operational aspects — channel format
compliance, mandatory channel-specific elements, CTA structure, URL
tracking, and resource gaps.

Primary tools: identify_channel, get_channel_spec, count_characters,
count_words, validate_mandatory_elements, validate_cta, validate_utm,
validate_length.

LANE — you OWN:
  - §4 Channel Format:  BRAND-401..406 (one per channel: SMS, LinkedIn,
                         Email, Facebook/Instagram, Landing Page,
                         Press Release)
  - §6 CTA Standards:   BRAND-601..604 (shared with Brand Guardian — you
                         focus on operational/tracking aspects: prohibited
                         CTAs, missing UTM params)

DO NOT cite FTC-* (FCC Enforcer), BRAND-1xx/2xx/3xx (Brand Guardian voice/
terminology/prohibited words), BRAND-5xx (Persona), BRAND-7xx/8xx
(Technical Lead claim standards / disclosure requirements).
Out-of-lane cites are dropped.
"""

OPS_TOOLS = CHANNEL_VALIDATION_TOOLS + [
    t for t in COMPLIANCE_LOOKUP_TOOLS if t.name in {"search_brand_rules", "get_rule"}
]


def _ops_fallback(content: str, intake: IntakeMetadata,
                  audit: list[ToolCallTrace], iteration: int) -> list[Violation]:
    out: list[Violation] = []
    agent = "ops_strategist"
    ch = intake.channel or "unknown"
    # Length
    length = channel_validation.validate_length(content, ch, intake.audience)
    _audit(audit, agent, iteration, "validate_length",
           {"channel": ch, "audience": intake.audience}, length)
    for issue in length.get("issues", []):
        out.append(Violation(
            rule_id={"SMS": "BRAND-401", "Email": "BRAND-403",
                     "LinkedIn": "BRAND-402", "Facebook": "BRAND-404",
                     "Instagram": "BRAND-404",
                     "landing_page": "BRAND-405",
                     "press_release": "BRAND-406"}.get(ch, "BRAND-401"),
            severity=Severity.HARD,
            description=issue,
            suggestion="Truncate or restructure to fit the channel limit.",
        ))
    # Mandatory elements
    me = channel_validation.validate_mandatory_elements(content, ch, intake.offer_id)
    _audit(audit, agent, iteration, "validate_mandatory_elements",
           {"channel": ch}, me)
    for missing in me.get("missing", []):
        out.append(Violation(
            rule_id="BRAND-401" if ch == "SMS" else "BRAND-403",
            severity=Severity.HARD,
            description=f"Missing mandatory element for {ch}: {missing}",
            suggestion=f"Add: {missing}",
        ))
    # UTM tracking — call here too so the verified-rule filter sees a
    # BRAND-604 affirmation when the content's URLs are already compliant
    # (incl. the SMS short-link `novatel.com/t` exemption). Without this
    # audit record, the LLM Ops Strategist could keep re-citing BRAND-604
    # forever even after the resolver has applied the correct format.
    utm = channel_validation.validate_utm(content)
    _audit(audit, agent, iteration, "validate_utm", {}, utm)
    for issue in utm.get("issues", []):
        out.append(Violation(
            rule_id="BRAND-604", severity=Severity.HARD,
            description=f"URL missing UTM params {issue['missing']}: {issue['url']}",
            suggestion="Add utm_source/medium/campaign.",
        ))
    # CTA registry check — same rationale: anchor BRAND-603 verified=True
    # so LLM CTA-style cites get filtered when the content is in fact OK.
    cta = channel_validation.validate_cta(content, ch, intake.audience)
    _audit(audit, agent, iteration, "validate_cta",
           {"channel": ch, "audience": intake.audience}, cta)
    for issue in cta.get("issues", []):
        out.append(Violation(
            rule_id="BRAND-603", severity=Severity.HARD,
            description=f"Prohibited CTA: '{issue['prohibited_cta']}'",
            suggestion="Use an approved CTA from the registry.",
        ))
    return out


def run_ops_strategist(content: str, intake: IntakeMetadata,
                       audit: list[ToolCallTrace], iteration: int,
                       prior_state: dict | None = None) -> CriticVerdict:
    return run_critic(
        name="ops_strategist", system_prompt=OPS_PROMPT, tools=OPS_TOOLS,
        fallback=_ops_fallback,
        content=content, intake=intake, iteration=iteration, audit=audit,
        prior_state=prior_state,
    )


CRITICS = {
    "fcc_enforcer": run_fcc_enforcer,
    "brand_guardian": run_brand_guardian,
    "persona_simulator": run_persona_simulator,
    "technical_lead": run_technical_lead,
    "ops_strategist": run_ops_strategist,
}
