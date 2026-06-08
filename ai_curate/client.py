"""
ai_curate.client -- Llama-swap-compatible vision model client.

Replaces the Ollama-specific request path from curate.py with a
chat/completions client that works with llama.cpp served through
llama-swap. Uses the OpenAI-compatible /v1/chat/completions endpoint.
"""

import base64
import json
import logging
import re
import socket
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, Optional, Tuple

from ai_curate.config import DEFAULT_BASE_URL, DEFAULT_MODEL, REQUEST_TIMEOUT, API_KEY

logger = logging.getLogger(__name__)

# Prompt template for element scoring
ELEMENT_PROMPT = """Check if each element is visible in this image.

{elements}

For each number, answer YES or NO.
Respond with ONLY this format, one per line:
1:YES
2:NO
3:YES
..."""


def build_score_payload(
    model: str,
    prompt_text: str,
    image_b64: str,
    content_type: str = "image/png",
) -> Dict:
    """Build a chat/completions request payload with an image.

    Uses the OpenAI-compatible multimodal message format that
    llama.cpp / llama-swap accepts.

    Args:
        model: Model alias to route through llama-swap.
        prompt_text: The scoring prompt text.
        image_b64: Base64-encoded image data.
        content_type: MIME type for the image data URI (default: image/png).

    Returns:
        Dict suitable for JSON serialization as the request body.
    """
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{content_type};base64,{image_b64}"},
                    },
                ],
            }
        ],
        "stream": False,
    }


def parse_score_response(
    content: str,
    num_elements: int,
) -> Tuple[int, int, Dict[int, str], str]:
    """Parse YES/NO element responses from the vision model output.

    Args:
        content: Raw text output from the model.
        num_elements: Expected number of element responses.

    Returns:
        Tuple of (yes_count, total, details_dict, error_message).
        On failure, yes_count is -1 and error_message is non-empty.
    """
    yes_count = 0
    details: Dict[int, str] = {}

    for line in content.strip().replace("\r\n", "\n").split("\n"):
        line = line.strip()
        match = re.match(r"(\d+)\s*[:\.]\s*(YES|NO)$", line, re.IGNORECASE)
        if match:
            num = int(match.group(1))
            answer = match.group(2).upper()
            if 1 <= num <= num_elements:
                details[num] = answer
                if answer == "YES":
                    yes_count += 1

    if not details:
        return -1, num_elements, {}, "failed to parse response"

    return yes_count, num_elements, details, ""


class VisionClient:
    """Client for scoring images against element lists via llama-swap.

    Uses the /v1/chat/completions endpoint which is compatible with
    llama.cpp's OpenAI-compatible server mode.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        model: Optional[str] = DEFAULT_MODEL,
        timeout: int = REQUEST_TIMEOUT,
        api_key: Optional[str] = API_KEY,
    ):
        self.base_url = base_url.rstrip("/")
        self.default_model = model
        self.timeout = timeout
        self.api_key = api_key

    def score_image(
        self,
        image_b64: str,
        prompt_text: str,
        elements: list,
        model: Optional[str] = None,
        content_type: str = "image/png",
    ) -> Tuple[int, int, Dict[int, str], str]:
        """Send an image to the vision model and check elements.

        Args:
            image_b64: Base64-encoded image data.
            prompt_text: The scoring prompt (already formatted with elements).
            elements: List of element strings (used for response validation).
            model: Optional model override; falls back to default_model.
            content_type: MIME type for the image (default: image/png).

        Returns:
            Tuple of (score, total, details, error_message).
        """
        model = model or self.default_model
        if not model:
            return -1, len(elements), {}, "error: no model configured"
        payload = build_score_payload(model, prompt_text, image_b64, content_type=content_type)
        payload_bytes = json.dumps(payload).encode("utf-8")

        url = f"{self.base_url}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(
            url,
            data=payload_bytes,
            headers=headers,
        )

        max_retries = 1  # One retry on transient network errors only
        last_transient_error: Optional[str] = None
        for attempt in range(max_retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode())
                # OpenAI-compatible response format
                choices = data.get("choices") or [{}]
                if isinstance(choices, list) and choices:
                    content = choices[0].get("message", {}).get("content")
                else:
                    content = None
                if content is None:
                    return -1, len(elements), {}, "failed to parse response"
                return parse_score_response(content, len(elements))

            # Transient network errors get one retry. HTTPError (4xx/5xx
            # response codes) is NOT retried: a misconfigured URL or bad
            # API key returns 4xx and retrying just delays the surface
            # of the real configuration error.
            except (urllib.error.URLError, socket.timeout) as e:
                last_transient_error = f"error: {e}"
                if attempt < max_retries:
                    continue
                return -1, len(elements), {}, last_transient_error

            except urllib.error.HTTPError as e:
                return -1, len(elements), {}, f"error: HTTP {e.code} {e.reason}"

            except json.JSONDecodeError as e:
                return -1, len(elements), {}, f"error: {e}"

        # Unreachable: the for-loop above always either returns from the
        # try block, returns from an except, or continues to a later
        # iteration that returns. Listed explicitly to keep mypy happy
        # and to give a defensive last line if the retry count is ever
        # changed.
        return -1, len(elements), {}, last_transient_error or "error: exhausted retries"

    # Maximum image file size for base64 encoding (default 50 MB)
    MAX_IMAGE_SIZE_BYTES: int = 50 * 1024 * 1024

    @staticmethod
    def encode_image(path: str) -> str:
        """Base64-encode an image file.

        Args:
            path: Filesystem path to the image.

        Returns:
            Base64-encoded string of the file contents.

        Raises:
            ValueError: If the file exceeds MAX_IMAGE_SIZE_BYTES.
        """
        file_path = Path(path)
        file_size = file_path.stat().st_size
        if file_size > VisionClient.MAX_IMAGE_SIZE_BYTES:
            raise ValueError(
                f"Image file too large: {file_size} bytes (max {VisionClient.MAX_IMAGE_SIZE_BYTES})"
            )
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    @staticmethod
    def content_type_for(path: str) -> str:
        """Return the MIME type for an image file based on its extension.

        Falls back to image/png for unrecognized extensions.
        """
        suffix = Path(path).suffix.lower()
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }
        return mime_map.get(suffix, "image/png")
