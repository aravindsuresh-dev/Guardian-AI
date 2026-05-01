"""Skill 4: Channel Format Validation."""
from __future__ import annotations

import re
from typing import Any

from app.skills import _data


_APPROVED_CONSUMER_CTAS = [
    "shop now", "see plans", "switch today", "compare plans",
    "check your trade-in value", "see the deal", "get started",
]

_APPROVED_B2B_CTAS = [
    "book a demo", "talk to an expert", "see how it works",
    "request a quote", "contact sales",
]


def identify_channel(text: str) -> str:
    """Best-effort channel classifier from text shape."""
    if re.search(r"\bsubject\s*:", text, re.I) and "unsubscribe" in text.lower():
        return "Email"
    if "stop to opt out" in text.lower() or "msg&data" in text.lower() or len(text) <= 200 and "\n" not in text:
        # short, single-line, with SMS markers
        if "stop to opt out" in text.lower() or "msg&data" in text.lower():
            return "SMS"
    if "linkedin" in text.lower() or re.search(r"\bbusiness\b.*\b(line|plan)\b", text, re.I):
        if "unsubscribe" not in text.lower():
            return "LinkedIn"
    if re.search(r"\bfor immediate release\b|\bmedia contact\b|\babout novatel\b", text, re.I):
        return "press_release"
    if "see more" in text.lower() or re.search(r"[\U0001F300-\U0001FAFF]", text):
        return "Facebook"
    if "<html" in text.lower() or "<h1" in text.lower():
        return "landing_page"
    if len(text) <= 320 and "\n" not in text:
        return "SMS"
    return "unknown"


def get_channel_spec(channel: str, audience: str | None = None) -> dict[str, Any]:
    """Return channel specs from channel_audience_matrix.json."""
    matrix = _data.channel_matrix().get("channels", {})
    # Normalize channel
    canon = {
        "sms": "SMS", "email": "Email",
        "facebook": "Facebook/Instagram", "instagram": "Facebook/Instagram",
        "linkedin": "LinkedIn", "landing_page": "Landing Page",
        "press_release": "Press Release",
    }.get(channel.lower(), channel)
    spec = matrix.get(canon)
    if not spec:
        # fuzzy fallback
        for k, v in matrix.items():
            if k.lower().startswith(canon.lower()[:3]):
                spec = v
                break
    if not spec:
        return {"channel": channel, "found": False}
    out = {"channel": canon, "found": True, **{k: v for k, v in spec.items() if k != "audiences"}}
    if audience:
        aud = spec.get("audiences", {}).get(audience)
        if aud:
            out["audience_profile"] = aud
    return out


def count_characters(text: str) -> int:
    return len(text)


def count_words(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def validate_mandatory_elements(text: str, channel: str,
                                offer_id: str | None = None) -> dict[str, Any]:
    """Check the channel's required elements (Msg&Data, STOP, T&C, Unsub, etc.).

    Elements tagged ``(if applicable)`` in the channel spec are conditional:
      * "Credit period (if applicable)" → only required when the offer
        actually has a bill-credit period (``credit_period_months`` is set
        and not ``"N/A"`` in the offer registry). Prepaid Visa / plan-promo
        offers with no device credits skip this check entirely.
    Without this conditional handling, the Ops Strategist deterministic
    fallback flags BRAND-403 forever on offers that have no credit period
    at all, and the score never improves across iterations.
    """
    spec = get_channel_spec(channel)
    if not spec.get("found"):
        return {"channel": channel, "checked": False, "missing": []}
    must = spec.get("mandatory_elements") or []
    tl = text.lower()
    # Resolve conditional applicability from the offer registry.
    offer = None
    if offer_id:
        # Local import to avoid a circular import at module load time.
        from app.skills.offer_verification import lookup_offer
        offer = lookup_offer(offer_id)
    has_credit_period = bool(
        offer and (offer.get("credit_period_months") or "").strip()
        and (offer.get("credit_period_months") or "").strip().upper() != "N/A"
    )
    missing: list[str] = []
    for el in must:
        e = el.lower()
        # Conditional element: "(if applicable)". Skip if the offer registry
        # tells us the condition doesn't apply. When we have no offer
        # context, we err on the side of skipping (the LLM can still flag).
        if "(if applicable)" in e:
            if "credit period" in e and not has_credit_period:
                continue
            if not offer_id:
                # No offer context → can't verify applicability deterministically.
                continue
        if "msg&data" in e or "msg & data" in e:
            if "msg&data" not in tl and "msg & data" not in tl:
                missing.append(el)
        elif "terms" in e or "t&c" in e:
            if "terms" not in tl and "/t" not in tl and "t&c" not in tl and "novatel.com/" not in tl:
                missing.append(el)
        elif "opt-out" in e or "stop" in e:
            if " stop " not in f" {tl} " and "opt out" not in tl and "unsubscribe" not in tl:
                missing.append(el)
        elif "unsubscribe" in e or "can-spam" in e:
            if "unsubscribe" not in tl and "unsub" not in tl:
                missing.append(el)
        elif "plan name" in e:
            if not re.search(r"unlimited (starter|extra|premium|ultimate)|5g home", tl):
                missing.append(el)
        elif "credit period" in e:
            if not re.search(r"\d+\s*(?:-?\s*)?(?:mo|month)", tl):
                missing.append(el)
        else:
            # generic substring fall-back
            if e not in tl:
                missing.append(el)
    return {
        "channel": spec["channel"],
        "required": must,
        "missing": missing,
        "verified": len(missing) == 0,
        "rule_ids_implicated": ["FTC-014", "BRAND-401", "BRAND-403", "BRAND-404"],
    }


def validate_cta(text: str, channel: str, audience: str | None = None) -> dict[str, Any]:
    """Check CTAs against approved list (BRAND-601/602/603)."""
    tl = text.lower()
    issues: list[dict[str, Any]] = []
    found_approved: list[str] = []
    # Prohibited CTAs
    for bad in ["click here", "learn more", "act now", "submit", "go", "don't miss out"]:
        if re.search(rf"\b{re.escape(bad)}\b", tl):
            issues.append({"prohibited_cta": bad, "rule_ids": ["BRAND-603", "BRAND-315"]})
    pool = _APPROVED_B2B_CTAS if (audience and "business" in audience.lower()) \
        or channel.lower() in {"linkedin"} else _APPROVED_CONSUMER_CTAS
    for ok in pool + _APPROVED_CONSUMER_CTAS + _APPROVED_B2B_CTAS:
        if re.search(rf"\b{re.escape(ok)}\b", tl):
            found_approved.append(ok)
    return {
        "issues": issues,
        "approved_found": list(set(found_approved)),
        "approved_pool": pool,
        "verified": len(issues) == 0,
        "rule_ids_implicated": ["BRAND-603"],
    }


def validate_utm(text_or_url: str) -> dict[str, Any]:
    """For each URL, ensure utm_source/utm_medium/utm_campaign are present (BRAND-604)."""
    urls = re.findall(r"https?://\S+|novatel\.com/\S+", text_or_url)
    if not urls:
        return {"urls_found": [], "issues": []}
    required = ["utm_source", "utm_medium", "utm_campaign"]
    issues = []
    for u in urls:
        # SMS short URLs (novatel.com/t) are exempt under BRAND-401 (char-limit accommodation)
        if re.fullmatch(r"novatel\.com/t\??.*", u):
            continue
        if u.endswith("/terms") or u.endswith("/unsub"):
            continue
        missing = [p for p in required if p not in u]
        if missing:
            issues.append({"url": u, "missing": missing, "rule_ids": ["BRAND-604"]})
    return {"urls_found": urls, "issues": issues, "verified": len(issues) == 0,
            "rule_ids_implicated": ["BRAND-604"]}


def check_audience_fit(channel: str, audience: str) -> dict[str, Any]:
    """E.g. SMS to Executive (VP+) → channel mismatch."""
    spec = get_channel_spec(channel, audience)
    if not spec.get("found"):
        return {"fit": "unknown"}
    profile = spec.get("audience_profile") or {}
    tone = (profile.get("tone") or "").lower()
    if "not recommended" in tone or "channel mismatch" in tone:
        return {"fit": "mismatch", "reason": profile.get("tone")}
    return {"fit": "ok", "tone_guidance": profile.get("tone")}


def validate_length(text: str, channel: str, audience: str | None = None) -> dict[str, Any]:
    """Char/word limit check vs. channel spec."""
    spec = get_channel_spec(channel, audience)
    issues: list[str] = []
    if not spec.get("found"):
        return {"checked": False}
    profile = spec.get("audience_profile") or {}
    max_chars = spec.get("max_characters")
    max_words = profile.get("max_words") or spec.get("max_words")
    if max_chars and count_characters(text) > int(max_chars):
        issues.append(f"Exceeds max_characters: {count_characters(text)} > {max_chars}")
    if max_words and count_words(text) > int(max_words):
        issues.append(f"Exceeds max_words: {count_words(text)} > {max_words}")
    rule_for_channel = {
        "SMS": "BRAND-401", "LinkedIn": "BRAND-402", "Email": "BRAND-403",
        "Facebook": "BRAND-404", "Instagram": "BRAND-404",
        "Facebook/Instagram": "BRAND-404",
        "landing_page": "BRAND-405", "Landing Page": "BRAND-405",
        "press_release": "BRAND-406", "Press Release": "BRAND-406",
    }.get(spec.get("channel") or channel, "BRAND-401")
    return {
        "checked": True,
        "char_count": count_characters(text),
        "word_count": count_words(text),
        "limits": {"max_characters": max_chars, "max_words": max_words},
        "issues": issues,
        "verified": len(issues) == 0,
        "rule_ids_implicated": [rule_for_channel],
    }
