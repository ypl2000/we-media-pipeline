#!/usr/bin/env python3
"""
Aggregate style findings across every article saved in a topic.

Per-article analysis produces single-value findings (段落数/配图数/强调色) that
only describe one article. This re-analyzes the whole corpus and rewrites those
volatile bullets as corpus statistics, so style.md reflects the topic rather
than the last article fetched.

Usage:
    python aggregate_style.py "新闻资讯" [-o reference]
"""

import argparse
import importlib.util
import io
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    'aus', os.path.join(SCRIPT_DIR, 'analyze_and_update_style.py'))
aus = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aus)

RGB = re.compile(r'rgb\((\d+),\s*(\d+),\s*(\d+)\)')

# 编译/编辑稿特征。只用无歧义的短语：「转载」在微信页底部是 UI 噪音，不能用。
COMPILED_MARKERS = ('全文编译', '本文编译', '编译自', '以下为编译',
                    '以下带来全文编译', '译文', '翻译自', '简译')


def excluded_titles(topic_dir):

    """手工排除名单：<topic_dir>/exclude.txt，一行一个文章目录名。"""

    path = os.path.join(topic_dir, 'exclude.txt')

    if not os.path.exists(path):

        return set()

    with io.open(path, 'r', encoding='utf-8') as f:

        return {line.strip() for line in f if line.strip() and not line.startswith('#')}


def load_articles(topic_dir):
    """Return ({title: findings}, skipped) for every article in the topic dir."""
    excluded = excluded_titles(topic_dir)
    skipped = []
    found = {}
    for name in sorted(os.listdir(topic_dir)):
        art_dir = os.path.join(topic_dir, name)
        if not os.path.isdir(art_dir):
            continue
        html = os.path.join(art_dir, name + '.html')
        if not os.path.exists(html):
            continue
        with io.open(html, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        text = re.sub(r'<[^>]+>', ' ', aus.strip_html(content))
        if len(text.strip()) < 500:
            continue  # 非文章页（如公众号平台页），不纳入语料统计
        if name in excluded:
            skipped.append((name, '手工排除'))
            continue
        hit = next((m for m in COMPILED_MARKERS if m in text), None)
        if hit:
            skipped.append((name, '编译稿（特征词：' + hit + '）'))
            continue
        images = os.path.join(art_dir, name + '_images.json')
        found[name] = aus.analyze_style(content, name, images if os.path.exists(images) else None)

    return found, skipped


def first_number(bullets, pattern):
    for b in bullets:
        m = re.search(pattern, b)
        if m:
            return int(m.group(1))
    return None


def collect(all_findings):
    """Aggregate per-article findings into corpus-level statistics."""
    n = len(all_findings)
    titles, bodies, images = [], [], []
    color_count, key_color_count = {}, {}
    img_type_count = {}

    for findings in all_findings.values():
        t = first_number(findings.get('标题', []), r'标题长度约(\d+)字')
        b = first_number(findings.get('结构', []), r'全文约(\d+)个段落')
        i = first_number(findings.get('配图位置', []), r'配图约(\d+)张')
        if t is not None:
            titles.append(t)
        if b is not None:
            bodies.append(b)
        if i is not None:
            images.append(i)

        for bullet in findings.get('排版格式', []):
            for m in RGB.finditer(bullet):
                color = m.group(0)
                if bullet.startswith('重点色'):
                    key_color_count[color] = key_color_count.get(color, 0) + 1
                else:
                    color_count[color] = color_count.get(color, 0) + 1

        for bullet in findings.get('配图位置', []):
            if bullet.startswith('配图以'):
                kind = '技术截图/界面图' if '技术截图' in bullet else '场景/人物/素材图'
                img_type_count[kind] = img_type_count.get(kind, 0) + 1

    agg = {}
    if titles:
        avg = round(sum(titles) / len(titles))
        agg['标题'] = [f'标题长度约{avg}字（语料均值，{n}篇）']
    if bodies:
        avg = round(sum(bodies) / len(bodies))
        agg['结构'] = [f'全文约{avg}个段落（语料均值，{n}篇）']
    if images:
        avg = round(sum(images) / len(images))
        agg['配图位置'] = [f'配图约{avg}张（语料均值，{n}篇）']
        if img_type_count:
            detail = '，'.join(f'{k} {v}篇' for k, v in
                               sorted(img_type_count.items(), key=lambda kv: -kv[1]))
            agg['配图位置'].append(f'配图类型：{detail}')

    fmt = []
    if color_count:
        top, cnt = max(color_count.items(), key=lambda kv: kv[1])
        name = aus.named_color(top, {})
        if len(color_count) == 1:
            fmt.append(f'使用单一强调色：{name}（语料 {cnt}/{n} 篇）')
        else:
            fmt.append(f'使用{len(color_count)}种强调色（语料 {n} 篇，最常见 {name} {cnt} 篇）')
    if key_color_count:
        top, cnt = max(key_color_count.items(), key=lambda kv: kv[1])
        name = aus.named_color(top, {})
        fmt.append(f'重点色{name}用于小标签/章节编号（语料 {cnt}/{n} 篇）')
    if fmt:
        agg['排版格式'] = fmt

    return agg


def main():
    parser = argparse.ArgumentParser(description='Aggregate style across a topic corpus')
    parser.add_argument('topic', help='Topic name')
    parser.add_argument('--output-dir', '-o', dest='output_dir', default=None)
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.join(os.path.dirname(script_dir), '..')
    base = args.output_dir or os.path.join(project_root, 'reference')
    base = os.path.abspath(base)
    if not base.endswith('reference'):
        base = os.path.join(base, 'reference')
    topic_dir = os.path.join(base, args.topic)

    if not os.path.isdir(topic_dir):
        print('No such topic dir:', topic_dir, file=sys.stderr)
        sys.exit(1)

    all_findings, skipped = load_articles(topic_dir)
    if not all_findings:
        print('No articles found in', topic_dir, file=sys.stderr)
        sys.exit(1)

    for name, reason in skipped:
        print(f'Skipped: {name}  ({reason})')

    agg = collect(all_findings)
    aus.update_style_md(topic_dir, agg)

    print(f'Aggregated {len(all_findings)} articles in {args.topic}:')
    for section, points in agg.items():
        for p in points:
            print(f'  - [{section}] {p}')
    print('Updated:', os.path.join(topic_dir, 'style.md'))


if __name__ == '__main__':
    main()
