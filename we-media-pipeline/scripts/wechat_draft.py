#!/usr/bin/env python3
"""把 Markdown 文章 + 封面直推微信公众号草稿箱（微信官方 /cgi-bin 接口）。

链路：token → material/add_material（封面→thumb_media_id）→ media/uploadimg（正文图→URL）
      → draft/add →（可选）freepublish/submit

凭据只从环境变量读，不落盘、不进日志：WECHAT_APP_ID / WECHAT_APP_SECRET（作者 WECHAT_AUTHOR）。
用法：
    python wechat_draft.py 03_article.md --cover cover.png --images-dir images_good
    python wechat_draft.py 03_article.md --preview preview.html   # 不调微信，只出 HTML
"""

import argparse
import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "article-formatter" / "scripts"))

try:
    import md_to_word  # 复用现有的 Markdown 解析 + 图片解析逻辑
except Exception as exc:  # pragma: no cover - 依赖缺失时给出可操作的提示
    print(f"需要 python-docx（article-formatter 的同款依赖）：pip install python-docx（{exc}）",
          file=sys.stderr)
    raise SystemExit(2)

WX_API = "https://api.weixin.qq.com"
COVER_MAX_BYTES = 10 * 1024 * 1024   # 永久素材上限
BODY_MAX_BYTES = 1 * 1024 * 1024      # media/uploadimg 上限 1MB
TIMEOUT = 30
FONT = "'Microsoft YaHei','PingFang SC','Noto Sans SC',sans-serif"

IMG_STYLE = "max-width:100%;display:block;margin:0 auto;border-radius:4px;"


# ── 微信接口 ────────────────────────────────────────────────────────────────
class WxError(Exception):
    """微信接口返回了错误码。"""

    def __init__(self, stage, errcode, errmsg):
        self.stage = stage
        self.errcode = errcode
        self.errmsg = errmsg
        super().__init__(f"[{stage}] errcode={errcode} {errmsg}")


class WeChat:
    def __init__(self, app_id, app_secret):
        self.app_id = app_id
        self.app_secret = app_secret
        self.session = requests.Session()
        # 微信校验真实出口 IP，走代理必然对不上 IP 白名单
        self.session.trust_env = False
        self.token = ""

    def _json(self, stage, resp):
        # 不用 resp.json()：requests 对无 charset 的响应默认按 ISO-8859-1 解，
        # 微信返回的中文 errmsg 会被解成乱码
        try:
            data = json.loads(resp.content.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise WxError(stage, -1, f"非 JSON 响应（HTTP {resp.status_code}）：{resp.text[:200]}")
        if data.get("errcode"):
            errcode = data["errcode"]
            errmsg = data.get("errmsg", "")
            hint = ""
            if errcode == 40164:
                hint = "（公众号后台没放行本机出口 IP：设置与开发→基本配置→IP 白名单）"
            elif errcode in (40013, 40125):
                hint = "（appid / secret 不对）"
            elif errcode == 48001:
                hint = "（该订阅号未认证，没有 draft/add 权限）"
            raise WxError(stage, errcode, errmsg + hint)
        return data

    def get_token(self):
        r = self.session.get(
            f"{WX_API}/cgi-bin/token",
            params={"grant_type": "client_credential", "appid": self.app_id, "secret": self.app_secret},
            timeout=TIMEOUT)
        data = self._json("token", r)
        self.token = data.get("access_token", "")
        if not self.token:
            raise WxError("token", -1, "响应里没有 access_token")
        return self.token

    def _upload(self, stage, path, url, field_result):
        with open(path, "rb") as f:
            files = {"media": (Path(path).name, f, _mime(path))}
            r = self.session.post(url, params={"access_token": self.token},
                                  files=files, timeout=TIMEOUT)
        data = self._json(stage, r)
        value = data.get(field_result, "")
        if not value:
            raise WxError(stage, -1, f"响应里没有 {field_result}")
        return value

    def upload_cover(self, path):
        """封面走永久素材，返回 thumb_media_id。"""
        return self._upload("cover", path,
                            f"{WX_API}/cgi-bin/material/add_material?type=image", "media_id")

    def upload_body_image(self, path):
        """正文图走 uploadimg，返回外链 URL。"""
        return self._upload("content", path,
                            f"{WX_API}/cgi-bin/media/uploadimg", "url")

    def add_draft(self, title, author, digest, content, thumb_media_id):
        body = {"articles": [{
            "title": title,
            "author": author,
            "digest": digest,
            "content": content,
            "thumb_media_id": thumb_media_id,
            "need_open_comment": 0,
            "only_fans_can_comment": 0,
        }]}
        # 微信的坑：中文不能走 JSON 的 \uXXXX 转义（requests 默认 ensure_ascii=True
        # 会转义，微信服务端不解码，草稿里全是 "唤" 字面量）。必须 UTF-8 明文。
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        r = self.session.post(f"{WX_API}/cgi-bin/draft/add", params={"access_token": self.token},
                              data=payload,
                              headers={"Content-Type": "application/json; charset=utf-8"},
                              timeout=TIMEOUT)
        data = self._json("draft", r)
        media_id = data.get("media_id", "")
        if not media_id:
            raise WxError("draft", -1, "响应里没有 media_id")
        return media_id

    def delete_draft(self, media_id):
        r = self.session.post(f"{WX_API}/cgi-bin/draft/delete", params={"access_token": self.token},
                              json={"media_id": media_id}, timeout=TIMEOUT)
        self._json("draft_delete", r)
        return True

    def get_draft(self, media_id):
        r = self.session.post(f"{WX_API}/cgi-bin/draft/get", params={"access_token": self.token},
                              json={"media_id": media_id}, timeout=TIMEOUT)
        return self._json("draft_get", r)

    def freepublish(self, media_id):
        r = self.session.post(f"{WX_API}/cgi-bin/freepublish/submit",
                              params={"access_token": self.token},
                              json={"media_id": media_id}, timeout=TIMEOUT)
        data = self._json("publish", r)
        return data.get("publish_id", ""), data.get("article_url", "")


def _mime(path):
    ext = Path(path).suffix.lower()
    return {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".bmp": "image/bmp"}.get(ext, "image/jpeg")


# ── 图片预处理：微信只认 jpg/png/gif/bmp，且正文图上限 1MB ──────────────────
def prepare_image(path, max_bytes):
    """返回 (字节, mime, 后缀)。不满足微信要求时用 Pillow 转码压缩。"""
    raw = Path(path).read_bytes()
    ext = Path(path).suffix.lower()
    if ext in (".jpg", ".jpeg", ".png", ".gif", ".bmp") and len(raw) <= max_bytes:
        return raw, _mime(path), ext
    try:
        from PIL import Image
    except ImportError:
        return raw, _mime(path), ext
    with Image.open(path) as im:
        im = im.convert("RGB")
        buf = io.BytesIO()
        quality = 88
        while True:
            buf.seek(0)
            buf.truncate()
            im.save(buf, "JPEG", quality=quality)
            if len(buf.getvalue()) <= max_bytes or quality <= 55:
                break
            quality -= 8
        data = buf.getvalue()
    return data, "image/jpeg", ".jpg"


# ── Markdown → 微信 HTML ────────────────────────────────────────────────────
def _esc(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def inline(text, upload=None, md_dir=None, preview_base=None):
    """行内格式。upload(src) 返回图片 URL（失败返回 None）。"""
    t = _esc(text)

    def img_sub(m):
        alt, src = m.group(1), m.group(2).strip()
        if upload is None:
            local = Path(src) if os.path.isabs(src) else Path(md_dir or ".") / src
            src = _local_src(local, preview_base)
            return f'<img src="{src}" alt="{alt}" style="{IMG_STYLE}" />'
        url = upload(src, md_dir)
        if not url:
            return f'<span style="color:#9aa0a6;font-size:13px;">[图片上传失败：{alt or src}]</span>'
        return f'<img src="{url}" alt="{alt}" style="{IMG_STYLE}" />'

    t = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", img_sub, t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"__(.+?)__", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", t)
    t = re.sub(r"`([^`]+)`",
               r'<code style="background:#f6f8fa;padding:2px 5px;border-radius:3px;'
               r'font-size:14px;font-family:Menlo,Consolas,monospace;">\1</code>', t)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2" style="color:#576b95;">\1</a>', t)
    return t


def _local_src(path, preview_base):
    """预览时的图片地址：相对预览文件所在目录，file:// 和 http:// 都能加载。"""
    if preview_base:
        return Path(os.path.relpath(path, preview_base)).as_posix()
    return Path(path).resolve().as_uri()


def render_html(elements, upload=None, md_dir=None, preview_base=None):
    """把 md_to_word 解析出的元素渲染成微信能留住的 HTML（样式全部内联）。"""
    out = []
    image_index = 0
    for el in elements:
        kind = el["type"]
        if kind == "heading1":
            continue  # 标题单独走 draft 的 title 字段
        if kind == "heading2":
            out.append(
                f'<h2 style="margin:34px 0 24px;padding:7px 14px;background:#000;color:#fff;'
                f'font-size:17px;font-weight:700;font-style:italic;text-align:center;'
                f'border-radius:2px;line-height:1.5;">{inline(el["content"], upload, md_dir, preview_base)}</h2>')
        elif kind == "heading3":
            out.append(
                f'<h3 style="margin:28px 0 14px;font-size:17px;font-weight:700;color:#000;'
                f'line-height:1.5;">{inline(el["content"], upload, md_dir, preview_base)}</h3>')
        elif kind == "paragraph":
            out.append(
                f'<p style="margin:0 0 20px;font-size:16px;line-height:1.95;">'
                f'{inline(el["content"], upload, md_dir, preview_base)}</p>')
        elif kind == "list":
            items = "".join(
                f'<li style="margin:0 0 8px;font-size:16px;line-height:1.9;">'
                f'{inline(item, upload, md_dir, preview_base)}</li>' for item in el["items"])
            out.append(f'<ul style="margin:0 0 20px;padding-left:24px;">{items}</ul>')
        elif kind == "blockquote":
            body = "".join(
                f'<p style="margin:0 0 8px;font-size:15px;line-height:1.9;">'
                f'{inline(line, upload, md_dir, preview_base)}</p>' for line in el["lines"])
            out.append(
                f'<blockquote style="margin:0 0 20px;padding:14px 18px;'
                f'border-left:3px solid #d0d7de;background:#f7f8fa;color:#5b6472;">{body}</blockquote>')
        elif kind == "table":
            head = "".join(
                f'<th style="padding:8px 10px;border:1px solid #e5e7eb;background:#f5f5f5;'
                f'font-size:14px;text-align:left;">{inline(c, upload, md_dir, preview_base)}</th>'
                for c in el["headers"])
            rows = "".join(
                "<tr>" + "".join(
                    f'<td style="padding:8px 10px;border:1px solid #e5e7eb;font-size:14px;'
                    f'line-height:1.7;">{inline(c, upload, md_dir, preview_base)}</td>' for c in row) + "</tr>"
                for row in el["rows"])
            out.append(
                f'<table style="width:100%;border-collapse:collapse;margin:0 0 20px;">'
                f'<thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>')
        elif kind == "image_placeholder":
            image_index += 1
            desc = el["description"]
            path = md_to_word.find_image_file(el.get("image_dir"), image_index, desc) \
                if el.get("image_dir") else None
            if not path or not os.path.exists(path):
                out.append(
                    f'<p style="margin:0 0 20px;color:#9aa0a6;font-size:13px;">'
                    f'[图片未找到：{desc}]</p>')
                continue
            url = upload(path) if upload else _local_src(path, preview_base)
            if not url:
                out.append(
                    f'<p style="margin:0 0 20px;color:#9aa0a6;font-size:13px;">'
                    f'[图片上传失败：{desc}]</p>')
                continue
            out.append(f'<img src="{url}" style="{IMG_STYLE}" />')
        elif kind == "editor_line":
            out.append(
                f'<p style="margin:0 0 8px;font-size:12px;color:#8a8a8a;font-weight:700;">'
                f'{inline(el["content"], upload, md_dir, preview_base)}</p>')
        elif kind == "hr":
            out.append('<hr style="margin:32px 0;border:none;border-top:1px solid #e5e7eb;" />')
    return (f'<section style="font-family:{FONT};font-size:16px;line-height:1.95;'
            f'color:#2b2b2b;text-align:left;word-break:break-word;">' + "\n".join(out) + "</section>")


def _truncate_bytes(text, limit):
    """按 UTF-8 字节截断（微信限制是字节，不是字符）。尽量断在标点处。"""
    if len(text.encode("utf-8")) <= limit:
        return text, False
    cut = text.encode("utf-8")[:limit].decode("utf-8", "ignore")
    idx = max((cut.rfind(sep) for sep in ("，", "。", "、", "：", "；", "？", "！", " ", ",")), default=-1)
    if idx >= len(cut) * 0.5:  # 断在后半段的标点上，别把标题砍成一截
        cut = cut[:idx]
    return cut, True


def build_content(md_path, image_dir, upload=None, preview_base=None):
    """返回 (html, title, digest)。upload 为 None 时只做本地预览。"""
    md = Path(md_path).read_text(encoding="utf-8")
    md = re.sub(r"^---\r?\n[\s\S]*?\r?\n---\r?\n", "", md)
    elements = md_to_word.parse_markdown(md)
    if image_dir:
        for el in elements:
            if el["type"] == "image_placeholder":
                el["image_dir"] = image_dir
    html = render_html(elements, upload, Path(md_path).resolve().parent, preview_base)
    title = ""
    for el in elements:
        if el["type"] == "heading1":
            title = el["content"]
            break
    digest = ""
    for el in elements:
        if el["type"] == "paragraph":
            digest = re.sub(r"[*_`\[\]()!]", "", el["content"]).strip()
            break
    return html, title, digest[:120]


# ── 主流程 ──────────────────────────────────────────────────────────────────
def find_cover(explicit, image_dir, out_dir):
    if explicit:
        return explicit
    candidates = []
    for base in (image_dir, out_dir):
        if not base:
            continue
        for name in ("cover.png", "cover.jpg", "cover.jpeg"):
            p = Path(base) / name
            if p.exists():
                return str(p)
            candidates.append(str(p))
    raise ValueError(f"找不到封面图，请用 --cover 指定。候选路径：{candidates}")


def main():
    ap = argparse.ArgumentParser(description="推送到微信公众号草稿箱")
    ap.add_argument("article", help="文章 Markdown 路径，如 03_article.md")
    ap.add_argument("--cover", help="封面图路径（jpg/png，≤10MB）")
    ap.add_argument("--images-dir", help="图片目录（占位符 [[IMG: ...]] 在这里解析）")
    ap.add_argument("--title", help="标题（默认取文章第一行 # ）")
    ap.add_argument("--author", default=os.environ.get("WECHAT_AUTHOR", ""), help="作者")
    ap.add_argument("--publish", action="store_true", help="建草稿后再提交发布（默认只进草稿箱）")
    ap.add_argument("--preview", help="只渲染 HTML 到这个文件，不调微信接口")
    args = ap.parse_args()

    article = Path(args.article)
    if not article.exists():
        print(f"文章不存在：{article}", file=sys.stderr)
        return 1

    images_dir = args.images_dir or str(article.parent / "images_good")

    # 预览：正文图用本地路径占位，不调接口
    if args.preview:
        preview_path = Path(args.preview)
        html, title, digest = build_content(article, images_dir, upload=None,
                                            preview_base=preview_path.parent)
        doc = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
               '<meta name="viewport" content="width=device-width,initial-scale=1">'
               f'<title>{title}</title></head>'
               '<body style="margin:0;padding:16px;background:#fff;">'
               + html + "</body></html>")
        preview_path.write_text(doc, encoding="utf-8")
        print(json.dumps({"ok": True, "stage": "preview", "preview": str(preview_path),
                          "title": title, "digest": digest}, ensure_ascii=False))
        return 0

    app_id = os.environ.get("WECHAT_APP_ID", "")
    app_secret = os.environ.get("WECHAT_APP_SECRET", "")
    if not app_id or not app_secret:
        print(json.dumps({"ok": False, "stage": "token", "error":
                          "缺少环境变量 WECHAT_APP_ID / WECHAT_APP_SECRET"}, ensure_ascii=False))
        return 1

    result = {"ok": False, "stage": "token", "media_id": "", "publish_id": "",
              "article_url": "", "title": args.title or "", "error": ""}
    wx = WeChat(app_id, app_secret)
    stage = "token"
    try:
        wx.get_token()

        stage = "cover"
        cover_path = find_cover(args.cover, images_dir, str(article.parent))
        data, mime, ext = prepare_image(cover_path, COVER_MAX_BYTES)
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        try:
            thumb = wx.upload_cover(tmp_path)
        finally:
            os.unlink(tmp_path)

        stage = "content"
        uploaded = {}

        def upload(src, md_dir=None):
            """图片上传器：本地路径 → 微信外链 URL，失败返回 None。"""
            path = src if os.path.isabs(src) else str(Path(md_dir or article.parent) / src)
            if not os.path.exists(path):
                return None
            if path in uploaded:
                return uploaded[path]
            try:
                data, mime, ext = prepare_image(path, BODY_MAX_BYTES)
                with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                    tmp.write(data)
                    tmp_path = tmp.name
                try:
                    url = wx.upload_body_image(tmp_path)
                finally:
                    os.unlink(tmp_path)
            except Exception:
                url = None
            uploaded[path] = url
            return url

        html, md_title, digest = build_content(article, images_dir, upload=upload)
        title = args.title or md_title
        result["title"] = title

        stage = "draft"
        title, title_cut = _truncate_bytes(title or md_title, 64)
        digest, digest_cut = _truncate_bytes(digest or md_title, 120)
        author, author_cut = _truncate_bytes(args.author, 8)  # 微信作者上限 8 字节
        if title_cut or digest_cut or author_cut:
            print(f"⚠️ 超过微信字节上限，已截断：标题{'(64B)' if title_cut else ''} "
                  f"摘要{'(120B)' if digest_cut else ''} 作者{'(16B)' if author_cut else ''}",
                  file=sys.stderr)
        result["title"] = title
        if len(html) > 20000:
            raise WxError("draft", -1, f"正文 {len(html)} 字符，超过微信上限 20000")
        media_id = wx.add_draft(title, author, digest, html, thumb)
        result["media_id"] = media_id
        result["stage"] = "done"
        result["ok"] = True

        if args.publish:
            stage = "publish"
            pid, url = wx.freepublish(media_id)
            result["publish_id"] = pid
            result["article_url"] = url
    except WxError as exc:
        result["stage"] = exc.stage
        result["error"] = str(exc)
        if exc.stage == "publish" and result["media_id"]:
            result["error"] += "（草稿已保存，去后台手动发即可）"
    except Exception as exc:
        result["stage"] = stage
        result["error"] = f"{type(exc).__name__}: {exc}"

    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
