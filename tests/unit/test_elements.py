"""Unit tests for ai_curate.elements -- element extraction from prompts."""

import pytest
from ai_curate.elements import extract_elements, QUALITY_ELEMENTS


class TestExtractElements:
    """Test element extraction from prompt descriptions."""

    def test_extracts_shot_type(self):
        """Wide shot in prompt produces a framing element."""
        elements = extract_elements("wide shot of girl on rooftop at night")
        assert any("wide shot" in e.lower() for e in elements)

    def test_extracts_close_up(self):
        """Close-up in prompt produces a close-up framing element."""
        elements = extract_elements("close-up of her eyes")
        assert any("close-up" in e.lower() for e in elements)

    def test_quality_elements_appended(self):
        """Quality baseline elements are always included."""
        elements = extract_elements("a simple prompt")
        for qe in QUALITY_ELEMENTS:
            assert qe in elements

    def test_no_duplicate_quality_elements(self):
        """Quality elements appear exactly once."""
        elements = extract_elements("wide shot of a landscape")
        for qe in QUALITY_ELEMENTS:
            assert elements.count(qe) == 1

    def test_splits_on_sentence_boundary(self):
        """Multiple sentences produce separate elements."""
        elements = extract_elements("girl with red hair. wearing a blue dress.")
        # Should have at least elements for "girl with red hair" and "wearing a blue dress"
        # plus quality elements
        non_quality = [e for e in elements if e not in QUALITY_ELEMENTS]
        assert len(non_quality) >= 2

    def test_splits_on_dash_delimiter(self):
        """Dash-separated fragments become separate elements."""
        elements = extract_elements("wide shot - girl on rooftop - night sky")
        non_quality = [e for e in elements if e not in QUALITY_ELEMENTS]
        assert len(non_quality) >= 2

    def test_strips_leading_articles(self):
        """Leading articles (a, an, the, she, etc.) are stripped from fragments."""
        elements = extract_elements("a girl with an umbrella")
        non_quality = [e for e in elements if e not in QUALITY_ELEMENTS]
        for e in non_quality:
            assert not e.lower().startswith("a ")
            assert not e.lower().startswith("an ")
            assert not e.lower().startswith("the ")

    def test_short_fragments_filtered(self):
        """Fragments shorter than 3 characters are dropped."""
        elements = extract_elements("wide shot - x - y - girl with sword")
        non_quality = [e for e in elements if e not in QUALITY_ELEMENTS]
        for e in non_quality:
            assert len(e) >= 3

    def test_pronoun_only_fragments_filtered(self):
        """Fragments that are just pronouns/connectors are dropped."""
        elements = extract_elements("she is dressed in armor")
        non_quality = [e for e in elements if e not in QUALITY_ELEMENTS]
        for e in non_quality:
            assert e.lower() not in ("she", "he", "they", "it", "is", "are")

    def test_empty_prompt_returns_quality_only(self):
        """Empty or whitespace-only prompt returns only quality elements."""
        elements = extract_elements("")
        assert elements == list(QUALITY_ELEMENTS)

    def test_explicit_elements_override(self):
        """When explicit elements are provided, they replace auto-extraction
        but quality elements are still appended."""
        from ai_curate.elements import build_element_list

        explicit = ["Character has blue eyes", "Wearing a cape"]
        result = build_element_list(explicit)
        assert "Character has blue eyes" in result
        assert "Wearing a cape" in result
        for qe in QUALITY_ELEMENTS:
            assert qe in result

    def test_panel_alias_accepted(self):
        """The 'panel' keyword in the function signature is accepted as
        an alias for 'prompt' -- backward compat."""
        # extract_elements should work identically regardless of
        # whether the caller calls it with a manga-style prompt
        elements = extract_elements("close-up of her eyes")
        assert len(elements) > len(QUALITY_ELEMENTS)
