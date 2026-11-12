"""GLM-Image (Z.AI) — https://api.z.ai/api/paas/v4/images/generations

Text-to-image only. Returns a URL, not base64, so there is one extra download.
Sizes must be between 1024 and 2048 on a side, divisible by 32, and stay under
2**22 pixels in total.
"""
import base64
import os

import requests

from ..common import api_key

DEFAULT_MODEL = "glm-image"
MAX_PIXELS = 2 ** 22
STEP = 32

# Official recommended sizes for glm-image.
RECOMMENDED = {
    "1:1": "1280x1280",
    "3:2": "1568x1056",
    "2:3": "1056x1568",
    "4:3": "1472x1088",
    "3:4": "1088x1472",
    "16:9": "1728x960",
    "9:16": "960x1728",
}


def default_model() -> str:
    return (os.environ.get("ZAI_IMAGE_MODEL") or os.environ.get("BIGMODEL_IMAGE_MODEL")
            or DEFAULT_MODEL)


def api_url() -> str:
    base = (os.environ.get("ZAI_BASE_URL") or os.environ.get("BIGMODEL_BASE_URL")
            or "https://api.z.ai/api/paas/v4").rstrip("/")
    if base.endswith("/images/generations"):
        return base
    if base.endswith("/v4"):
        return f"{base}/images/generations"
    return f"{base}/api/paas/v4/images/generations"


def size_for(aspect_ratio: str) -> str:
    """GLM-Image wants explicit WxH, not a ratio shorthand."""
    if aspect_ratio in RECOMMENDED:
        return RECOMMENDED[aspect_ratio]
    try:
        w, h = (float(v) for v in aspect_ratio.split(":"))
    except ValueError:
        return RECOMMENDED["16:9"]
    long_edge = 1728
    short = max(512, min(long_edge, round(long_edge * min(w, h) / max(w, h) / STEP) * STEP))
    width, height = (long_edge, short) if w >= h else (short, long_edge)
    while width * height > MAX_PIXELS:
        width -= STEP
        height -= STEP
    return f"{width}x{height}"


def draw(prompt: str, size: str, model: str | None = None) -> bytes:
    key = api_key(("ZAI_API_KEY", "BIGMODEL_API_KEY"), "zai_api_key", "Z.AI")
    resp = requests.post(
        api_url(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": model or default_model(), "prompt": prompt, "quality": "hd", "size": size},
        timeout=300,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Z.AI image_generation failed ({resp.status_code}): {resp.text[:400]}")
    item = (resp.json().get("data") or [{}])[0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    url = item.get("url")
    if not url:
        raise RuntimeError(f"no image in response: {resp.text[:400]}")
    img = requests.get(url, timeout=300)
    if img.status_code != 200:
        raise RuntimeError(f"downloading the generated image failed ({img.status_code})")
    return img.content
