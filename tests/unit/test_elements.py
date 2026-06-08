"""Unit tests for ai_curate.elements -- element extraction from prompts."""

from ai_curate.elements import (
    extract_elements,
    QUALITY_ELEMENTS,
    QUALITY_CHECKS,
    get_quality_elements,
    build_element_list,
)


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
        explicit = ["Character has blue eyes", "Wearing a cape"]
        result = build_element_list(explicit)
        assert "Character has blue eyes" in result
        assert "Wearing a cape" in result
        for qe in QUALITY_ELEMENTS:
            assert qe in result


class TestQualityChecks:
    """Test the named quality checks system."""

    def test_quality_checks_dict_has_entries(self):
        """QUALITY_CHECKS contains at least the anatomy and artifacts entries."""
        assert "anatomy" in QUALITY_CHECKS
        assert "artifacts" in QUALITY_CHECKS

    def test_get_quality_elements_empty(self):
        """No keys returns empty list."""
        assert get_quality_elements([]) == []
        assert get_quality_elements(None) == []

    def test_get_quality_elements_single_key(self):
        """Single key returns that element."""
        result = get_quality_elements(["anatomy"])
        assert len(result) == 1
        assert "Clean anatomy" in result[0]

    def test_get_quality_elements_unknown_key_ignored(self):
        """Unknown keys are silently ignored."""
        result = get_quality_elements(["nonexistent", "artifacts"])
        assert len(result) == 1
        assert result[0] == QUALITY_CHECKS["artifacts"]

    def test_build_element_list_with_flags(self):
        """With explicit quality_flags, only selected checks appended."""
        result = build_element_list(["Test element"], quality_flags=["anatomy"])
        assert "Test element" in result
        assert any("Clean anatomy" in e for e in result)
        assert not any("No visual artifacts" in e for e in result)

    def test_build_element_list_with_empty_flags(self):
        """With empty quality_flags, no quality elements appended."""
        result = build_element_list(["Test element"], quality_flags=[])
        assert result == ["Test element"]

    def test_build_element_list_backward_compat(self):
        """Without quality_flags (None), all quality elements appended (CLI compat)."""
        result = build_element_list(["Test element"])
        assert "Test element" in result
        for qe in QUALITY_ELEMENTS:
            assert qe in result
