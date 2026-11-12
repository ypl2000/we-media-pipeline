#!/usr/bin/env python3
"""
Fetch WeChat article content using Playwright.
Saves article as PDF, HTML, or screenshot with title-based filenames.
Supports topic-based organization: output_dir/topic/safe_title/...
Extracts image metadata (URLs, positions, surrounding text) for style learning.
"""

import sys
import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright
import time
import os
import re
import json


def sanitize_filename(title):
    """Convert title to safe filename."""
    safe = re.sub(r'[\\/*?:"<>|]', '', title)
    safe = re.sub(r'\s+', '_', safe)
    safe = re.sub(r'[^\w]', '', safe)
    return safe[:50]


def extract_image_metadata_from_page(page, raw_text):
    """
    Extract image URLs and their positions from the fully-rendered page.
    WeChat lazy-loads images via data-src attributes that only become
    populated after JS executes. We query them via evaluate() for reliability.
    """
    # Use page.evaluate to extract images directly from DOM
    # This avoids HTML parsing issues with inner_html
    image_data = page.evaluate("""
        () => {
            const jsContent = document.getElementById('js_content');
            if (!jsContent) return [];
            const imgs = jsContent.querySelectorAll('img');
            return Array.from(imgs).map((img, i) => {
                const src = img.dataset.src || img.dataset.original || img.src || '';
                return {
                    url: src,
                    index: i,
                    width: img.naturalWidth || img.width || 0,
                    height: img.naturalHeight || img.height || 0,
                    className: img.className || '',
                    dataType: img.dataset.type || '',
                    alt: img.alt || ''
                };
            }).filter(img => img.url && !img.url.startsWith('data:'));
        }
    """)

    # Build paragraph context from raw_text
    paragraphs = [p.strip() for p in raw_text.split('\n') if p.strip()]

    results = []
    for img in image_data:
        i = img['index']
        results.append({
            'url': img['url'],
            'index': i,
            'context_before': paragraphs[max(0, i * 2 - 1)] if paragraphs else "",
            'context_after': paragraphs[min(len(paragraphs) - 1, i * 2 + 1)] if paragraphs else "",
            'width': img.get('width', 0),
            'height': img.get('height', 0),
            'class': img.get('className', ''),
            'data_type': img.get('dataType', ''),
            'alt': img.get('alt', '')
        })

    return results


def fetch_article(url, output_dir, wait_time=5, topic=None):
    """
    Fetch a WeChat article and save with title-based filenames.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1280, 'height': 800},
            device_scale_factor=2,
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        page = context.new_page()

        try:
            try:
                page.goto(url, wait_until='domcontentloaded', timeout=30000)
            except:
                page.goto(url, wait_until='load', timeout=30000)

            try:
                page.wait_for_selector('#js_content', timeout=20000)
            except:
                pass

            time.sleep(wait_time)

            title = page.title()
            safe_title = sanitize_filename(title)

            if topic:
                target_dir = os.path.join(output_dir, topic, safe_title)
            else:
                target_dir = os.path.join(output_dir, safe_title)
            os.makedirs(target_dir, exist_ok=True)

            pdf_path = os.path.join(target_dir, f"{safe_title}.pdf")
            html_path = os.path.join(target_dir, f"{safe_title}.html")
            screenshot_path = os.path.join(target_dir, f"{safe_title}.png")
            images_json_path = os.path.join(target_dir, f"{safe_title}_images.json")

            try:
                content = page.inner_text('#js_content')
            except:
                content = "Content extraction failed"

            html_content = page.content()

            # Extract image metadata via page.evaluate (reliable DOM access)
            image_metadata = extract_image_metadata_from_page(page, content)

            page.pdf(
                path=pdf_path,
                format='A4',
                print_background=True,
                margin={'top': '20px', 'right': '20px', 'bottom': '20px', 'left': '20px'}
            )

            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html_content)

            page.screenshot(path=screenshot_path, full_page=True)

            with open(images_json_path, 'w', encoding='utf-8') as f:
                json.dump(image_metadata, f, ensure_ascii=False, indent=2)

            context.close()
            browser.close()

            return {
                'title': title,
                'safe_title': safe_title,
                'content': content,
                'pdf_path': pdf_path,
                'html_path': html_path,
                'screenshot_path': screenshot_path,
                'images_json_path': images_json_path,
                'image_metadata': image_metadata,
                'target_dir': target_dir,
                'topic': topic,
                'success': True
            }

        except Exception as e:
            context.close()
            browser.close()
            return {
                'title': '',
                'safe_title': '',
                'content': '',
                'success': False,
                'error': str(e)
            }


def main():
    parser = argparse.ArgumentParser(description='Fetch WeChat article with topic support')
    parser.add_argument('url', help='WeChat article URL')
    parser.add_argument('-o', '--output-dir', default=None,
                        help='Base output directory (default: {project}/reference)')
    parser.add_argument('-t', '--topic', default=None,
                        help='Topic folder name (e.g. AI创业). Creates topic subfolder.')
    parser.add_argument('-w', '--wait', type=int, default=5,
                        help='Wait time in seconds')
    args = parser.parse_args()

    if args.output_dir is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        skill_dir = os.path.dirname(script_dir)
        args.output_dir = os.path.join(skill_dir, '..', 'reference')
    else:
        output_path = Path(args.output_dir).resolve()
        if not (str(output_path).endswith('reference') or str(output_path).endswith('reference' + os.sep)):
            args.output_dir = os.path.join(args.output_dir, 'reference')

    os.makedirs(args.output_dir, exist_ok=True)

    result = fetch_article(args.url, args.output_dir, args.wait, args.topic)

    if result['success']:
        print(f"Title: {result['title']}")
        print(f"Safe filename: {result['safe_title']}")
        if result['topic']:
            print(f"Topic: {result['topic']}")
        print(f"\nContent preview (first 500 chars):\n{result['content'][:500]}...")
        print(f"\nImages found: {len(result['image_metadata'])}")
        for i, img in enumerate(result['image_metadata'][:5]):
            print(f"  [{i}] {img['url'][:80]}...")
            print(f"      before: {img['context_before'][:50]}...")
            print(f"      after: {img['context_after'][:50]}...")
        print(f"\nSaved to: {result['target_dir']}")
        print(f"  - {result['pdf_path']}")
        print(f"  - {result['html_path']}")
        print(f"  - {result['screenshot_path']}")
        print(f"  - {result['images_json_path']}")

        import json
        print(f"\n---RESULT_JSON---")
        print(json.dumps({
            'title': result['title'],
            'safe_title': result['safe_title'],
            'content': result['content'],
            'target_dir': result['target_dir'],
            'topic': result['topic'],
            'html_path': result['html_path'],
            'images_json_path': result['images_json_path'],
            'image_count': len(result['image_metadata'])
        }, ensure_ascii=False))
    else:
        print(f"Error: {result.get('error', 'Unknown error')}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
