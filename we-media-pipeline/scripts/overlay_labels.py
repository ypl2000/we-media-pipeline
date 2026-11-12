"""Overlay Chinese labels onto an illustration that contains no text.

The image model draws the scene only (it can't be trusted to spell Chinese
correctly); this script adds the hand-written annotations afterwards, so every
character is exactly what the caller asked for.

Usage:
  python overlay_labels.py --image xiaohei_01.png --labels "AI短剧,爽点,工业化" --out xiaohei_01_lab.png

Labels are placed in the emptiest parts of the picture, in KaiTi (closest to
the hand-drawn look of the style) with an orange marker underline.
"""
import argparse
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\simkai.ttf",   # 楷体, closest to the hand-drawn style
    r"C:\Windows\Fonts\simfang.ttf",
    r"C:\Windows\Fonts\msyh.ttc",
]
ORANGE = (230, 98, 42)
BLACK = (25, 25, 25)
BLUE = (35, 90, 170)
RED = (200, 45, 45)
WHITE = (250, 250, 250)
COLORS = {"black": BLACK, "orange": ORANGE, "blue": BLUE, "red": RED, "white": WHITE}

GRID_W, GRID_H = 8, 4      # candidate anchor columns / rows


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise SystemExit("no CJK font found")


def busy_map(img: Image.Image, cols: int = 32, rows: int = 18):
    """How much detail each part of the picture has. 0 = flat, safe for text."""
    edges = img.convert("L").filter(ImageFilter.FIND_EDGES)
    small = edges.resize((cols, rows), Image.BILINEAR)
    return list(small.get_flattened_data())


def area_mean(values, cols, rows, box, w, h):
    """Average value over the cells a pixel box covers."""
    x0, y0, x1, y1 = box
    cx0 = max(0, int(x0 / w * cols))
    cx1 = min(cols - 1, int(x1 / w * cols))
    cy0 = max(0, int(y0 / h * rows))
    cy1 = min(rows - 1, int(y1 / h * rows))
    vals = [values[cy * cols + cx] for cy in range(cy0, cy1 + 1) for cx in range(cx0, cx1 + 1)]
    return sum(vals) / len(vals) if vals else 0


def overlaps(box, placed, pad=30):
    for other in placed:
        if (box[0] - pad < other[2] and box[2] + pad > other[0]
                and box[1] - pad < other[3] and box[3] + pad > other[1]):
            return True
    return False


def underline(draw, box, h, rng):
    """A wobbly orange marker line just under the text."""
    x0, y0, x1, y1 = box
    y = y1 + max(2, int(h * 0.006))
    steps = 6
    for i in range(steps):
        ax = x0 + (x1 - x0) * i / steps
        bx = x0 + (x1 - x0) * (i + 1) / steps
        draw.line([(ax, y + rng.uniform(-1.5, 1.5)), (bx, y + rng.uniform(-1.5, 1.5))],
                  fill=ORANGE, width=max(2, int(h * 0.004)))


def overlay(image_path, labels, out_path, seed=0, color="black") -> str:
    """Draw the labels onto image_path and save the result to out_path.

    Labels land on the flattest part of the picture and get a backing plate in
    whatever colour contrasts with that spot, so they stay readable on a white
    page and on a navy blueprint alike.
    """
    rng = random.Random(seed)
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    labels = [s.strip() for s in labels.split(",") if s.strip()]

    font = load_font(max(20, int(h * 0.078)))
    draw = ImageDraw.Draw(img)
    grey = img.convert("L")
    grey_small = grey.resize((32, 18), Image.BILINEAR)
    grey_cells = list(grey_small.get_flattened_data())
    busy = busy_map(img)
    cols, rows = 32, 18
    plate_alpha = 225

    placed = []
    for i, label in enumerate(labels):
        text_w = draw.textlength(label, font=font)
        best, best_score = None, None
        for row in range(GRID_H):
            for col in range(GRID_W):
                # anchor grid of possible positions, kept clear of the edges
                ax = (col + 0.5) / GRID_W * w
                ay = (row + 0.5) / GRID_H * h
                x = min(max(ax - text_w / 2, int(w * 0.02)), int(w * 0.97) - text_w)
                y = min(max(ay - h * 0.04, int(h * 0.02)), int(h * 0.88))
                box = (x, y, x + text_w, y + font.size)
                if overlaps(box, placed):
                    continue
                # spread the labels out: penalise a row that already has one
                same_row = sum(1 for b in placed
                               if abs((b[1] + b[3]) / 2 - (box[1] + box[3]) / 2) < h * 0.12)
                # prefer flat areas (few edges) over busy ones
                score = -area_mean(busy, cols, rows, box, w, h) - row * 2 - 40 * same_row
                if best_score is None or score > best_score:
                    best, best_score = (box, x, y), score
        if best is None:  # no free anchor left — park it at the bottom
            x = int(w * 0.03) + (i * int(text_w * 0.9)) % int(w * 0.6)
            y = int(h * 0.9)
            best = ((x, y, x + text_w, y + font.size), x, y)
        box, x, y = best

        # dark background -> white text on a dark plate, and vice versa
        brightness = area_mean(grey_cells, cols, rows, box, w, h)
        dark_bg = brightness < 128
        text_color = COLORS["white"] if dark_bg else COLORS.get(color, BLACK)
        plate = (0, 0, 0) if dark_bg else (255, 255, 255)

        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).rounded_rectangle(
            [box[0] - 6, box[1] - 3, box[2] + 6, box[3] + 3],
            radius=max(4, font.size // 6), fill=plate + (plate_alpha,))
        img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")
        draw = ImageDraw.Draw(img)
        draw.text((x, y), label, font=font, fill=text_color)
        underline(draw, box, h, rng)
        placed.append(box)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return str(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--labels", required=True, help="comma separated Chinese labels")
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--color", default="black", choices=sorted(COLORS))
    args = ap.parse_args()
    print(overlay(args.image, args.labels, args.out, args.seed, args.color))


if __name__ == "__main__":
    main()
