"""
ai_curate.client -- Llama-swap-compatible vision model client.

Replaces the Ollama-specific request path from curate.py with a
chat/completions client that works with llama.cpp served through
llama-swap. Uses the OpenAI-compatible /v1/chat/completions endpoint.
"""

import base64
import json
import re
import socket
import urllib.error
import urllib.request
from typing import Dict, Optional, Tuple

from ai_curate.config import DEFAULT_BASE_URL, DEFAULT_MODEL, REQUEST_TIMEOUT

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
) -> Dict:
    """Build a chat/completions request payload with an image.

    Uses the OpenAI-compatible multimodal message format that
    llama.cpp / llama-swap accepts.

    Args:
        model: Model alias to route through llama-swap.
        prompt_text: The scoring prompt text.
        image_b64: Base64-encoded image data.

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
                        "image_url": {"url": f"data:image/png;base64,{image_b64}"},
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

    for line in content.strip().split("\n"):
        line = line.strip()
        match = re.match(r"(\d+)\s*[:\.]\s*(YES|NO)", line, re.IGNORECASE)
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
        model: str = DEFAULT_MODEL,
        timeout: int = REQUEST_TIMEOUT,
    ):
        self.base_url = base_url.rstrip("/")
        self.default_model = model
        self.timeout = timeout

    def score_image(
        self,
        image_b64: str,
        prompt_text: str,
        elements: list,
        model: Optional[str] = None,
    ) -> Tuple[int, int, Dict[int, str], str]:
        """Send an image to the vision model and check elements.

        Args:
            image_b64: Base64-encoded image data.
            prompt_text: The scoring prompt (already formatted with elements).
            elements: List of element strings (used for response validation).
            model: Optional model override; falls back to default_model.

        Returns:
            Tuple of (score, total, details, error_message).
        """
        model = model or self.default_model
        payload = build_score_payload(model, prompt_text, image_b64)
        payload_bytes = json.dumps(payload).encode("utf-8")

        url = f"{self.base_url}/v1/chat/completions"
        req = urllib.request.Request(
            url,
            data=payload_bytes,
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode())
            # OpenAI-compatible response format
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return parse_score_response(content, len(elements))

        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            json.JSONDecodeError,
            socket.timeout,
        ) as e:
            return -1, len(elements), {}, f"error: {e}"

    @staticmethod
    def encode_image(path: str) -> str:
        """Base64-encode an image file.

        Args:
            path: Filesystem path to the image.

        Returns:
            Base64-encoded string of the file contents.
        """
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
