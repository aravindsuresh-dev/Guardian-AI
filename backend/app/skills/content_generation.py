"""Skill 5: Content Generation (templated, deterministic helpers used by Resolver)."""
from __future__ import annotations

import re
from typing import Any

from app.skills import _data
from app.skills.offer_verification import lookup_offer, get_mandatory_disclosure


_REPLACEMENTS = {
    "guaranteed": "we stand behind",
    "click here": "shop now",
    "learn more": "see plans",
    "leverage": "use",
    "seamlessly": "easily",
    "empower": "help",
    "robust": "strong",
    "disruptive": "innovative",
    "synergy": "combined benefit",
    "game-changing": "important",
    "industry-leading": "high-performing",
    "revolutionary": "new",
    "no strings attached": "with simple terms",
    "best network": "high-quality network",
    "truly unlimited": "unlimited",
    "no throttling": "with speed-management during congestion",
    "no caps": "with usage policies",
    "ai-powered": "ai-assisted",
    "ai-driven": "ai-assisted",
}


def replace_prohibited_terms(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Substitute prohibited words/phrases with approved alternatives.
    Returns: (rewritten, [{from, to, rule_id?}])."""
    out = text
    changes: list[dict[str, Any]] = []
    for bad, good in _REPLACEMENTS.items():
        pattern = re.compile(rf"\b{re.escape(bad)}\b", flags=re.IGNORECASE)
        if pattern.search(out):
            out, n = pattern.subn(good, out)
            if n:
                changes.append({"from": bad, "to": good, "count": n})
    # Collapse repeated exclamation marks
    out2 = re.sub(r"!{2,}", "!", out)
    if out2 != out:
        changes.append({"from": "multiple-bangs", "to": "single-bang"})
        out = out2
    return out, changes


def add_utm(url: str, channel: str, campaign: str = "guardian_q2") -> str:
    """Append utm_source/medium/campaign if missing (BRAND-604)."""
    if re.fullmatch(r"novatel\.com/t/?", url):
        return url  # short-URL exemption
    medium = {
        "sms": "sms", "email": "email",
        "linkedin": "social", "facebook": "social", "instagram": "social",
        "landing_page": "web", "press_release": "pr",
    }.get(channel.lower(), "web")
    source = channel.lower()
    sep = "&" if "?" in url else "?"
    needed = []
    if "utm_source" not in url:
        needed.append(f"utm_source={source}")
    if "utm_medium" not in url:
        needed.append(f"utm_medium={medium}")
    if "utm_campaign" not in url:
        needed.append(f"utm_campaign={campaign}")
    if not needed:
        return url
    return f"{url}{sep}{'&'.join(needed)}"


def add_utm_to_text(text: str, channel: str, campaign: str = "guardian_q2") -> str:
    """Run add_utm over every URL inside `text`.

    SMS exemption: SMS character budget is 160; UTM query strings would
    consume ~60 chars and crowd out the offer copy. Real-world SMS attribution
    is handled server-side via a short-link redirect (e.g., novatel.com/t),
    not query params. So for channel=SMS we collapse any `novatel.com/...`
    URL to the short form and skip UTM appending altogether.
    """
    if channel.lower() == "sms":
        return re.sub(r"novatel\.com/\S+", "novatel.com/t", text)

    def repl(m: re.Match) -> str:
        return add_utm(m.group(0), channel, campaign)
    return re.sub(r"https?://\S+|novatel\.com/\S+", repl, text)


def add_mandatory_elements(text: str, channel: str) -> str:
    """Insert any missing mandatory elements (Msg&Data, STOP, T&C URL, Unsub)."""
    ch = channel.lower()
    out = text.rstrip()
    tl = out.lower()
    if ch == "sms":
        if "novatel.com/" not in tl:
            out = f"{out} novatel.com/t"
        if "msg&data" not in tl and "msg & data" not in tl:
            out = f"{out} Msg&Data rates apply"
        if " stop" not in f" {out.lower()} " and "opt out" not in tl:
            out = f"{out} STOP to opt out"
    elif ch == "email":
        if "novatel.com/terms" not in tl:
            out = f"{out}\n\nFull terms: novatel.com/terms"
        if "unsubscribe" not in tl:
            out = f"{out}\nUnsubscribe: novatel.com/unsub"
    elif ch in {"facebook", "instagram", "linkedin"}:
        if "novatel.com/" not in tl:
            out = f"{out}\n\nTerms: novatel.com/terms"
    return out


def truncate_to_channel(text: str, channel: str) -> str:
    """Smart-truncate while preserving mandatory tail (Msg&Data / STOP)."""
    ch = channel.lower()
    if ch == "sms" and len(text) > 160:
        # Split off the mandatory tail and try to preserve it
        tail_keywords = ["Msg&Data", "STOP", "novatel.com"]
        tail = ""
        body = text
        for kw in tail_keywords:
            idx = body.find(kw)
            if idx > 0:
                tail = body[idx:].strip() + " " + tail
                body = body[:idx].strip()
        budget = 160 - len(tail) - 1
        if budget < 40:
            budget = 100  # give up gracefully
        body = body[:budget].rstrip(" ,.;:") + "…"
        return f"{body} {tail}".strip()[:160]
    return text


def apply_disclosure(text: str, offer_id: str, channel: str) -> str:
    """Append (or inline for SMS) the canonical disclosure for an offer."""
    disclosure = get_mandatory_disclosure(offer_id)
    if not disclosure:
        return text
    ch = channel.lower()
    if disclosure[:30].lower() in text.lower():
        return text  # already present
    if ch == "sms":
        # Compress disclosure to short form
        offer = lookup_offer(offer_id) or {}
        plan = offer.get("plan_required", "")
        cost = offer.get("plan_monthly_cost", "")
        months = offer.get("credit_period_months", "")
        short = f" w/ elig. trade-in on {plan} (${cost}/mo). {months}-mo credits."
        if short.lower() not in text.lower() and plan:
            text = text + short
        return text
    if ch == "email":
        return f"{text}\n\nDisclosure: {disclosure}"
    return f"{text}\n\n*{disclosure}"


def fewshot_good_samples(channel: str, audience: str | None = None, k: int = 2) -> list[dict[str, Any]]:
    """Pick K compliant samples matching channel/audience for LLM few-shot."""
    samples = _data.good_samples().get("samples", [])
    matches = [
        s for s in samples
        if s.get("channel", "").lower() == channel.lower()
        and (audience is None or s.get("target_audience") == audience)
    ]
    if not matches:
        matches = [s for s in samples if s.get("channel", "").lower() == channel.lower()]
    if not matches:
        matches = samples
    return matches[:k]


def generate_changelog(
    original: str,
    revised: str,
    violations_fixed: list[dict[str, Any]],
) -> str:
    """Human-readable changelog summarizing what was fixed."""
    lines = ["## Revision Changelog", "", "### Violations addressed"]
    if not violations_fixed:
        lines.append("- (none)")
    for v in violations_fixed:
        rid = v.get("rule_id", "?")
        sev = v.get("severity", "?")
        desc = v.get("description") or v.get("summary") or ""
        lines.append(f"- **{rid}** ({sev}): {desc}")
    lines.append("")
    lines.append(f"### Length: {len(original)} → {len(revised)} chars")
    return "\n".join(lines)
