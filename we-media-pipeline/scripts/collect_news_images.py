"""Collect the news photos that actually belong in the article.

The search API hands back every image on a page -- site logos, author avatars,
promos for unrelated stories -- so downloading that list verbatim fills the
article with pictures that have nothing to do with the topic. This script keeps
only the lead image of each search hit (a hit is relevance-ranked by the search
engine, so its lead image is on-topic by construction), drops the obvious junk
URLs, and drops anything too small to use.

`--vision` additionally asks a vision model whether a picture is on-topic.
Off by default: on borderline photos a small model gives inconsistent verdicts
(same batch, two runs, different answers), and a flaky gate is worse than no
gate.

Usage:
  python collect_news_images.py --results-md 01_search_results.md \
      --topic "personal agent" --out-dir images_good --pool-dir images-all \
      --article 03_article.md
"""
import argparse
import hashlib
import io
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_image import check_relevance  # noqa: E402

EXT = {b"\xff\xd8\xff": "jpg", b"\x89PNG": "png", b"GIF8": "gif", b"RIFF": "webp"}
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif")
JUNK = re.compile(r"(logo|placeholder|icon|sprite|avatar|favicon|badge|watermark|/dist/images/|"
                  r"qr[-_]?code|series-elements|brand|theme|[-_]graphic)", re.I)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}


def _sniff(raw: bytes) -> str:
    for magic, ext in EXT.items():
        if raw.startswith(magic):
            return ext
    try:
        return Image.open(io.BytesIO(raw)).format.lower()
    except Exception:
        return "jpg"


def _looks_like_image(url: str) -> bool:
    """True for URLs that plausibly serve an image.

    CDNs often hide the extension behind a query string
    (/cdn/image?src=...jpg), so a missing extension is not a reason to skip.
    Whatever comes back gets sniffed and opened by PIL anyway.
    """
    path = url.split("?")[0].lower()
    if path.endswith(IMG_EXT):
        return True
    return "." not in path.rsplit("/", 1)[-1]


def parse_lead_images(md: str) -> list:
    """Lead image of every search hit, in result order.

    The markdown keeps each hit's own image list, which is the only place the
    "which picture belongs to which article" mapping survives.
    """
    leads = []
    for block in re.split(r"^### \d+\. ", md, flags=re.M)[1:]:
        urls = []
        in_images = False
        for line in block.splitlines():
            if line.startswith("**Images:**"):
                in_images = True
                continue
            if in_images:
                if line.startswith("- http"):
                    urls.append(line[2:].strip())
                elif line.strip() and not line.startswith("- "):
                    break
        for u in urls:
            if _looks_like_image(u) and not JUNK.search(u):
                leads.append(u)
                break
    return leads


def download(url: str, pool: Path) -> Path:
    """Fetch one image into the pool dir, content-addressed so re-runs reuse it."""
    name = hashlib.sha1(url.encode()).hexdigest()[:12]
    existing = list(pool.glob(f"{name}.*"))
    if existing:
        return existing[0]
    raw = requests.get(url, headers=UA, timeout=30).content
    path = pool / f"{name}.{_sniff(raw)}"
    path.write_bytes(raw)
    return path


def article_title(path) -> str:
    """H1 of the article, used to ground the relevance check."""
    if not path:
        return ""
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def rewrite_news_section(article_path, names, dir_name="images_good"):
    """Replace the 图片占位符 list under 「## 新闻配图」, leaving the rest alone."""
    art = Path(article_path)
    lines = art.read_text(encoding="utf-8").splitlines()
    start = next((i for i, l in enumerate(lines) if re.match(r"^##\s*新闻配图", l)), None)
    if start is None:
        lines += ["", "## 新闻配图", ""]
        start = len(lines) - 2
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].startswith("## ") and not lines[i].startswith("### ")), len(lines))
    body = [l for l in lines[start + 1:end] if "[[IMG:" not in l]
    lines[start + 1:end] = body + [f"[[IMG: {dir_name}/{n}]]" for n in names]
    art.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-md", required=True, help="01_search_results.md")
    ap.add_argument("--topic", required=True, help="文章主题，用于相关性判断")
    ap.add_argument("--out-dir", required=True, help="图片最终目录（images_good）")
    ap.add_argument("--pool-dir", default="", help="原始下载目录（images-all）")
    ap.add_argument("--article", default="", help="要把占位符写回去的 markdown")
    ap.add_argument("--min-width", type=int, default=800)
    ap.add_argument("--min-height", type=int, default=600)
    ap.add_argument("--vision", action="store_true",
                    help="额外用视觉模型判相关性（边界图上不稳定，默认关闭）")
    args = ap.parse_args()

    md = Path(args.results_md).read_text(encoding="utf-8")
    leads = parse_lead_images(md)
    if not leads:
        sys.exit("no usable image found in " + args.results_md)

    out_dir = Path(args.out_dir)
    pool = Path(args.pool_dir) if args.pool_dir else out_dir.parent / "images-all"
    out_dir.mkdir(parents=True, exist_ok=True)
    pool.mkdir(parents=True, exist_ok=True)

    # download + size filter
    candidates = []
    for url in leads:
        try:
            path = download(url, pool)
            w, h = Image.open(path).size
        except Exception as exc:  # noqa: BLE001
            print(f"  skip {url[:80]}: {exc}", file=sys.stderr)
            continue
        if w < args.min_width or h < args.min_height:
            print(f"  skip {path.name}: {w}x{h} too small", file=sys.stderr)
            continue
        candidates.append((url, path))

    # relevance check -- the topic alone is too thin for the model to judge,
    # so ground it with the article title as well
    title = article_title(args.article)
    topic = f"{args.topic}；相关文章标题：{title}" if title else args.topic

    kept, rejected = [], []
    if not args.vision:
        kept = [(u, p, "") for u, p in candidates]
    else:
        def judge(item):
            url, path = item
            try:
                res = check_relevance(path, topic)
            except Exception as exc:  # noqa: BLE001
                res = {"relevant": True, "reason": f"check failed: {exc}"}
            return item, res

        with ThreadPoolExecutor(max_workers=6) as pool_exec:
            for (url, path), res in pool_exec.map(judge, candidates):
                (kept if res.get("relevant") else rejected).append((url, path, res.get("reason", "")))
                print(f"  {'keep' if res.get('relevant') else 'drop'} {path.name}: {res.get('reason','')}",
                      file=sys.stderr)

    # write into out-dir as news_NNN.ext, pruning stale news_* we no longer use
    names = []
    for i, (_url, path, _reason) in enumerate(kept, 1):
        dst = out_dir / f"news_{i:03d}{path.suffix.lower()}"
        if dst.resolve() != path.resolve():
            dst.write_bytes(path.read_bytes())
        names.append(dst)
    keep_names = {p.name for p in names}
    for stale in out_dir.glob("news_*"):
        if stale.is_file() and stale.name not in keep_names:
            stale.unlink()

    # write placeholders back into the article
    if args.article:
        rewrite_news_section(args.article, [n.name for n in names], out_dir.name)

    print(json.dumps({
        "good": [str(p) for p in names],
        "good_count": len(names),
        "rejected": [{"file": str(p), "reason": r} for _u, p, r in rejected],
        "checked": len(candidates),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
