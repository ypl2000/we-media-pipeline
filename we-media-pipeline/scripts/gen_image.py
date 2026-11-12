"""Generate illustrations. One provider = one package under scripts/providers/.

The Claude agent writes the scene; the provider owns the style template and the
request. Chinese labels are never drawn by the model (it cannot spell Chinese
reliably) — pass --labels and overlay_labels.py stamps them on afterwards.

Usage (single):
  python gen_image.py --scene "the small figure pushes a cart along a line" --labels "写剧本,改稿" --out images_good/xiaohei_01.png

Usage (other protagonist):
  python gen_image.py --character cat --scene "..." --out out.png
  # characters: line_person, cat, robot, dot, none

Usage (batch, drawn concurrently):
  python gen_image.py --prompts-file prompts.json
  # prompts.json: [{"scene": "...", "labels": "a,b", "out": "images_good/xiaohei_01.png",
  #                 "character": "cat", "provider": "glm"}, ...]

Provider chain: --provider glm,agnes (comma separated) beats the env var
IMAGE_PROVIDER, which beats config.json "image_provider_chain", which beats
the old "image_api_type". Each drawing walks the chain and the first provider
whose picture passes --verify wins; a provider whose request fails is skipped.

Config: api keys in config.json (or env vars) — agnes_api_key / zai_api_key.
"""
import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_image import check_image
from overlay_labels import overlay
from providers import PROVIDERS, get_provider
from providers.common import load_config


def resolve_chain(cli_provider: str | None) -> list:
    """Provider chain for this run: CLI > env > config.json > default."""
    for value in (cli_provider, os.environ.get("IMAGE_PROVIDER")):
        if value:
            chain = [p.strip() for p in value.split(",") if p.strip()]
            if chain:
                return chain
    cfg = load_config()
    if cfg.get("image_provider_chain"):
        return list(cfg["image_provider_chain"])
    if cfg.get("image_api_type"):
        return [cfg["image_api_type"]]
    return ["agnes"]


def draw_with_chain(prompt_of, aspect_ratio: str, chain: list, model: str | None,
                     out: str, scene: str, verify: bool, attempts: int) -> dict:
    """Walk the chain until a provider both answers and passes the check."""
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    report = {"ok": True, "has_text": False, "matches": True, "reason": ""}
    used, error, drew = chain[-1], "", False
    for _ in range(max(1, attempts)):
        for name in chain:
            provider = get_provider(name)
            try:
                prompt = prompt_of(provider)
                data = provider.draw(prompt, provider.size_for(aspect_ratio),
                                     model or provider.default_model())
            except Exception as exc:
                error = f"{name}: {exc}"
                continue
            path.write_bytes(data)
            used, drew = name, True
            if not verify:
                return {"file": str(path), "check": report, "provider": name, "error": ""}
            report = check_image(str(path), scene)
            if report.get("ok", True):
                return {"file": str(path), "check": report, "provider": name, "error": ""}
            error = f"{name}: check failed — {report.get('reason', '')}"
    if not drew:
        # nothing was drawn at all — every provider in the chain refused
        report = {"ok": False, "has_text": False, "matches": True, "reason": error}
    return {"file": str(path), "check": report, "provider": used, "error": error}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", help="one short sentence describing the scene")
    ap.add_argument("--prompt", help="raw prompt (skips the style template)")
    ap.add_argument("--style", default=None,
                    help="style template (default: the provider's own, xiaohei)")
    ap.add_argument("--character", default=None,
                    help="recurring protagonist (default: the style's own); "
                         "characters: line_person, cat, robot, dot, none")
    ap.add_argument("--out")
    ap.add_argument("--prompts-file",
                    help='JSON list of {"scene": str, "labels": str, "out": str, "style": str, '
                         '"character": str, "provider": str}')
    ap.add_argument("--aspect-ratio", default="16:9")
    ap.add_argument("--provider", default=None,
                    help=f"provider or comma separated chain, e.g. glm,agnes (known: {', '.join(PROVIDERS)})")
    ap.add_argument("--model", default=None)
    ap.add_argument("--labels", default=None,
                    help="comma separated Chinese labels to overlay after drawing")
    ap.add_argument("--verify", action="store_true",
                    help="have a vision model check each drawing, redraw if it is off")
    ap.add_argument("--attempts", type=int, default=2)
    args = ap.parse_args()

    chain = resolve_chain(args.provider)
    for name in chain:
        if name not in PROVIDERS:
            ap.error(f"unknown provider '{name}' — pick from: {', '.join(PROVIDERS)}")

    def run(item):
        style = item.get("style") or args.style
        scene, raw = item.get("scene"), item.get("prompt")
        character = item.get("character") or args.character
        item_chain = ([p.strip() for p in item["provider"].split(",") if p.strip()]
                      if item.get("provider") else chain)

        def prompt_of(provider):
            return provider.build_prompt(scene, raw, style or provider.DEFAULT_STYLE, character)

        result = draw_with_chain(prompt_of, args.aspect_ratio, item_chain, args.model,
                                  item["out"], scene or "", args.verify, args.attempts)
        if (item.get("labels") or args.labels) and Path(result["file"]).exists():
            # The model is told not to draw any text; we add the Chinese labels
            # ourselves so every character is exactly what the caller asked for.
            provider = get_provider(result["provider"])
            templates = provider.STYLE_TEMPLATES
            color = templates.get(style or provider.DEFAULT_STYLE, {}).get("label_color", "black")
            overlay(result["file"], item.get("labels") or args.labels, result["file"], color=color)
        return result

    if args.prompts_file:
        items = json.loads(Path(args.prompts_file).read_text(encoding="utf-8"))
        with ThreadPoolExecutor(max_workers=min(4, len(items) or 1)) as pool:
            results = list(pool.map(run, items))
    elif args.out:
        results = [run({"scene": args.scene, "prompt": args.prompt, "out": args.out,
                        "labels": args.labels})]
    else:
        ap.error("need --scene/--prompt with --out, or --prompts-file")

    failed = [r["file"] for r in results if not r["check"].get("ok", True)]
    print(json.dumps({"success": not failed, "files": [r["file"] for r in results],
                      "providers": [r["provider"] for r in results],
                      "checks": [r["check"] for r in results],
                      "errors": [r["error"] for r in results],
                      "failed": failed}, ensure_ascii=False))


if __name__ == "__main__":
    main()
