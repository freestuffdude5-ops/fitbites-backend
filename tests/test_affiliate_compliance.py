"""Tests for FTC affiliate compliance service."""
import pytest
from src.services.affiliate_compliance import (
    DisclosureLevel,
    generate_compliance_metadata,
    inject_compliance_into_response,
    generate_disclosure_page_html,
    DISCLOSURES,
    PROVIDER_DISCLOSURES,
)


class TestGenerateComplianceMetadata:
    def test_with_providers(self):
        meta = generate_compliance_metadata(["amazon", "instacart"])
        assert meta.has_affiliate_links is True
        assert meta.disclosure_text == DISCLOSURES[DisclosureLevel.STANDARD]
        assert len(meta.provider_disclosures) == 2

    def test_no_providers(self):
        meta = generate_compliance_metadata([])
        assert meta.has_affiliate_links is False
        assert meta.disclosure_text == ""
        assert meta.provider_disclosures == []

    def test_full_disclosure_level(self):
        meta = generate_compliance_metadata(["amazon"], DisclosureLevel.FULL)
        assert "qualifying purchases" in meta.disclosure_text
        assert "Affiliate Disclosure Policy" in meta.disclosure_text

    def test_compact_disclosure_level(self):
        meta = generate_compliance_metadata(["amazon"], DisclosureLevel.COMPACT)
        assert meta.disclosure_text == "Affiliate link"

    def test_deduplicates_providers(self):
        meta = generate_compliance_metadata(["amazon", "amazon", "iherb"])
        # Should deduplicate
        assert meta.has_affiliate_links is True
        assert len(meta.provider_disclosures) == 2

    def test_unknown_provider_no_specific_disclosure(self):
        meta = generate_compliance_metadata(["unknown_provider"])
        assert meta.has_affiliate_links is True
        assert meta.provider_disclosures == []

    def test_custom_disclosure_url(self):
        meta = generate_compliance_metadata(["amazon"], disclosure_url="/custom/disclosure")
        assert meta.disclosure_url == "/custom/disclosure"

    def test_amazon_specific_text(self):
        meta = generate_compliance_metadata(["amazon"])
        assert any("Amazon Associate" in d for d in meta.provider_disclosures)

    def test_all_four_providers(self):
        meta = generate_compliance_metadata(["amazon", "iherb", "instacart", "thrive"])
        assert len(meta.provider_disclosures) == 4


class TestInjectCompliance:
    def test_injects_into_empty_response(self):
        resp = {"recipe_id": "abc"}
        result = inject_compliance_into_response(resp, ["amazon"])
        assert "compliance" in result
        assert result["compliance"]["has_affiliate_links"] is True
        assert result["recipe_id"] == "abc"  # Original data preserved

    def test_injects_with_no_links(self):
        resp = {"data": []}
        result = inject_compliance_into_response(resp, [])
        assert result["compliance"]["has_affiliate_links"] is False

    def test_preserves_existing_data(self):
        resp = {"ingredients": [{"name": "chicken"}], "score": 95}
        result = inject_compliance_into_response(resp, ["instacart"])
        assert result["ingredients"] == [{"name": "chicken"}]
        assert result["score"] == 95
        assert "compliance" in result


class TestDisclosurePageHtml:
    def test_generates_valid_html(self):
        html = generate_disclosure_page_html()
        assert "<!DOCTYPE html>" in html
        assert "Affiliate Disclosure" in html
        assert "FitBites" in html

    def test_includes_all_providers(self):
        html = generate_disclosure_page_html()
        for provider in ["Amazon", "Iherb", "Instacart", "Thrive"]:
            assert provider in html

    def test_includes_contact_info(self):
        html = generate_disclosure_page_html()
        assert "support@fitbites.app" in html

    def test_includes_editorial_independence(self):
        html = generate_disclosure_page_html()
        assert "Editorial Independence" in html
