"""Skill 3: Content Analysis (text-level deterministic checks)."""
from __future__ import annotations

import re
from typing import Any

from app.skills import _data
from app.skills.compliance_lookup import list_prohibited_terms


_SUPERLATIVES = [
    "fastest", "best", "#1", "number one", "most reliable",
    "best-in-class", "best in class", "industry-leading", "industry leading",
    "unbeatable", "unmatched", "world-class",
]

_URGENCY = [
    "act now", "hurry", "limited time", "don't miss out", "do not miss",
    "last chance", "won't last", "before it's gone", "today only",
    "ending soon", "while supplies last",
]

_PROHIBITED_CTAS = [
    "click here", "learn more", "act now", "don't miss out",
    "buy now before it's too late", "submit", "go",
]


def detect_superlatives(text: str) -> list[dict[str, Any]]:
    """Flag superlatives that need a third-party citation (FTC-017 / BRAND-702)."""
    out: list[dict[str, Any]] = []
    tl = text.lower()
    has_citation = bool(
        re.search(r"ookla|j\.?d\.?\s*power|opensignal|rootmetrics", tl)
    )
    for s in _SUPERLATIVES:
        for m in re.finditer(rf"\b{re.escape(s)}\b", tl):
            out.append({
                "term": s,
                "span": text[max(0, m.start() - 20): m.end() + 20],
                "needs_citation": not has_citation,
                "rule_ids": ["FTC-017", "BRAND-702"],
            })
    return out


def detect_urgency_language(text: str) -> list[dict[str, Any]]:
    """Catches BRAND-102 urgency violations."""
    tl = text.lower()
    out: list[dict[str, Any]] = []
    for u in _URGENCY:
        if u in tl:
            out.append({
                "term": u,
                "rule_ids": ["BRAND-102"],
                "severity": "HARD",
            })
    # Countdown emoji ⏰
    if "⏰" in text or "⌛" in text:
        out.append({"term": "countdown emoji", "rule_ids": ["BRAND-102"], "severity": "HARD"})
    return out


def detect_all_caps(text: str) -> list[dict[str, Any]]:
    """Flag headlines / subject lines / standalone lines in ALL CAPS (BRAND-103)."""
    out: list[dict[str, Any]] = []
    # Subject line
    for m in re.finditer(r"^subject:\s*(.+)$", text, flags=re.IGNORECASE | re.MULTILINE):
        line = m.group(1).strip()
        if line and line == line.upper() and re.search(r"[A-Z]{4,}", line):
            out.append({"line": line, "kind": "subject", "rule_ids": ["BRAND-103"]})
    # All-caps lines longer than 4 chars (excluding URLs / acronym-only lines)
    for line in text.splitlines():
        stripped = line.strip()
        letters = re.sub(r"[^A-Za-z]", "", stripped)
        if len(letters) >= 6 and letters == letters.upper() and stripped == stripped.upper():
            if "http" in stripped.lower():
                continue
            out.append({"line": stripped, "kind": "line", "rule_ids": ["BRAND-103"]})
    return out


def detect_prohibited_phrases(text: str, channel: str | None = None) -> list[dict[str, Any]]:
    """Match against the BRAND-3xx prohibited-words/phrases list."""
    out: list[dict[str, Any]] = []
    tl = text.lower()
    for term in list_prohibited_terms(channel=channel):
        t = term["term"].lower()
        # 'free' / '$0' get extra context handling — only flag if no adjacent disclosure
        if term["rule_id"] == "BRAND-302":
            if re.search(r"\bfree\b|\$\s*0", tl):
                # We let the offer-verification skill grade this; flag presence only
                out.append({**term, "match": "free/$0 claim present (verify disclosure)"})
            continue
        if term["rule_id"] == "BRAND-301" and t == "unlimited":
            if "unlimited" in tl:
                out.append({**term, "match": "'unlimited' present (verify deprioritization disclosure)"})
            continue
        if term["kind"] == "cta":
            if re.search(rf"\b{re.escape(t)}\b", tl):
                out.append({**term, "match": t})
            continue
        if re.search(rf"\b{re.escape(t)}\b", tl):
            out.append({**term, "match": t})
    return out


def detect_passive_voice(text: str) -> list[dict[str, Any]]:
    """Lightweight passive-voice detector (BRAND-105 — SOFT)."""
    out: list[dict[str, Any]] = []
    pattern = re.compile(
        r"\b(?:is|are|was|were|be|been|being)\s+\w+ed\b", re.IGNORECASE
    )
    for m in pattern.finditer(text):
        out.append({"span": m.group(0), "rule_ids": ["BRAND-105"], "severity": "SOFT"})
    return out


def score_readability(text: str) -> dict[str, Any]:
    """Flesch Reading Ease (approx). Lower = harder."""
    sentences = max(1, len(re.findall(r"[.!?]+", text)))
    words = re.findall(r"\b[\w']+\b", text)
    n_words = max(1, len(words))
    syllables = 0
    for w in words:
        wl = w.lower()
        # crude syllable count
        groups = re.findall(r"[aeiouy]+", wl)
        s = max(1, len(groups))
        if wl.endswith("e") and s > 1:
            s -= 1
        syllables += s
    asl = n_words / sentences
    asw = syllables / n_words
    flesch = 206.835 - (1.015 * asl) - (84.6 * asw)
    return {
        "flesch_reading_ease": round(flesch, 1),
        "avg_sentence_length": round(asl, 1),
        "avg_syllables_per_word": round(asw, 2),
        "n_words": n_words,
        "n_sentences": sentences,
    }


def extract_claims(text: str) -> list[dict[str, Any]]:
    """Heuristic claim extraction. (LLM-free; agents may also call the LLM directly.)"""
    claims: list[dict[str, Any]] = []
    # Price / $0 / free
    for m in re.finditer(r"\$\s*\d+(?:\.\d{1,2})?(?:/mo)?|\bfree\b", text, re.I):
        claims.append({"type": "price", "text": m.group(0)})
    # Speeds
    for m in re.finditer(r"\b\d+(?:\.\d+)?\s*(?:gbps|mbps)\b", text, re.I):
        claims.append({"type": "speed", "text": m.group(0)})
    # Superlatives
    for s in detect_superlatives(text):
        claims.append({"type": "superlative", "text": s["term"]})
    # Savings
    for m in re.finditer(r"\bsave\s+(?:up\s+to\s+)?\d+%", text, re.I):
        claims.append({"type": "savings", "text": m.group(0)})
    # Coverage
    for m in re.finditer(r"\b(?:nationwide|everywhere|100%|all)\b\s+coverage", text, re.I):
        claims.append({"type": "coverage", "text": m.group(0)})
    # Unlimited / no throttling
    for m in re.finditer(r"truly unlimited|no throttling|no data caps", text, re.I):
        claims.append({"type": "unlimited", "text": m.group(0)})
    return claims
