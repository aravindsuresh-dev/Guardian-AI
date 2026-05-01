"""Intake Parser — identifies channel, audience hint, offer_id, and extracts claims."""
from __future__ import annotations

from app.models.schemas import IntakeMetadata
from app.skills import channel_validation, content_analysis, offer_verification


_CHANNEL_NORMALIZE = {
    "sms": "SMS",
    "email": "Email",
    "linkedin": "LinkedIn",
    "facebook": "Facebook",
    "instagram": "Instagram",
    "instagram_story": "Instagram",
    "landing page": "landing_page",
    "landing_page": "landing_page",
    "press release": "press_release",
    "press_release": "press_release",
}


def _normalize_channel(c: str | None) -> str:
    if not c:
        return "unknown"
    return _CHANNEL_NORMALIZE.get(c.strip().lower(), c)


def run_intake(
    content: str,
    channel_hint: str | None = None,
    audience_hint: str | None = None,
    offer_id_hint: str | None = None,
) -> IntakeMetadata:
    channel = _normalize_channel(channel_hint or channel_validation.identify_channel(content))
    audience = audience_hint
    offer_id = offer_id_hint
    if not offer_id:
        candidates = offer_verification.find_offer_by_content(content)
        if candidates:
            offer_id = candidates[0]["offer_id"]
    claims = [c["text"] for c in content_analysis.extract_claims(content)]
    return IntakeMetadata(
        channel=channel,  # type: ignore[arg-type]
        audience=audience,
        offer_id=offer_id,
        extracted_claims=claims,
    )
