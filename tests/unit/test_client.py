"""Unit tests for ai_curate.client -- llama-swap vision client."""

import json
import socket

import pytest
from unittest.mock import patch, MagicMock
from ai_curate.client import VisionClient, build_score_payload, parse_score_response


class TestBuildScorePayload:
    """Test request payload construction for the chat/completions endpoint."""

    def test_payload_structure(self):
        """Payload has model, messages, and stream=False."""
        payload = build_score_payload(
            model="vl-scorer",
            prompt_text="Check elements",
            image_b64="abc123",
        )
        assert payload["model"] == "vl-scorer"
        assert payload["stream"] is False
        assert len(payload["messages"]) == 1
        msg = payload["messages"][0]
        assert msg["role"] == "user"
        # Content is a list of parts; find the text part
        text_parts = [p for p in msg["content"] if p.get("type") == "text"]
        assert any("Check elements" in p["text"] for p in text_parts)

    def test_payload_includes_image(self):
        """Payload message content includes the base64 image."""
        payload = build_score_payload(
            model="vl-scorer",
            prompt_text="test",
            image_b64="base64data",
        )
        msg = payload["messages"][0]
        # Content should be a list with text and image_url parts
        assert isinstance(msg["content"], list)
        parts = msg["content"]
        has_text = any(p.get("type") == "text" for p in parts)
        has_image = any(p.get("type") == "image_url" for p in parts)
        assert has_text
        assert has_image


class TestParseScoreResponse:
    """Test parsing of YES/NO element responses from the vision model."""

    def test_parse_yes_no_lines(self):
        """Standard N:YES / N:NO lines are parsed correctly."""
        content = "1:YES\n2:NO\n3:YES\n4:YES"
        score, total, details, err = parse_score_response(content, num_elements=4)
        assert score == 3
        assert total == 4
        assert details == {1: "YES", 2: "NO", 3: "YES", 4: "YES"}
        assert err == ""

    def test_parse_with_dot_separator(self):
        """N.YES / N.NO format is also accepted."""
        content = "1.YES\n2.NO"
        score, total, details, err = parse_score_response(content, num_elements=2)
        assert score == 1
        assert total == 2
        assert details == {1: "YES", 2: "NO"}

    def test_parse_case_insensitive(self):
        """yes/no in lowercase is accepted."""
        content = "1:yes\n2:no\n3:yes"
        score, total, details, err = parse_score_response(content, num_elements=3)
        assert score == 2
        assert details[1] == "YES"
        assert details[2] == "NO"

    def test_parse_empty_response(self):
        """Empty or unparseable response returns failure."""
        score, total, details, err = parse_score_response("", num_elements=4)
        assert score == -1
        assert "failed to parse" in err

    def test_parse_garbled_response(self):
        """Non-matching response text returns failure."""
        score, total, details, err = parse_score_response("blah blah blah", num_elements=4)
        assert score == -1

    def test_parse_with_extra_whitespace(self):
        """Lines with extra whitespace are still parsed."""
        content = "  1 :  YES  \n  2 :  NO  "
        score, total, details, err = parse_score_response(content, num_elements=2)
        assert score == 1
        assert details[1] == "YES"

    def test_parse_rejects_trailing_characters(self):
        """Trailing characters after YES/NO cause the line to be rejected."""
        content = "1:YESextra\n2:NO"
        score, total, details, err = parse_score_response(content, num_elements=2)
        # Only line 2 should parse; line 1 should be rejected
        assert score == 0
        assert total == 2
        assert details == {2: "NO"}

    def test_parse_with_junk_lines(self):
        """Lines with extra junk after YES/NO are ignored."""
        content = "1:YES more text here\n2:NO"
        score, total, details, err = parse_score_response(content, num_elements=2)
        assert score == 0
        assert total == 2
        assert details == {2: "NO"}


class TestVisionClientResponseHandling:
    """Test how the client handles various response shapes."""

    @patch("ai_curate.client.urllib.request.urlopen")
    def test_missing_content_field_returns_failure(self, mock_urlopen):
        """When response has no content field, it should return failure, not empty string."""
        mock_resp = MagicMock()
        # Response with choices but no content field at all
        mock_resp.read.return_value = json.dumps(
            {"choices": [{"message": {}}]}
        ).encode("utf-8")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        client = VisionClient(model="test-model")
        score, total, details, err = client.score_image(
            image_b64="fakebase64",
            prompt_text="test",
            elements=["elem1", "elem2"],
        )
        assert score == -1
        assert "failed to parse" in err

    @patch("ai_curate.client.urllib.request.urlopen")
    def test_no_choices_in_response_returns_failure(self, mock_urlopen):
        """When response has no choices array, it should return failure."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({}).encode("utf-8")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        client = VisionClient(model="test-model")
        score, total, details, err = client.score_image(
            image_b64="fakebase64",
            prompt_text="test",
            elements=["elem1"],
        )
        assert score == -1
        assert "failed to parse" in err


class TestVisionClient:
    """Test the VisionClient class (mocked network calls)."""

    def test_init_defaults(self):
        """Client initializes with default config values."""
        client = VisionClient()
        assert client.base_url is not None
        assert client.default_model is None
        assert client.timeout > 0

    def test_init_custom(self):
        """Client accepts custom base_url and model."""
        client = VisionClient(base_url="http://custom:9999", model="my-model")
        assert client.base_url == "http://custom:9999"
        assert client.default_model == "my-model"

    def test_encode_image_returns_base64(self, tmp_path):
        """encode_image base64-encodes file contents."""
        img_path = tmp_path / "test.png"
        img_path.write_bytes(b"\x89PNG\r\n\x1a\n")
        result = VisionClient.encode_image(str(img_path))
        import base64
        assert result == base64.b64encode(b"\x89PNG\r\n\x1a\n").decode("utf-8")

    def test_content_type_for_png(self):
        """content_type_for returns image/png for .png files."""
        assert VisionClient.content_type_for("file.png") == "image/png"

    def test_content_type_for_jpeg(self):
        """content_type_for returns image/jpeg for .jpg and .jpeg files."""
        assert VisionClient.content_type_for("file.jpg") == "image/jpeg"
        assert VisionClient.content_type_for("file.jpeg") == "image/jpeg"

    def test_content_type_for_webp(self):
        """content_type_for returns image/webp for .webp files."""
        assert VisionClient.content_type_for("file.webp") == "image/webp"

    def test_content_type_for_unknown_falls_back_to_png(self):
        """content_type_for returns image/png for unrecognized extensions."""
        assert VisionClient.content_type_for("file.txt") == "image/png"
        assert VisionClient.content_type_for("file") == "image/png"

    @patch("ai_curate.client.urllib.request.urlopen")
    def test_score_image_success(self, mock_urlopen):
        """score_image returns parsed results on successful API call."""
        # Mock the HTTP response
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"choices": [{"message": {"content": "1:YES\n2:NO\n3:YES"}}]}
        ).encode("utf-8")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        client = VisionClient(model="test-model")
        score, total, details, err = client.score_image(
            image_b64="fakebase64",
            prompt_text="Check these elements",
            elements=["elem1", "elem2", "elem3"],
        )
        assert score == 2
        assert total == 3
        assert err == ""

    @patch("ai_curate.client.urllib.request.urlopen")
    def test_score_image_timeout(self, mock_urlopen):
        """score_image returns failure on timeout."""
        mock_urlopen.side_effect = socket.timeout("timed out")

        client = VisionClient(timeout=5)
        score, total, details, err = client.score_image(
            image_b64="fakebase64",
            prompt_text="test",
            elements=["elem1"],
        )
        assert score == -1
        assert "timeout" in err or "error" in err
