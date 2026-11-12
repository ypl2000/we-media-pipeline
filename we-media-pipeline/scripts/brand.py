# -*- coding: utf-8 -*-
"""品牌标识（文字 / logo / 图文）的读取与绘制。

品牌名、logo 和呈现方式来自仓库配置的 ``brand`` 段，脚本里不写死：

    "brand": {
      "name": "你的品牌名",
      "logo_image": "we-video-generator/assets/logos/example_logo.png",
      "mode": "text"
    }

读取顺序（与仓库配置规矩一致）：优先走 ``shared/config_loader.py``，保留
「环境变量 > config.json」优先级；loader 不可用时才回退直读 config.json。
字段级环境变量：``BRAND_NAME`` / ``BRAND_LOGO_IMAGE`` / ``BRAND_MODE``；
整段覆盖用 ``BRAND``（值是 JSON 对象字符串）。

- ``name``       品牌名（卡片左上角、PPT 页脚、视频水印）
- ``logo_image`` 相对仓库根的图片路径；留空或文件不存在时，``logo``/``both``
                自动退回 ``text``
- ``mode``       ``text`` 只画文字 | ``logo`` 只贴图 | ``both`` 图 + 字

依赖：标准库 + Pillow（仓库已在用）。没装 Pillow 时 import 阶段给出可读错误。

命令行预览（1080x240 白底，肉眼确认品牌效果）：:

    python brand.py --preview %TEMP%\\brand.png
    python brand.py --preview %TEMP%\\brand.png --mode logo --logo we-video-generator/assets/logos/ai_not_cool_logo.png
    python brand.py --preview %TEMP%\\brand.png --mode both --name 测试品牌
"""

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:  # pragma: no cover - 只在本机缺依赖时触发
    raise ImportError(
        "brand.py 需要 Pillow 才能绘制品牌标识，请先安装：python -m pip install Pillow"
    ) from exc

__all__ = ["DEFAULT_BRAND", "VALID_MODES", "load_brand", "draw_brand"]

# 默认值刻意留空：没配置时不画任何品牌，避免把某个品牌写死在代码里。
DEFAULT_BRAND = {
    "name": "",
    "logo_image": "",
    "mode": "text",
}

VALID_MODES = ("text", "logo", "both")

# 中文标题字体：优先黑体，找不到再退到系统里常见的中文字体。
_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/System/Library/Fonts/PingFang.ttc",
)

_font_cache = {}


def _find_project_root():
    """从本文件所在位置向上找含 config.json 的目录（即仓库根）。"""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "config.json").is_file():
            return parent
    # 兜底：we-media-pipeline/scripts/brand.py -> 仓库根
    return here.parents[2]


def _load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        # 配置缺失或损坏都不阻断出图，交给默认值兜底。
        return {}


_MISSING = object()


def _load_brand_from_config_loader():
    """优先用 shared/config_loader.py 读品牌配置。

    这样能沿用仓库统一的优先级链：环境变量 > 项目 config.json > 默认值。
    loader 对 ``brand`` 段的环境变量是 ``BRAND``（JSON 对象字符串），
    对每个字段则是 ``BRAND_NAME`` / ``BRAND_LOGO_IMAGE`` / ``BRAND_MODE``。

    Returns:
        dict | None: 读到的品牌配置；loader 不可用或完全没配置时返回 None，
        由调用方回退到直读 config.json。
    """
    try:
        shared = Path(__file__).resolve().parents[2] / "shared"
        if str(shared) not in sys.path:
            sys.path.append(str(shared))
        from config_loader import get_config_value
    except Exception:
        return None

    if os.environ.get("BRAND") is not None:
        # 环境变量只能是字符串，允许用 JSON 覆盖整个 brand 段
        section = get_config_value("brand")
        try:
            section = json.loads(section) if isinstance(section, str) else None
        except ValueError:
            print("brand.py 警告：环境变量 BRAND 不是合法 JSON，已忽略", file=sys.stderr)
            section = None
        if not isinstance(section, dict):
            return None
        # 整段覆盖优先，不再用 config.json 的字段把它盖回去
        return section

    section = get_config_value("brand")
    if not isinstance(section, dict):
        section = {}

    touched = bool(section)
    for field in ("name", "logo_image", "mode"):
        value = get_config_value("brand.%s" % field, _MISSING)
        if value is not _MISSING:
            section[field] = value
            touched = True

    return section if touched else None


def _resolve_logo(raw, root):
    """把 logo_image 解析成绝对路径；找不到返回空串。

    配置里写相对仓库根的路径；命令行传相对路径时也允许相对当前目录。
    """
    raw = (raw or "").strip()
    if not raw:
        return ""
    expanded = os.path.expanduser(os.path.expandvars(raw))
    p = Path(expanded)
    if p.is_absolute():
        candidates = [p]
    else:
        candidates = [Path(root) / p, Path.cwd() / p]
    for cand in candidates:
        try:
            if cand.is_file():
                return str(cand.resolve())
        except OSError:
            continue
    return ""


def _normalise_mode(value):
    mode = str(value or "").strip().lower()
    return mode if mode in VALID_MODES else DEFAULT_BRAND["mode"]


def load_brand(project_root=None):
    """读取品牌配置（优先 config_loader，回退直读 config.json）。

    Args:
        project_root: 仓库根；省略时从本文件位置向上找 config.json，并优先
            交给 shared/config_loader.py 解析（环境变量可覆盖）。显式传入
            路径时直接读该目录下的 config.json。

    Returns:
        dict: ``{"name": str, "logo_image": str, "mode": str}``

        - 缺字段用默认值（name 空、logo_image 空、mode text）；
        - config.json 不存在或损坏也不报错；
        - ``logo_image`` 返回绝对路径；留空/文件不存在时为空串；
        - ``mode`` 是**生效值**：logo/both 但 logo 不可用时已退回 text。
    """
    if project_root is None:
        root = _find_project_root()
        section = _load_brand_from_config_loader()
    else:
        root = Path(project_root).resolve()
        section = None

    if not isinstance(section, dict):
        # loader 不可用、或调用方指定了别的仓库根：直读该根下的 config.json
        config = _load_json(root / "config.json")
        section = config.get("brand") if isinstance(config, dict) else None
        if not isinstance(section, dict):
            section = {}

    name = section.get("name", DEFAULT_BRAND["name"])
    name = "" if name is None else str(name).strip()

    mode = _normalise_mode(section.get("mode", DEFAULT_BRAND["mode"]))

    logo_raw = section.get("logo_image", DEFAULT_BRAND["logo_image"])
    logo_path = _resolve_logo(logo_raw, root)
    if mode in ("logo", "both") and not logo_path:
        # 留空或路径失效：不画白块，退回文字模式。
        mode = "text"

    return {"name": name, "logo_image": logo_path, "mode": mode}


def _font(size):
    """取一个能画中文的字体；系统里一个都没有时退回 Pillow 默认字体。"""
    size = max(1, int(round(size)))
    cached = _font_cache.get(size)
    if cached is not None:
        return cached
    for path in _FONT_CANDIDATES:
        try:
            if os.path.isfile(path):
                font = ImageFont.truetype(path, size)
                _font_cache[size] = font
                return font
        except OSError:
            continue
    print(
        "brand.py 警告：没找到中文字体（msyhbd/simhei/Noto/PingFang），"
        "中文可能显示为方块",
        file=sys.stderr,
    )
    font = ImageFont.load_default()
    _font_cache[size] = font
    return font


def _trim_logo(im):
    """裁掉 logo 四周的透明或纯白留白，让 44px 高度落在图形本体上。"""
    if "A" in im.getbands():
        alpha = im.getchannel("A")
        if alpha.getextrema()[0] < 255:
            bbox = alpha.getbbox()
            if bbox:
                return im.crop(bbox)
            return im
    # 不透明图（常见是白底 banner）：按亮度阈值找内容边界。
    mask = im.convert("L").point(lambda v: 0 if v >= 245 else 255)
    bbox = mask.getbbox()
    if bbox:
        return im.crop(bbox)
    return im


def _load_logo(logo_path, height):
    """读入 logo 并等比缩放到指定高度；失败返回 None。"""
    if not logo_path:
        return None
    try:
        with Image.open(logo_path) as src:
            im = src.convert("RGBA")
    except (OSError, ValueError):
        return None
    im = _trim_logo(im)
    w, h = im.size
    if not w or not h:
        return None
    target_h = max(1, int(round(height)))
    target_w = max(1, int(round(w * target_h / float(h))))
    return im.resize((target_w, target_h), Image.LANCZOS)


def _draw_target(draw):
    """取 ImageDraw 底下的真实图片（贴图用）；取不到返回 None。"""
    return getattr(draw, "_image", None) or getattr(draw, "im", None)


def draw_brand(draw, brand, x=96, y=115, dark=False,
               accent=(191, 69, 32), ink=(45, 49, 66), light=(242, 243, 245),
               scale=1.0):
    """在给定的 ImageDraw 上画品牌标识。

    布局与卡片原稿一致：文字 40px、左对齐、垂直居中于 y，
    红条 10x24 位于 x-24；logo 高度 44px，左边缘同样对齐 x-24。

    Args:
        draw: PIL ImageDraw（其底层图片需可写，贴 logo 时用于 alpha 合成）
        brand: load_brand() 的返回值，或同结构的 dict
        x, y: 品牌基线左端 / 垂直中心（逻辑像素）
        dark: 深色背景下文字用浅色
        accent, ink, light: 红条 / 浅底文字 / 深底文字颜色
        scale: 超采样倍率（卡片画布是 2x，传 2 即按原生分辨率绘制）
                  不影响外部坐标系，只在内部换算。

    Returns:
        int: 画出的宽度（逻辑像素）；什么都没画返回 0。
    """
    if draw is None:
        return 0

    brand = brand or {}
    name = str(brand.get("name") or "").strip()
    mode = _normalise_mode(brand.get("mode", DEFAULT_BRAND["mode"]))
    logo_path = brand.get("logo_image") or ""
    if logo_path and not os.path.isabs(str(logo_path)):
        logo_path = _resolve_logo(str(logo_path), _find_project_root())
    if mode in ("logo", "both") and not (logo_path and os.path.isfile(str(logo_path))):
        mode = "text"

    s = max(0.01, float(scale))
    fx, fy = x * s, y * s
    bar_w, bar_h = 10 * s, 24 * s
    gap = 16 * s
    font = _font(40 * s)
    text_color = light if dark else ink

    # ---- 只画文字 ----
    if mode == "text":
        if not name:
            return 0
        draw.rectangle(
            [fx - 24 * s, fy - bar_h / 2.0,
             fx - 24 * s + bar_w, fy + bar_h / 2.0],
            fill=accent,
        )
        draw.text((fx, fy), name, font=font, fill=text_color, anchor="lm")
        return int(round(24 * s + font.getlength(name)))

    # ---- 贴 logo（logo / both）----
    logo = _load_logo(logo_path, 44 * s)
    if logo is None:  # 理论上前面已退回，防御性处理
        if not name:
            return 0
        draw.text((fx, fy), name, font=font, fill=text_color, anchor="lm")
        return int(round(font.getlength(name)))

    target = _draw_target(draw)
    left = int(round(fx - 24 * s))
    top = int(round(fy - logo.height / 2.0))
    if target is not None:
        target.paste(logo, (left, top), logo)
    width = logo.width

    if mode == "both" and name:
        text_x = left + logo.width + gap
        draw.text((text_x, fy), name, font=font, fill=text_color, anchor="lm")
        width = int(round(width + gap + font.getlength(name)))

    return int(round(width))


# --------------------------------------------------------------------------- CLI
def _build_preview_brand(args):
    brand = load_brand()
    if args.mode:
        brand["mode"] = _normalise_mode(args.mode)
    if args.name is not None:
        brand["name"] = args.name.strip()
    if args.logo is not None:
        logo = _resolve_logo(args.logo, _find_project_root())
        if args.logo.strip() and not logo:
            print(f"警告：找不到 logo 文件 {args.logo!r}，已退回文字模式", file=sys.stderr)
        brand["logo_image"] = logo
    if brand["mode"] in ("logo", "both") and not brand.get("logo_image"):
        brand["mode"] = "text"
    return brand


def _preview(out_path, brand, dark=False):
    w, h = 1080, 240
    bg = (28, 30, 38) if dark else (255, 255, 255)
    im = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(im)
    width = draw_brand(draw, brand, x=96, y=h // 2, dark=dark)
    out = Path(out_path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(str(out))
    return im, width


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="品牌标识预览（1080x240）",
        epilog=(
            "环境变量覆盖（优先级高于 config.json）：BRAND_NAME / "
            "BRAND_LOGO_IMAGE / BRAND_MODE；整段覆盖用 BRAND（JSON 对象字符串）。"
        ),
    )
    parser.add_argument("--preview", required=True, metavar="OUT.png",
                        help="预览图输出路径")
    parser.add_argument("--mode", choices=VALID_MODES, help="覆盖 config 的 mode")
    parser.add_argument("--name", help="覆盖 config 的品牌名")
    parser.add_argument("--logo", help="覆盖 config 的 logo 图片路径")
    parser.add_argument("--dark", action="store_true", help="深色背景预览")
    args = parser.parse_args(argv)

    brand = _build_preview_brand(args)
    im, width = _preview(args.preview, brand, dark=args.dark)
    print(f"预览已保存: {Path(args.preview).expanduser().resolve()}")
    print(f"尺寸: {im.width}x{im.height}  模式: {brand['mode']}  名称: {brand['name']!r}")
    if brand["logo_image"]:
        print(f"logo: {brand['logo_image']}")
    print(f"品牌宽度: {width}px（画布高 240，品牌垂直居中）")
    if width == 0:
        print("未绘制任何内容：name 为空且没有可用 logo", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
