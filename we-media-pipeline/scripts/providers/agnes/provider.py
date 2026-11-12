"""Agnes image API — https://apihub.agnes-ai.com/v1/images/generations"""
import base64
import os

import requests

from ..common import api_key

DEFAULT_MODEL = "agnes-image-2.1-flash"
API_URL = "https://apihub.agnes-ai.com/v1/images/generations"


def default_model() -> str:
    return os.environ.get("AGNES_IMAGE_MODEL") or DEFAULT_MODEL


def size_for(aspect_ratio: str) -> str:
    """Agnes takes the ratio shorthand ("16x9") and picks its own pixel size."""
    return aspect_ratio.replace(":", "x")


def draw(prompt: str, size: str, model: str | None = None) -> bytes:
    key = api_key(("AGNES_API_KEY",), "agnes_api_key", "Agnes")
    resp = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": model or default_model(), "prompt": prompt, "size": size,
              "return_base64": True},
        timeout=300,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"agnes image_generation failed ({resp.status_code}): {resp.text[:400]}")
    b64 = (resp.json().get("data") or [{}])[0].get("b64_json")
    if not b64:
        raise RuntimeError(f"no image in response: {resp.text[:400]}")
    return base64.b64decode(b64)
