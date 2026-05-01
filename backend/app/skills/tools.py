"""LangChain `@tool` wrappers around the deterministic skills.

Critic and Resolver agents bind subsets of these to the underlying LLM.
"""
from __future__ import annotations

from langchain_core.tools import tool

from app.skills import (
    compliance_lookup,
    offer_verification,
    content_analysis,
    channel_validation,
    content_generation,
)


# -------- Skill 1: Compliance Lookup --------

@tool
def search_regulations(query: str = "", category: str | None = None,
                       channel: str | None = None, limit: int = 10) -> list[dict]:
    """Search FCC/FTC regulatory rules by keyword, category, or channel."""
    return compliance_lookup.search_regulations(query, category, channel, limit)


@tool
def get_rule(rule_id: str) -> dict | None:
    """Fetch a single rule by id (FTC-* or BRAND-*)."""
    return compliance_lookup.get_rule(rule_id)


@tool
def search_brand_rules(query: str = "", section: str | None = None,
                       channel: str | None = None, limit: int = 10) -> list[dict]:
    """Search NovaTel brand guidelines."""
    return compliance_lookup.search_brand_rules(query, section, channel, limit)


@tool
def list_prohibited_terms(channel: str | None = None) -> list[dict]:
    """List prohibited words/phrases/CTAs."""
    return compliance_lookup.list_prohibited_terms(channel)


@tool
def get_required_citations(claim_type: str) -> dict:
    """For a claim type return required citations & disclosures."""
    return compliance_lookup.get_required_citations(claim_type)


# -------- Skill 2: Offer Verification --------

@tool
def lookup_offer(offer_id: str) -> dict | None:
    """Return the full offer record (plan, price, trade-in rules, credits)."""
    return offer_verification.lookup_offer(offer_id)


@tool
def find_offer_by_content(text: str) -> list[dict]:
    """Heuristically match marketing text to offer_ids."""
    return offer_verification.find_offer_by_content(text)


@tool
def verify_claim(claim: str, offer_id: str) -> dict:
    """Verify a marketing claim against the registered offer."""
    return offer_verification.verify_claim(claim, offer_id)


@tool
def get_mandatory_disclosure(offer_id: str) -> str | None:
    """Return the canonical mandatory disclosure text for an offer."""
    return offer_verification.get_mandatory_disclosure(offer_id)


@tool
def check_price_accuracy(text: str, offer_id: str) -> dict:
    """Detect $0/free claims missing AutoPay/plan/credit-period disclosure."""
    return offer_verification.check_price_accuracy(text, offer_id)


@tool
def check_trade_in_eligibility(text: str, offer_id: str) -> dict:
    """Detect 'any phone' style claims when only specific brands qualify."""
    return offer_verification.check_trade_in_eligibility(text, offer_id)


# -------- Skill 3: Content Analysis --------

@tool
def detect_superlatives(text: str) -> list[dict]:
    """Find superlative claims that need third-party citation."""
    return content_analysis.detect_superlatives(text)


@tool
def detect_urgency_language(text: str) -> list[dict]:
    """Catch 'HURRY/ACT NOW/LIMITED TIME' urgency violations."""
    return content_analysis.detect_urgency_language(text)


@tool
def detect_all_caps(text: str) -> list[dict]:
    """Flag ALL-CAPS headlines / subject lines."""
    return content_analysis.detect_all_caps(text)


@tool
def detect_prohibited_phrases(text: str, channel: str | None = None) -> list[dict]:
    """Find prohibited words/phrases (BRAND-3xx)."""
    return content_analysis.detect_prohibited_phrases(text, channel)


@tool
def detect_passive_voice(text: str) -> list[dict]:
    """Detect passive-voice constructions (BRAND-105 SOFT)."""
    return content_analysis.detect_passive_voice(text)


@tool
def score_readability(text: str) -> dict:
    """Compute Flesch readability metrics."""
    return content_analysis.score_readability(text)


@tool
def extract_claims(text: str) -> list[dict]:
    """Extract factual claims (price/speed/superlative/savings/coverage)."""
    return content_analysis.extract_claims(text)


# -------- Skill 4: Channel Format Validation --------

@tool
def identify_channel(text: str) -> str:
    """Best-effort channel classifier."""
    return channel_validation.identify_channel(text)


@tool
def get_channel_spec(channel: str, audience: str | None = None) -> dict:
    """Return channel-specific format & tone spec."""
    return channel_validation.get_channel_spec(channel, audience)


@tool
def count_characters(text: str) -> int:
    """Character count."""
    return channel_validation.count_characters(text)


@tool
def count_words(text: str) -> int:
    """Word count."""
    return channel_validation.count_words(text)


@tool
def validate_mandatory_elements(text: str, channel: str) -> dict:
    """Verify channel-required elements (Msg&Data, STOP, T&C URL, Unsub)."""
    return channel_validation.validate_mandatory_elements(text, channel)


@tool
def validate_cta(text: str, channel: str, audience: str | None = None) -> dict:
    """Validate CTAs against approved/prohibited lists."""
    return channel_validation.validate_cta(text, channel, audience)


@tool
def validate_utm(text_or_url: str) -> dict:
    """Verify UTM parameters on URLs."""
    return channel_validation.validate_utm(text_or_url)


@tool
def check_audience_fit(channel: str, audience: str) -> dict:
    """Catch channel-audience mismatches (e.g., SMS to executives)."""
    return channel_validation.check_audience_fit(channel, audience)


@tool
def validate_length(text: str, channel: str, audience: str | None = None) -> dict:
    """Check char/word limits per channel × audience."""
    return channel_validation.validate_length(text, channel, audience)


# -------- Skill 5: Content Generation (Resolver only) --------

@tool
def replace_prohibited_terms(text: str) -> dict:
    """Substitute prohibited words/phrases with approved alternatives."""
    rewritten, changes = content_generation.replace_prohibited_terms(text)
    return {"rewritten": rewritten, "changes": changes}


@tool
def add_utm_to_text(text: str, channel: str, campaign: str = "guardian_q2") -> str:
    """Append UTM params to every URL in text."""
    return content_generation.add_utm_to_text(text, channel, campaign)


@tool
def add_mandatory_elements(text: str, channel: str) -> str:
    """Insert missing channel-mandatory elements."""
    return content_generation.add_mandatory_elements(text, channel)


@tool
def truncate_to_channel(text: str, channel: str) -> str:
    """Smart-truncate while preserving mandatory tail."""
    return content_generation.truncate_to_channel(text, channel)


@tool
def apply_disclosure(text: str, offer_id: str, channel: str) -> str:
    """Append canonical offer disclosure adjacent to the claim."""
    return content_generation.apply_disclosure(text, offer_id, channel)


# ----- Tool group bundles -----

COMPLIANCE_LOOKUP_TOOLS = [
    search_regulations, get_rule, search_brand_rules,
    list_prohibited_terms, get_required_citations,
]
OFFER_VERIFICATION_TOOLS = [
    lookup_offer, find_offer_by_content, verify_claim,
    get_mandatory_disclosure, check_price_accuracy, check_trade_in_eligibility,
]
CONTENT_ANALYSIS_TOOLS = [
    detect_superlatives, detect_urgency_language, detect_all_caps,
    detect_prohibited_phrases, detect_passive_voice, score_readability, extract_claims,
]
CHANNEL_VALIDATION_TOOLS = [
    identify_channel, get_channel_spec, count_characters, count_words,
    validate_mandatory_elements, validate_cta, validate_utm,
    check_audience_fit, validate_length,
]
CONTENT_GENERATION_TOOLS = [
    replace_prohibited_terms, add_utm_to_text, add_mandatory_elements,
    truncate_to_channel, apply_disclosure,
]
