"""Ask a vision model whether a freshly drawn illustration is usable.

Two things go wrong often enough to be worth catching: the model sneaks some
text or a watermark into the picture, and it draws something unrelated to what
was asked. Both are invisible to the pipeline until a human opens the file.

Usage:
  python check_image.py --image xiaohei_01.png --scene "the small figure pushes a cart"
"""
import base64
import json
import os
import re
import sys
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
API_BASE = os.environ.get("MINIMAX_BASE_URL", "https://api.minimaxi.com").rstrip("/")
MODEL = os.environ.get("MINIMAX_CHECK_MODEL", "MiniMax-M3.1-Flash")

PROMPT = (
    "这是一张白底线稿插画。请判断两件事，只输出一个 JSON 对象，不要解释：\n"
    '{"has_text": true/false, "matches": true/false, "reason": "一句话说明"}\n'
    "1) has_text：画面里除了线条和小人之外，有没有出现文字、字母、数字、水印或签名？\n"
    "2) matches：画面内容是否符合这句描述——{scene}\n"
)

# 新闻配图不是线稿插画，判的是"跟主题有没有关系"，不是"画得对不对"
RELEVANCE_PROMPT = (
    "这张图来自新闻网页。请判断它和主题「{topic}」是否相关，只输出一个 JSON 对象，不要解释：\n"
    '{"relevant": true/false, "reason": "一句话说明"}\n'
    "判定规则（按顺序判断）：\n"
    "1. 画面主体是该主题的产品、界面、相关人物、相关场景 → true\n"
    "2. 画面是该主题所在话题的通用场景（如同行业的办公、客服、电商、社交现场）→ true\n"
    "3. 网站 logo、用户头像、通用横幅、纯装饰插画、图表模板、"
    "明显属于其他不相干话题的照片 → false\n"
)


def get_api_key() -> str:
    sys.path.insert(0, str(PROJECT_ROOT / "shared"))
    from config_loader import get_config_value
    key = get_config_value("minimax_api_key") or ""
    if not key:
        sys.exit("minimax_api_key not found in env MINIMAX_API_KEY or config.json")
    return key


def _parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def check_image(path, scene: str = "", timeout: int = 240) -> dict:
    """{'ok': bool, 'has_text': bool, 'matches': bool, 'reason': str}

    Never raises: a failed check returns ok=True so a flaky API can't block
    the pipeline.
    """
    return _ask(path, PROMPT.replace("{scene}", scene or "(no description given)"), timeout)


def check_relevance(path, topic: str, timeout: int = 240) -> dict:
    """{'relevant': bool, 'reason': str} — is this news photo on-topic?

    Never raises: a failed check returns relevant=True so a flaky API can't
    silently drop every image.
    """
    data = _ask(path, RELEVANCE_PROMPT.replace("{topic}", topic or "(no topic given)"), timeout)
    return {"relevant": bool(data.get("relevant", True)),
            "reason": str(data.get("reason", ""))[:200]}


def _ask(path, prompt: str, timeout: int = 240) -> dict:
    b64 = base64.b64encode(Path(path).read_bytes()).decode()
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(
        Path(path).suffix.lower().lstrip("."), "image/png")
    try:
        resp = requests.post(
            f"{API_BASE}/v1/chat/completions",
            headers={"Authorization": f"Bearer {get_api_key()}", "Content-Type": "application/json"},
            json={
                "model": MODEL,
                "temperature": 0,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64," + b64}},
                ]}],
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001 - a broken check must not break the run
        return {"ok": True, "has_text": False, "matches": True, "relevant": True,
                "reason": f"check skipped: {type(exc).__name__}"}

    data = _parse(content)
    has_text = bool(data.get("has_text"))
    matches = bool(data.get("matches", True))
    return {"ok": not has_text and matches, "has_text": has_text, "matches": matches,
            "relevant": bool(data.get("relevant", True)),
            "reason": str(data.get("reason", ""))[:200]}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--scene", default="")
    ap.add_argument("--topic", default="", help="按主题相关性判断（新闻配图）")
    args = ap.parse_args()
    if args.topic:
        print(json.dumps(check_relevance(args.image, args.topic), ensure_ascii=False))
    else:
        print(json.dumps(check_image(args.image, args.scene), ensure_ascii=False))


if __name__ == "__main__":
    main()
