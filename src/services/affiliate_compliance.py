"""
FTC compliance service for affiliate disclosures.

Automatically injects proper disclosures into API responses containing affiliate links.
Handles:
- FTC 16 CFR Part 255 compliance (endorsement disclosures)
- Platform-specific disclosure formatting (iOS, Android, Web)
- Disclosure positioning and visibility rules
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DisclosureLevel(str, Enum):
    """How prominently to display the affiliate disclosure."""
    FULL = "full"       # Full legal text (settings, about page)
    STANDARD = "standard"  # Clear "contains affiliate links" notice
    COMPACT = "compact"    # Short inline disclosure per link


# FTC-compliant disclosure texts
DISCLOSURES = {
    DisclosureLevel.FULL: (
        "FitBites earns commissions from qualifying purchases made through "
        "affiliate links on this app. This means we may receive a small "
        "percentage of the sale when you buy products through our links. "
        "This does not affect the price you pay. We only recommend products "
        "we believe are relevant to the recipes shown. "
        "For more information, see our Affiliate Disclosure Policy."
    ),
    DisclosureLevel.STANDARD: (
        "This recipe contains affiliate links. We may earn a small commission "
        "if you purchase through these links, at no extra cost to you."
    ),
    DisclosureLevel.COMPACT: "Affiliate link",
}

# Per-provider specific disclosures (Amazon requires specific language)
PROVIDER_DISCLOSURES = {
    "amazon": (
        "As an Amazon Associate, FitBites earns from qualifying purchases."
    ),
    "iherb": (
        "We may earn a commission through iHerb affiliate links."
    ),
    "instacart": (
        "We may earn a commission through Instacart affiliate links."
    ),
    "thrive": (
        "We may earn a commission through Thrive Market affiliate links."
    ),
}


@dataclass
class ComplianceMetadata:
    """Compliance info to attach to any response containing affiliate links."""
    has_affiliate_links: bool
    disclosure_text: str
    disclosure_level: DisclosureLevel
    provider_disclosures: list[str]
    disclosure_url: str  # Link to full disclosure page


def generate_compliance_metadata(
    providers: list[str],
    level: DisclosureLevel = DisclosureLevel.STANDARD,
    disclosure_url: str = "/legal/affiliate-disclosure",
) -> ComplianceMetadata:
    """Generate FTC-compliant disclosure metadata for a set of providers."""
    if not providers:
        return ComplianceMetadata(
            has_affiliate_links=False,
            disclosure_text="",
            disclosure_level=level,
            provider_disclosures=[],
            disclosure_url=disclosure_url,
        )

    unique_providers = list(set(providers))
    provider_texts = []
    for p in unique_providers:
        text = PROVIDER_DISCLOSURES.get(p)
        if text:
            provider_texts.append(text)

    return ComplianceMetadata(
        has_affiliate_links=True,
        disclosure_text=DISCLOSURES[level],
        disclosure_level=level,
        provider_disclosures=provider_texts,
        disclosure_url=disclosure_url,
    )


def inject_compliance_into_response(
    response: dict,
    providers: list[str],
    level: DisclosureLevel = DisclosureLevel.STANDARD,
) -> dict:
    """Add compliance metadata to an API response dict.

    This should be called on any response that contains affiliate links.
    The mobile app renders this as a small disclosure banner above the links.
    """
    meta = generate_compliance_metadata(providers, level)
    response["compliance"] = {
        "has_affiliate_links": meta.has_affiliate_links,
        "disclosure": meta.disclosure_text,
        "provider_disclosures": meta.provider_disclosures,
        "disclosure_url": meta.disclosure_url,
    }
    return response


def generate_disclosure_page_html() -> str:
    """Generate the full affiliate disclosure page HTML.

    This is served at /legal/affiliate-disclosure for full FTC compliance.
    """
    full_text = DISCLOSURES[DisclosureLevel.FULL]
    provider_sections = ""
    for provider, text in PROVIDER_DISCLOSURES.items():
        provider_sections += f"<p><strong>{provider.title()}:</strong> {text}</p>\n"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Affiliate Disclosure - FitBites</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 700px; margin: 40px auto; padding: 0 20px; color: #333; line-height: 1.6; }}
        h1 {{ color: #1a1a1a; }}
        h2 {{ color: #444; margin-top: 2em; }}
        .updated {{ color: #888; font-size: 0.9em; }}
    </style>
</head>
<body>
    <h1>Affiliate Disclosure</h1>
    <p class="updated">Last updated: February 2026</p>

    <h2>Overview</h2>
    <p>{full_text}</p>

    <h2>Our Affiliate Partners</h2>
    {provider_sections}

    <h2>How Affiliate Links Work</h2>
    <p>When you tap a product link in a recipe, you may be directed to a third-party
    retailer's website or app. If you make a purchase, FitBites receives a small
    commission from the retailer. This commission comes from the retailer's marketing
    budget and does <strong>not</strong> increase the price you pay.</p>

    <h2>Editorial Independence</h2>
    <p>Our recipe recommendations are based on nutritional quality, user engagement,
    and taste — not affiliate commission rates. We never promote a recipe because it
    has higher-paying affiliate links.</p>

    <h2>Questions?</h2>
    <p>Contact us at <a href="mailto:support@fitbites.app">support@fitbites.app</a></p>
</body>
</html>"""
