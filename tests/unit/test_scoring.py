"""Unit tests for ai_curate.scoring -- scoring orchestration."""

import pytest
from unittest.mock import MagicMock, patch

from ai_curate.scoring import find_images, build_scoring_prompt, score_images
from ai_curate.elements import extract_elements


class TestFindImages:
    def test_finds_images_in_directory(self, tmp_path):
        """find_images returns image files from a directory."""
        (tmp_path / "photo1.png").write_bytes(b"fake")
        (tmp_path / "photo2.jpg").write_bytes(b"fake")
        (tmp_path / "notes.txt").write_bytes(b"not an image")
        result = find_images(tmp_path)
        names = [p.name for p in result]
        assert "photo1.png" in names
        assert "photo2.jpg" in names
        assert "notes.txt" not in names

    def test_excludes_animated_video_and_audio_boundaries(self, tmp_path):
        for filename in ("still.webp", "animation.gif", "clip.mp4", "track.mp3"):
            (tmp_path / filename).write_bytes(b"media")

        assert [path.name for path in find_images(tmp_path)] == ["still.webp"]

    def test_returns_empty_for_nonexistent_dir(self, tmp_path):
        """find_images returns empty list for nonexistent directory."""
        result = find_images(tmp_path / "nonexistent")
        assert result == []

    def test_sorted_by_name(self, tmp_path):
        """find_images returns files sorted by name."""
        (tmp_path / "c.png").write_bytes(b"fake")
        (tmp_path / "a.png").write_bytes(b"fake")
        (tmp_path / "b.png").write_bytes(b"fake")
        result = find_images(tmp_path)
        assert [p.name for p in result] == ["a.png", "b.png", "c.png"]


class TestBuildScoringPrompt:
    def test_includes_numbered_elements(self):
        """build_scoring_prompt produces numbered element list."""
        elements = ["Blue sky", "Red dress", "Clean anatomy"]
        prompt = build_scoring_prompt(elements)
        assert "1. Blue sky" in prompt
        assert "2. Red dress" in prompt
        assert "3. Clean anatomy" in prompt
        assert "YES" in prompt
        assert "NO" in prompt

    def test_empty_elements_raises(self):
        """build_scoring_prompt must reject an empty element list.

        Regression: a silent failure where the prompt template expanded
        with an empty numbered block, then ``parse_score_response`` rejected
        every YES/NO line because ``num_elements == 0``.
        """
        with pytest.raises(ValueError, match="empty"):
            build_scoring_prompt([])


class TestScoreImages:
    @patch("ai_curate.scoring.VisionClient")
    def test_score_images_with_mock(self, MockClient, tmp_path):
        """score_images returns results for each image."""
        # Create test images
        (tmp_path / "img1.png").write_bytes(b"fake")
        (tmp_path / "img2.png").write_bytes(b"fake")

        # Mock the client
        mock_client = MagicMock()
        mock_client.score_image.side_effect = [
            (3, 5, {1: "YES", 2: "NO", 3: "YES"}, ""),
            (5, 5, {1: "YES", 2: "YES", 3: "YES"}, ""),
        ]

        elements = extract_elements("wide shot of landscape")
        results, total = score_images(
            image_dir=tmp_path,
            elements=elements,
            client=mock_client,
        )

        assert total == 2
        assert len(results) == 2
        assert results[0].filename == "img1.png"
        assert results[1].filename == "img2.png"

    @patch("ai_curate.scoring.VisionClient")
    def test_cancel_check_stops_scoring(self, MockClient, tmp_path):
        """score_images stops when cancel_check returns True."""
        (tmp_path / "img1.png").write_bytes(b"fake")
        (tmp_path / "img2.png").write_bytes(b"fake")
        (tmp_path / "img3.png").write_bytes(b"fake")

        mock_client = MagicMock()
        mock_client.score_image.return_value = (3, 5, {}, "")

        # Cancel after first image
        cancel_calls = [0]

        def cancel_check():
            cancel_calls[0] += 1
            return cancel_calls[0] > 1

        results, total = score_images(
            image_dir=tmp_path,
            elements=["elem1"],
            client=mock_client,
            cancel_check=cancel_check,
        )

        # Should have scored only 1 image before cancellation
        assert len(results) == 1

    @patch("ai_curate.scoring.VisionClient")
    def test_empty_elements_raises(self, MockClient, tmp_path):
        """score_images must raise on empty elements instead of silently failing every image."""
        (tmp_path / "img1.png").write_bytes(b"fake")
        mock_client = MagicMock()
        with pytest.raises(ValueError, match="empty"):
            score_images(
                image_dir=tmp_path,
                elements=[],
                client=mock_client,
            )
        # No call should have been made to the vision client.
        mock_client.score_image.assert_not_called()
