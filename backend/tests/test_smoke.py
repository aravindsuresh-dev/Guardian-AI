"""Smoke tests — run with no LLM key required."""
from __future__ import annotations

from app.agents.intake import run_intake
from app.agents.critics import CRITICS
from app.skills import _data


def test_offers_load():
    assert len(_data.offers_registry()) >= 15
    assert _data.offer_index()["OFF-001"]["plan_required"] == "Unlimited Premium"


def test_rules_load():
    assert any(r["rule_id"] == "FTC-005" for r in _data.all_regulatory_rules())
    assert any(r["rule_id"] == "BRAND-302" for r in _data.all_brand_rules())


def test_bad_001_sms():
    sample = next(s for s in _data.violation_samples()["samples"] if s["sample_id"] == "BAD-001")
    intake = run_intake(
        sample["content"],
        channel_hint=sample["channel"],
        audience_hint=sample["target_audience"],
        offer_id_hint=sample["associated_offer_id"],
    )
    audit = []
    found = set()
    for name, fn in CRITICS.items():
        v = fn(content=sample["content"], intake=intake, audit=audit, iteration=1)
        for viol in v.violations:
            found.add(viol.rule_id)
    expected = {pv["rule_id"] for pv in sample["planted_violations"]}
    # Without LLM, we still want strong recall on this easy sample
    overlap = found & expected
    assert len(overlap) >= 4, f"Expected ≥4 of {expected}, got {found}"
