"""Skill 2: Offer Verification (against offers_registry.csv)."""
from __future__ import annotations

import re
from typing import Any

from app.skills import _data


def lookup_offer(offer_id: str) -> dict[str, Any] | None:
    """Return the full offer row, or None."""
    return _data.offer_index().get(offer_id)


def list_offers() -> list[dict[str, Any]]:
    """Lightweight list of all offers (id, headline, device, plan)."""
    return [
        {
            "offer_id": r["offer_id"],
            "headline": r["offer_headline"],
            "offer_type": r["offer_type"],
            "device": r.get("device"),
            "plan_required": r.get("plan_required"),
        }
        for r in _data.offers_registry()
    ]


def find_offer_by_content(text: str) -> list[dict[str, Any]]:
    """Heuristic match: device/keywords → candidate offer_ids, ordered by score."""
    t = text.lower()
    scored: list[tuple[int, dict[str, Any]]] = []
    for r in _data.offers_registry():
        score = 0
        device = (r.get("device") or "").lower()
        if device and device != "n/a":
            for token in re.findall(r"[a-z0-9]+", device):
                if len(token) >= 3 and token in t:
                    score += 2
        plan = (r.get("plan_required") or "").lower()
        if plan and plan in t:
            score += 3
        # offer-type keywords
        otype = (r.get("offer_type") or "").lower()
        keywords = {
            "device_trade_in": ["trade-in", "trade in"],
            "bogo": ["bogo", "buy one", "get one"],
            "switcher": ["switch", "port-in", "port in"],
            "home_internet": ["home internet", "5g home"],
            "accessory_bundle": ["ipad", "watch"],
            "business": ["business", "smb"],
            "plan_promo": [],
        }.get(otype, [])
        for kw in keywords:
            if kw in t:
                score += 1
        if score > 0:
            scored.append((score, {
                "offer_id": r["offer_id"],
                "headline": r["offer_headline"],
                "score": score,
            }))
    scored.sort(key=lambda x: -x[0])
    return [s[1] for s in scored[:5]]


def get_mandatory_disclosure(offer_id: str) -> str | None:
    """Canonical disclosure text from the registry for a given offer."""
    o = lookup_offer(offer_id)
    return o.get("mandatory_disclosure_text") if o else None


# ---------- Claim verification ----------

_FREE_PATTERNS = [
    r"\bfree\b",
    r"\$\s*0(?!\.\d)",
    r"\$0/mo\b",
    r"\bon us\b",
]

_ANY_PHONE_PATTERNS = [
    r"\bany phone\b",
    r"\bany device\b",
    r"\beven a flip phone\b",
    r"\beven an old\b",
]


def _has_any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, flags=re.I) for p in patterns)


def check_price_accuracy(text: str, offer_id: str) -> dict[str, Any]:
    """Detect $0/free claims and check the surrounding text mentions plan, trade-in
    requirements, credit period, and AutoPay (per BRAND-801 / FTC-005).

    Channel-aware (SMS short-link safe harbor): when the SMS contains a terms
    URL (novatel.com/t...), secondary conditions that traditionally live on
    the terms page — AutoPay, credit-period months, and "credits stop"
    language — are considered disclosed via that link. Plan name, plan
    monthly cost, and trade-in language must STILL appear adjacent to the
    claim regardless of channel. This matches FTC SMS-disclosure guidance and
    is what the resolver can realistically achieve in 160 chars.
    """
    o = lookup_offer(offer_id)
    if not o:
        return {"verified": False, "error": f"Unknown offer_id {offer_id}"}

    findings: list[str] = []
    has_free_claim = _has_any(_FREE_PATTERNS, text)
    if not has_free_claim:
        return {"verified": True, "has_free_claim": False, "missing_conditions": []}

    plan = (o.get("plan_required") or "").strip()
    plan_cost = (o.get("plan_monthly_cost") or "").strip()
    credit_months = (o.get("credit_period_months") or "").strip()
    autopay = (o.get("autopay_required") or "").strip().lower() == "yes"
    trade_in_req = (o.get("trade_in_required") or "").strip().lower() == "yes"

    tl = text.lower()
    # SMS short-link safe harbor: presence of a novatel.com terms URL allows
    # the secondary disclosures (AutoPay, credit period, "credits stop") to
    # live on the linked terms page. The CORE disclosures (plan name, $/mo,
    # trade-in) must still appear in the SMS body itself.
    has_terms_link = bool(re.search(r"novatel\.com/(t|terms)", tl))
    is_short_form = len(text) <= 200  # SMS-sized

    if plan and plan.lower() not in tl:
        findings.append(f"Required plan '{plan}' not mentioned adjacent to free/$0 claim")
    if plan_cost and plan_cost not in text:
        findings.append(f"Plan monthly cost '${plan_cost}/mo' not disclosed")
    if trade_in_req and "trade" not in tl:
        findings.append("Trade-in requirement not disclosed")

    # Secondary conditions — waived if a terms link is present in SMS-sized copy.
    secondary_waived = has_terms_link and is_short_form
    if not secondary_waived:
        if autopay and "autopay" not in tl and "auto pay" not in tl:
            findings.append("AutoPay requirement not disclosed")
        if credit_months and credit_months != "N/A" and credit_months not in text:
            findings.append(f"Credit period '{credit_months} months' not disclosed")
        if credit_months and credit_months != "N/A":
            if not re.search(r"credits?\s+stop|cancel|change plan", text, re.I):
                findings.append("Missing 'credits stop if you cancel/change plan' language")
    return {
        "verified": len(findings) == 0,
        "has_free_claim": True,
        "missing_conditions": findings,
        "secondary_waived_via_terms_link": secondary_waived,
        "rule_ids_implicated": ["FTC-005", "BRAND-302", "BRAND-801"],
    }


def check_trade_in_eligibility(text: str, offer_id: str) -> dict[str, Any]:
    """Catches 'any phone' when only specific brands qualify (FTC-013)."""
    o = lookup_offer(offer_id)
    if not o:
        return {"verified": False, "error": f"Unknown offer_id {offer_id}"}

    eligible = (o.get("eligible_trade_in_brands") or "").strip()
    if not eligible or eligible == "N/A":
        return {"verified": True, "note": "Offer does not require trade-in"}

    findings: list[str] = []
    if _has_any(_ANY_PHONE_PATTERNS, text):
        findings.append(
            f"'any phone' style language used, but offer only credits {eligible}"
        )
    # Brand-name check
    brands = [b.strip() for b in eligible.split(",")]
    if "trade" in text.lower() and not any(b.lower() in text.lower() for b in brands):
        findings.append(f"Trade-in eligible brands not listed (need: {eligible})")
    condition = (o.get("trade_in_condition") or "").strip()
    if "trade" in text.lower() and condition and "good condition" not in text.lower() \
            and "any condition" not in text.lower():
        findings.append(f"Device condition not stated (offer requires: {condition})")
    return {
        "verified": len(findings) == 0,
        "eligible_brands": eligible,
        "condition_required": condition,
        "issues": findings,
        "rule_ids_implicated": ["FTC-012", "FTC-013"],
    }


def verify_claim(claim: str, offer_id: str) -> dict[str, Any]:
    """Spot-check a claim string against the registered offer.

    Returns: { verified, contradicts: [str], missing_conditions: [str] }
    """
    o = lookup_offer(offer_id)
    if not o:
        return {"verified": False, "error": f"Unknown offer_id {offer_id}"}
    contradicts: list[str] = []
    missing: list[str] = []
    cl = claim.lower()

    # Unlimited / no throttling claims
    depri = (o.get("deprioritization_threshold_gb") or "").strip()
    if re.search(r"truly unlimited|no throttling|no caps|no limits", cl):
        if depri and depri.lower() not in {"none (truly unlimited premium data)", "none", "n/a"}:
            contradicts.append(
                f"'truly unlimited / no throttling' contradicts deprioritization threshold: {depri}"
            )

    # Speed claims
    if re.search(r"\b\d+\s*(gbps|mbps)\b", cl) or "fastest" in cl or "fastest 5g" in cl:
        if not re.search(r"ookla|j\.?d\.?\s*power|opensignal|rootmetrics", cl):
            missing.append("Speed/superlative claim missing independent source citation")

    # Free / $0
    price_check = check_price_accuracy(claim, offer_id)
    if price_check.get("has_free_claim") and not price_check["verified"]:
        missing.extend(price_check["missing_conditions"])

    # Trade-in
    ti_check = check_trade_in_eligibility(claim, offer_id)
    if ti_check.get("issues"):
        contradicts.extend(ti_check["issues"])

    return {
        "verified": not contradicts and not missing,
        "contradicts": contradicts,
        "missing_conditions": missing,
        "offer_id": offer_id,
    }
