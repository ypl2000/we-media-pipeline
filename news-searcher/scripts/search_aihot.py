#!/usr/bin/env python3
"""AIHOT 信源适配器 —— 把 aihot.news 的公开 API 映射成 search_news.py 的输出契约。

为什么要这个文件
----------------
`run-pipeline.yml` 的 Phase 1 只认两个产物：`01_search_results.md` 和
`01_news_images.json`。这里输出同样的两个文件，workflow 只需把命令从
search_news.py 换成 search_aihot.py，其余阶段（写作 / 评审 / 配图 / 导出）不用动。

和 search_news.py 的关键差异（别当成 bug）
------------------------------------------
1. **没有图片**：AIHOT 的 API 不返回图片，`01_news_images.json` 恒为 `[]`。
   配图仍要走 ImageDownload 阶段回原文页抓。
2. **q 是模糊匹配**：`q=Gemini` 会混进低分无关条目。所以默认按窗口拉「精选」，
   有关键词时按 score 过滤，不指望它做精准检索。
3. **失败语义保持一致**：窗口内条数 < 3 直接退出码 1，交给 workflow 重试/报错。

使用
----
  # 今天写什么（默认：近 24h 精选 + 热点榜）
  python search_aihot.py -o 01_search_results.md

  # 指定窗口/条数
  python search_aihot.py -d 2 -n 12 -f markdown -o 01_search_results.md

  # 带了关键词（模糊匹配，按 score 过滤）
  python search_aihot.py "Gemini" -n 10 -o 01_search_results.md

  # 只看某个事件的时间线（选题已定、要原始报道清单）
  python search_aihot.py --story 760e0591-91c2-4b7a-aea8-5a33ba5d86b1

约定（来自 https://aihot.news/llms.txt）
----------------------------------------
匿名只读、无需 Key；items/hot-topics 最快 60 秒一次；请带 gzip 与 If-None-Match；
单 IP 约 60 次/分钟会 429，按 Retry-After 退避。详情页对默认 UA 返回 403，必须带浏览器 UA。
"""
import argparse
import gzip
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://aihot.news"

# Windows 控制台默认 GBK，输出中文/符号会炸，统一改成 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

CATEGORY_ZH = {
    "ai-models": "AI 模型",
    "ai-products": "AI 产品",
    "industry": "行业动态",
    "paper": "论文",
    "tip": "教程",
    "opinion": "观点",
}


def api(path, etag_file=None):
    """GET 一个 API 路径，返回解析后的 JSON。支持 gzip 与 If-None-Match。"""
    headers = {"User-Agent": UA, "Accept": "application/json",
               "Accept-Encoding": "gzip"}
    etag = None
    if etag_file and Path(etag_file).exists():
        etag = Path(etag_file).read_text(encoding="utf-8").strip()
        if etag:
            headers["If-None-Match"] = etag

    req = urllib.request.Request(BASE + path, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            new_etag = r.headers.get("ETag")
            if etag_file and new_etag:
                Path(etag_file).write_text(new_etag, encoding="utf-8")
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return {"notModified": True}
        if e.code == 429:
            wait = int(e.headers.get("Retry-After", "30"))
            print(f"  429 限流，按 Retry-After 等 {wait}s", file=sys.stderr)
            time.sleep(min(wait, 60))
            return api(path, etag_file)
        raise


def iso_local(s):
    """2026-11-11T05:47:04.000Z -> 11-11 13:47（本地时区）。"""
    if not s:
        return ""
    from datetime import datetime, timezone
    dt = datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone()
    return dt.strftime("%m-%d %H:%M")


def collect(days, limit, query, story_id):
    """按参数拉数据，返回 (items, hot, story)。"""
    items, hot, story = [], [], None

    if story_id:
        story = api(f"/api/v1/stories/{urllib.parse.quote(story_id)}").get("story")
        return items, hot, story

    window = "24h" if days <= 1 else "7d"
    qs = {"mode": "selected" if not query else "all", "window": window,
          "limit": str(limit), "by": "published"}
    if query:
        qs["q"] = query
    items = api("/api/v1/items?" + urllib.parse.urlencode(qs)).get("items", [])

    if query:
        # q 是模糊匹配：只留 score 说得过去的，避免把无关条目塞进选题池
        items = [i for i in items if (i.get("score") or 0) >= 40] or items

    try:
        hot = api("/api/v1/hot-topics").get("items", [])
    except Exception as exc:            # 热点榜挂了不该拖垮主流程
        print(f"  热点榜拉取失败（不影响主流程）: {exc}", file=sys.stderr)

    return items, hot, story


def render(items, hot, story, query, days):
    """生成 markdown，结构与 search_news.py 的 markdown 输出保持一致。"""
    L = []
    label = query or "AI 行业动态（无主题，按精选自动选题）"
    L.append(f"# Search Results: {label}")
    L.append("")
    L.append(f"**Time Range:** last {days} day(s)")
    L.append(f"**Results:** {len(items) if items else (len(story.get('reports', [])) if story else 0)}")
    L.append(f"**Source:** AIHOT 公开 API v1（匿名只读，https://aihot.news）")
    L.append("")
    L.append("---")
    L.append("")

    # 热点榜：多信源共识，是「这事有多大」的量级信号
    if hot:
        L.append("## 热点榜（近 48h 多信源共识，Top 10）")
        L.append("")
        L.append("| # | 独立信源 | 事件 | 事件页 |")
        L.append("|---|---|---|---|")
        for h in hot:
            L.append(f"| {h.get('rank')} | {h.get('sourceCount', '?')} | {h.get('title')} | "
                     f"{h.get('links', {}).get('story', '')} |")
        L.append("")

    # 事件模式：直接给原始报道清单
    if story:
        L.append(f"## 事件：{story.get('title')}")
        L.append("")
        L.append(f"**信源数:** {story.get('sourceCount')} / **报道数:** {story.get('reportCount')}")
        L.append("")
        L.append("### AI 综述（仅作线索，事实必须回原文核对）")
        L.append("")
        L.append((story.get("digest") or "").strip())
        L.append("")
        L.append("### 原始报道（按时间倒序）")
        L.append("")
        for r in (story.get("reports") or [])[:40]:
            L.append(f"- **{r.get('title')}** — {r.get('source', {}).get('name', '')}")
            L.append(f"  - 原文: {r.get('links', {}).get('original', '')}")
            L.append(f"  - 时间: {iso_local(r.get('publishedAt'))}")
        L.append("")
        return "\n".join(L)

    # 常规：给选题池
    L.append("## News Articles")
    L.append("")
    for i, it in enumerate(items, 1):
        cat = CATEGORY_ZH.get(it.get("category"), it.get("category") or "")
        L.append(f"### {i}. {it.get('title')}")
        L.append(f"**Source:** {it.get('source', {}).get('name', '')}")
        L.append(f"**Published:** {iso_local(it.get('publishedAt'))}")
        L.append(f"**URL:** {it.get('links', {}).get('original', '')}")
        L.append(f"**AIHOT:** {it.get('links', {}).get('aihot', '')}")
        L.append(f"**Score:** {(it.get('score') or 0) / 100:.2f}（AIHOT 0-100）")
        L.append(f"**Category:** {cat}")
        if it.get("reason"):
            L.append(f"**为何入选:** {it.get('reason')}")
        L.append("")
        L.append((it.get("summary") or "")[:600])
        L.append("")
        L.append("---")
        L.append("")

    L.append("## 使用须知")
    L.append("")
    L.append("- 本文件是**选题层**产物：只用来决定写什么，不要整段搬进正文。")
    L.append("- 正文事实必须回 `URL` 指向的原文核对；AIHOT 摘要由 AI 生成，可能出错。")
    L.append("- AIHOT 对「选取/编排/摘要/评分」享有权利；原文与客观事实不受其限制。")
    L.append("- 免费使用范围：个人非商业 / 公益 / 组织内部；对外商业发布需书面授权。")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="AIHOT → we-media-pipeline 信源适配器")
    ap.add_argument("query", nargs="?", default="", help="关键词（可选；不填=按精选自动选题）")
    ap.add_argument("-d", "--days", type=int, default=1, help="时间窗口天数（1=24h，其余=7d）")
    ap.add_argument("-n", "--num", type=int, default=15, help="最多取多少条")
    ap.add_argument("-f", "--format", default="markdown", choices=["markdown", "json", "text"])
    ap.add_argument("-o", "--output", help="输出 markdown 路径")
    ap.add_argument("--story", help="只拉某个事件的时间线（publicId）")
    args = ap.parse_args()

    items, hot, story = collect(args.days, args.num, args.query, args.story)

    total = len(story.get("reports", [])) if story else len(items)
    if total < 3 and not args.story:
        print(json.dumps({"success": False,
                          "error": f"窗口内仅 {total} 条（<3），按流水线语义判失败"},
                         ensure_ascii=False))
        return 1

    md = render(items, hot, story, args.query, args.days)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding="utf-8")
        print(f"[ok] 写入 {out}")
        # 契约要求同名图片清单；AIHOT 无图，写空数组让下游知道要回原文抓
        img = out.with_name("01_news_images.json")
        img.write_text("[]", encoding="utf-8")
        print(f"[ok] 写入 {img}（AIHOT 不返回图片，需 ImageDownload 阶段补）");

    print(json.dumps({
        "success": True,
        "query": args.query,
        "time_range": f"last {args.days} day(s)",
        "results_count": total,
        "hot_topics": len(hot or []),
        "images_count": 0,
        "top": (items[0]["title"] if items else (story or {}).get("title", "")),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
