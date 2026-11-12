#!/usr/bin/env python3
"""
通用文章抓取脚本，支持多种网站。
Supported sites: 微信公众号、知乎、36氪、虎嗅、简书、掘金、CSDN等
"""

import sys
import argparse
from playwright.sync_api import sync_playwright
import time
import os
import re
from pathlib import Path
from urllib.parse import urlparse


def sanitize_filename(title):
    """Convert title to safe filename."""
    safe = re.sub(r'[\\/*?:"<>|]', '', title)
    safe = re.sub(r'\s+', '_', safe)
    safe = re.sub(r'[^\w]', '', safe)
    return safe[:50]


# 不同网站的内容选择器配置
SITE_CONFIGS = {
    # 微信公众号
    'mp.weixin.qq.com': {
        'content_selector': '#js_content',
        'title_selector': None,  # 使用 page.title()
        'wait_selector': '#js_content',
    },
    # 知乎文章
    'zhuanlan.zhihu.com': {
        'content_selector': '.Post-RichText, .RichText, article',
        'title_selector': 'h1.Post-Title, h1.QuestionHeader-title',
        'wait_selector': '.Post-RichText, .RichText',
    },
    # 36氪
    '36kr.com': {
        'content_selector': '.article-content, .kr-article-content, .content-body',
        'title_selector': '.article-title, .kr-article-title',
        'wait_selector': '.article-content',
    },
    # 虎嗅
    'huxiu.com': {
        'content_selector': '.article-content, .t-huxiu-article-content, .article-detail-content',
        'title_selector': '.article-title, h1.t-huxiu-article-title',
        'wait_selector': '.article-content',
    },
    # 简书
    'jianshu.com': {
        'content_selector': '.article-content, .show-content, .note-text',
        'title_selector': 'h1.title, .article-title',
        'wait_selector': '.article-content',
    },
    # 掘金
    'juejin.cn': {
        'content_selector': '.article-content, .entry-content, .markdown-body',
        'title_selector': 'h1.article-title, h1',
        'wait_selector': '.article-content',
    },
    # CSDN
    'blog.csdn.net': {
        'content_selector': '#content_views, .article-content, .blog-content',
        'title_selector': 'h1.article-title, .article-header-title',
        'wait_selector': '#content_views',
    },
    # 微信公众号收藏（备用）
    'mp.weixin.qq.com': {
        'content_selector': '#js_content, .rich_media_content',
        'title_selector': None,
        'wait_selector': '#js_content',
    },
    # 少数派
    'sspai.com': {
        'content_selector': '.article-content, .markdown-body, .article-body',
        'title_selector': 'h1.article-title',
        'wait_selector': '.article-content',
    },
    # 腾讯云社区
    'cloud.tencent.com': {
        'content_selector': '.article-content, .markdown-body, .content-detail',
        'title_selector': 'h1.article-title',
        'wait_selector': '.article-content',
    },
    # 阿里云社区
    'aliyun.com': {
        'content_selector': '.article-content, .content-body, .detail-content',
        'title_selector': 'h1.title',
        'wait_selector': '.article-content',
    },
    # 思否
    'segmentfault.com': {
        'content_selector': '.article-content, .markdown-body, .article-detail',
        'title_selector': 'h1.title',
        'wait_selector': '.article-content',
    },
    # 博客园
    'cnblogs.com': {
        'content_selector': '#cnblogs_post_body, .article-content, .post-body',
        'title_selector': '#cb_post_title_url, h1.postTitle',
        'wait_selector': '#cnblogs_post_body',
    },
    # 知乎问答
    'www.zhihu.com': {
        'content_selector': '.RichContent, .QuestionAnswer-content, .List-item',
        'title_selector': 'h1.QuestionHeader-title',
        'wait_selector': '.RichContent',
    },
}


def get_site_config(url):
    """根据URL获取网站配置"""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()

    # 精确匹配
    if domain in SITE_CONFIGS:
        return SITE_CONFIGS[domain]

    # 模糊匹配（包含域名片段）
    for site_domain, config in SITE_CONFIGS.items():
        if site_domain in domain:
            return config

    # 默认配置（通用网页）
    return {
        'content_selector': 'article, main, .content, .article-content, .post-content, .entry-content, [role="main"]',
        'title_selector': 'h1, .title, .article-title, .post-title',
        'wait_selector': 'article, main',
    }


def fetch_article(url, output_dir, wait_time=5):
    """
    Fetch article from any supported website.

    Args:
        url: Article URL
        output_dir: Output directory
        wait_time: Seconds to wait for page load

    Returns:
        dict: Contains title, content, and output paths
    """
    config = get_site_config(url)
    print(f"[INFO] 检测到网站配置: {urlparse(url).netloc}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1280, 'height': 800},
            device_scale_factor=2,
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = context.new_page()

        try:
            # Navigate to article
            try:
                page.goto(url, wait_until='domcontentloaded', timeout=30000)
            except:
                try:
                    page.goto(url, wait_until='load', timeout=30000)
                except:
                    page.goto(url, timeout=30000)

            # Wait for content selector
            wait_selector = config.get('wait_selector')
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=10000)
                except:
                    pass

            time.sleep(wait_time)

            # Get title
            title_selector = config.get('title_selector')
            if title_selector:
                try:
                    title = page.inner_text(title_selector).strip()
                except:
                    title = page.title()
            else:
                title = page.title()

            if not title or title == '':
                title = page.title()

            safe_title = sanitize_filename(title)

            # Create output paths
            pdf_path = os.path.join(output_dir, f"{safe_title}.pdf")
            html_path = os.path.join(output_dir, f"{safe_title}.html")
            screenshot_path = os.path.join(output_dir, f"{safe_title}.png")

            # Extract content
            content_selector = config.get('content_selector')
            content = None

            if content_selector:
                # 尝试多个选择器
                selectors = content_selector.split(', ')
                for sel in selectors:
                    try:
                        sel = sel.strip()
                        elements = page.query_selector_all(sel)
                        if elements:
                            content = '\n\n'.join([el.inner_text() for el in elements])
                            if content and len(content) > 100:
                                break
                    except:
                        pass

            if not content or len(content) < 100:
                # 回退：尝试通用选择器
                try:
                    content = page.inner_text('article')
                except:
                    try:
                        content = page.inner_text('main')
                    except:
                        try:
                            content = page.inner_text('.content')
                        except:
                            content = page.inner_text('body')
                            # 清理明显的导航和脚本内容
                            content = re.sub(r'(登录|注册|首页|导航|菜单|相关推荐|热门文章|关注|订阅).{0,50}', '', content)

            if not content or len(content) < 50:
                content = f"[无法提取正文内容]\n\n请访问原始链接查看完整内容：{url}"

            # 清理内容（移除多余空白）
            content = re.sub(r'\n{3,}', '\n\n', content)
            content = content.strip()

            # Save as PDF
            try:
                page.pdf(
                    path=pdf_path,
                    format='A4',
                    print_background=True,
                    margin={'top': '20px', 'right': '20px', 'bottom': '20px', 'left': '20px'}
                )
            except Exception as e:
                print(f"[WARN] PDF 保存失败: {e}")
                pdf_path = None

            # Save as HTML
            try:
                html_content = page.content()
                with open(html_path, 'w', encoding='utf-8') as f:
                    f.write(html_content)
            except Exception as e:
                print(f"[WARN] HTML 保存失败: {e}")
                html_path = None

            # Save screenshot
            try:
                page.screenshot(path=screenshot_path, full_page=True)
            except Exception as e:
                print(f"[WARN] 截图保存失败: {e}")
                screenshot_path = None

            context.close()
            browser.close()

            print(f"[INFO] 标题: {title}")
            print(f"[INFO] 内容长度: {len(content)} 字符")

            return {
                'title': title,
                'safe_title': safe_title,
                'content': content,
                'pdf_path': pdf_path,
                'html_path': html_path,
                'screenshot_path': screenshot_path,
                'success': True,
                'url': url,
                'domain': urlparse(url).netloc
            }

        except Exception as e:
            context.close()
            browser.close()
            return {
                'title': '',
                'safe_title': '',
                'content': '',
                'success': False,
                'error': str(e),
                'url': url
            }


def main():
    parser = argparse.ArgumentParser(description='通用文章抓取脚本，支持微信公众号、知乎、36氪、虎嗅等多种网站')
    parser.add_argument('url', help='文章URL')
    parser.add_argument('-o', '--output-dir', default=None,
                        help='输出目录（默认：桌面输出根目录/语料）')
    parser.add_argument('-w', '--wait', type=int, default=5, help='等待时间（秒）')
    args = parser.parse_args()

    if args.output_dir is None:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))
        from config_loader import get_output_dir
        args.output_dir = get_output_dir("语料")

    os.makedirs(args.output_dir, exist_ok=True)

    result = fetch_article(args.url, args.output_dir, args.wait)

    if result['success']:
        print(f"\n✓ 抓取成功!")
        print(f"✓ 标题: {result['title']}")
        print(f"✓ 来源: {result.get('domain', 'unknown')}")
        print(f"\n✓ 内容预览（前500字）:\n{result['content'][:500]}...")
        if result.get('html_path'):
            print(f"\n✓ HTML 保存至: {result['html_path']}")
        if result.get('screenshot_path'):
            print(f"✓ 截图 保存至: {result['screenshot_path']}")
    else:
        print(f"\n✗ 抓取失败: {result.get('error', '未知错误')}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
