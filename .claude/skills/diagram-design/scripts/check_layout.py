#!/usr/bin/env python3
"""Check an SVG-in-HTML diagram: text bboxes inside viewBox, no text-on-text overlap.

    python check_layout.py diagram.html            # upstream floor (Han >= 12px)
    python check_layout.py diagram.html --min-han 40   # WeChat body-image floor
"""
import sys, json, pathlib, argparse
from playwright.sync_api import sync_playwright

JS = r"""
() => {
  const svg = document.querySelector('svg');
  const vb = svg.viewBox.baseVal;
  const items = [];
  for (const t of svg.querySelectorAll('text')) {
    const b = t.getBBox();
    const cs = getComputedStyle(t);
    items.push({
      text: t.textContent.trim(),
      x: b.x, y: b.y, w: b.width, h: b.height,
      size: cs.fontSize, weight: cs.fontWeight, family: cs.fontFamily,
      anchor: cs.textAnchor
    });
  }
  return {vb: {w: vb.width, h: vb.height}, items};
}
"""

def overlap(a, b):
    return not (a['x'] + a['w'] <= b['x'] or b['x'] + b['w'] <= a['x'] or
                a['y'] + a['h'] <= b['y'] or b['y'] + b['h'] <= a['y'])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='+')
    ap.add_argument('--min-han', type=float, default=12.0,
                    help='minimum font size for Han characters (40 for WeChat body images)')
    args = ap.parse_args()
    bad = 0
    for f in args.files:
        file_bad = 0
        p = pathlib.Path(f).resolve()
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            page = b.new_page()
            page.goto(p.as_uri(), wait_until='load')
            page.evaluate("document.fonts.ready")
            d = page.evaluate(JS)
            b.close()
        print(f"== {p.name}  viewBox {d['vb']['w']}x{d['vb']['h']}  texts={len(d['items'])}")
        for it in d['items']:
            if it['x'] < -1 or it['y'] < -1 or it['x'] + it['w'] > d['vb']['w'] + 1 or it['y'] + it['h'] > d['vb']['h'] + 1:
                file_bad += 1; print(f"  OUT OF FRAME: {it['text']!r} at {it['x']:.0f},{it['y']:.0f} {it['w']:.0f}x{it['h']:.0f} size={it['size']}")

            fs = float(it['size'].replace('px', ''))
            if any('一' <= c <= '鿿' for c in it['text']) and fs < args.min_han:
                file_bad += 1; print(f"  TOO SMALL FOR HAN ({fs}px < {args.min_han}px): {it['text']!r}")

        for i in range(len(d['items'])):
            for j in range(i + 1, len(d['items'])):
                a, c = d['items'][i], d['items'][j]
                if overlap(a, c):
                    file_bad += 1; print(f"  OVERLAP: {a['text']!r} <> {c['text']!r}")
        bad += file_bad
        print(f"  {'clean' if file_bad == 0 else f'{file_bad} ISSUES'}")
    return 1 if bad else 0

if __name__ == '__main__':
    raise SystemExit(main())
