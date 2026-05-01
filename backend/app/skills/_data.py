"""Cached loaders for Guardian AI data assets."""
from __future__ import annotations

import csv
import json
from functools import lru_cache
from typing import Any

from app.config import DATA_DIR


@lru_cache
def regulatory_rules() -> dict[str, Any]:
    with open(DATA_DIR / "regulatory_rules.json", encoding="utf-8") as f:
        return json.load(f)


@lru_cache
def brand_guidelines() -> dict[str, Any]:
    with open(DATA_DIR / "carrier_brand_guidelines.json", encoding="utf-8") as f:
        return json.load(f)


@lru_cache
def channel_matrix() -> dict[str, Any]:
    with open(DATA_DIR / "channel_audience_matrix.json", encoding="utf-8") as f:
        return json.load(f)


@lru_cache
def good_samples() -> dict[str, Any]:
    with open(DATA_DIR / "good_content_samples.json", encoding="utf-8") as f:
        return json.load(f)


@lru_cache
def violation_samples() -> dict[str, Any]:
    with open(DATA_DIR / "violation_content_samples.json", encoding="utf-8") as f:
        return json.load(f)


@lru_cache
def source_assets() -> dict[str, Any]:
    with open(DATA_DIR / "source_content_assets.json", encoding="utf-8") as f:
        return json.load(f)


@lru_cache
def offers_registry() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(DATA_DIR / "offers_registry.csv", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


@lru_cache
def offer_index() -> dict[str, dict[str, Any]]:
    return {row["offer_id"]: row for row in offers_registry()}


# ---------- Flattened rule indexes ----------

@lru_cache
def all_regulatory_rules() -> list[dict[str, Any]]:
    return list(regulatory_rules().get("rules", []))


@lru_cache
def regulatory_rule_index() -> dict[str, dict[str, Any]]:
    return {r["rule_id"]: r for r in all_regulatory_rules()}


@lru_cache
def all_brand_rules() -> list[dict[str, Any]]:
    """Flatten every brand rule across sections, attaching its section_id/title."""
    out: list[dict[str, Any]] = []
    for section in brand_guidelines().get("sections", []):
        sid = section.get("section_id")
        stitle = section.get("title")
        for rule in section.get("rules", []):
            r = dict(rule)
            r["section_id"] = sid
            r["section_title"] = stitle
            out.append(r)
    return out


@lru_cache
def brand_rule_index() -> dict[str, dict[str, Any]]:
    return {r["rule_id"]: r for r in all_brand_rules()}
