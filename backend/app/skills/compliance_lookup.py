"""Skill 1: Compliance Lookup (FCC/FTC + brand guidelines)."""
from __future__ import annotations

from typing import Any

from app.skills import _data


def _matches_channel(applies_to: list[str] | None, channel: str | None) -> bool:
    if not channel:
        return True
    if not applies_to:
        return True
    if "all" in applies_to:
        return True
    # Loose match: 'social' covers Facebook/Instagram/LinkedIn
    cl = channel.lower()
    for a in applies_to:
        if a.lower() == cl:
            return True
        if a.lower() == "social" and cl in {"facebook", "instagram", "linkedin", "tiktok"}:
            return True
        if a.lower() == "mobile_web" and cl == "landing_page":
            return True
    return False


def _haystack(rule: dict[str, Any]) -> str:
    return " ".join(
        str(v)
        for k, v in rule.items()
        if k in {"rule_text", "category", "rule_id", "word", "phrase",
                 "claim_type", "section_title", "example_violation"}
    ).lower()


def search_regulations(
    query: str = "",
    category: str | None = None,
    channel: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search FTC/FCC regulatory rules. Returns matching rule dicts."""
    q = query.lower().strip()
    out: list[dict[str, Any]] = []
    for r in _data.all_regulatory_rules():
        if category and r.get("category") != category:
            continue
        if not _matches_channel(r.get("applies_to"), channel):
            continue
        if q and q not in _haystack(r):
            continue
        out.append({
            "rule_id": r["rule_id"],
            "category": r.get("category"),
            "severity": r.get("severity"),
            "rule_text": r.get("rule_text"),
            "source": r.get("source"),
            "applies_to": r.get("applies_to"),
            "example_violation": r.get("example_violation"),
        })
        if len(out) >= limit:
            break
    return out


def get_rule(rule_id: str) -> dict[str, Any] | None:
    """Fetch one rule by id (FTC-* or BRAND-*)."""
    if rule_id in _data.regulatory_rule_index():
        return _data.regulatory_rule_index()[rule_id]
    if rule_id in _data.brand_rule_index():
        return _data.brand_rule_index()[rule_id]
    return None


def search_brand_rules(
    query: str = "",
    section: str | None = None,
    channel: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search NovaTel brand guidelines."""
    q = query.lower().strip()
    out: list[dict[str, Any]] = []
    for r in _data.all_brand_rules():
        if section and r.get("section_id") != section and r.get("section_title") != section:
            continue
        if not _matches_channel(r.get("applies_to"), channel):
            continue
        if q and q not in _haystack(r):
            continue
        out.append({
            "rule_id": r["rule_id"],
            "section_id": r.get("section_id"),
            "section_title": r.get("section_title"),
            "severity": r.get("severity"),
            "rule_text": r.get("rule_text") or r.get("condition"),
            "word": r.get("word"),
            "phrase": r.get("phrase"),
            "applies_to": r.get("applies_to"),
            "examples": r.get("examples"),
        })
        if len(out) >= limit:
            break
    return out


def list_prohibited_terms(channel: str | None = None) -> list[dict[str, Any]]:
    """Return prohibited words & phrases (BRAND-3xx + prohibited CTAs)."""
    out: list[dict[str, Any]] = []
    for r in _data.all_brand_rules():
        if r.get("section_id") not in {"§3", "§6"}:
            continue
        if not _matches_channel(r.get("applies_to"), channel):
            continue
        # Prohibited words/phrases
        if r.get("word") or r.get("phrase"):
            out.append({
                "rule_id": r["rule_id"],
                "term": r.get("word") or r.get("phrase"),
                "kind": "word" if r.get("word") else "phrase",
                "condition": r.get("condition"),
                "severity": r.get("severity"),
            })
        # Prohibited CTAs (BRAND-603)
        for cta in r.get("prohibited_ctas", []) or []:
            out.append({
                "rule_id": r["rule_id"],
                "term": cta,
                "kind": "cta",
                "condition": r.get("rule_text"),
                "severity": r.get("severity"),
            })
    return out


def get_required_citations(claim_type: str) -> dict[str, Any]:
    """For a claim type ('superlative', 'speed', 'savings', 'free_device', 'bogo', 'unlimited'),
    return the citation/disclosure requirements drawn from BRAND-7xx and BRAND-8xx."""
    keymap = {
        "superlative": ["BRAND-702", "FTC-017"],
        "speed": ["BRAND-802", "FTC-009", "FTC-010"],
        "savings": ["BRAND-803", "FTC-011"],
        "free_device": ["BRAND-801", "FTC-005", "FTC-006"],
        "bogo": ["BRAND-804", "FTC-019"],
        "unlimited": ["BRAND-805", "FTC-007", "FTC-008"],
        "trade_in": ["FTC-012", "FTC-013"],
        "quantitative": ["BRAND-701"],
    }
    rule_ids = keymap.get(claim_type.lower(), [])
    rules = []
    for rid in rule_ids:
        r = get_rule(rid)
        if r:
            rules.append({
                "rule_id": rid,
                "severity": r.get("severity"),
                "requirement": r.get("rule_text") or r.get("mandatory_disclosures"),
                "example_disclosure": r.get("example_disclosure") or r.get("example_compliant"),
            })
    return {"claim_type": claim_type, "rules": rules}
