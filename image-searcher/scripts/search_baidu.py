#!/usr/bin/env python3
"""
百度图片搜索爬虫
Search and download images from Baidu Image.

注意：此脚本仅用于个人学习/研究，请遵守相关法律法规和版权规定。
"""

import sys
import argparse
import requests
import re
import os
import shutil
from pathlib import Path


def search_baidu_images(query, max_results=20, timeout=30):
    """
    Search images using Baidu Image with quality filtering.
    
    Args:
        query: Search query string (Chinese supported)
        max_results: Maximum number of results to return
        timeout: Request timeout in seconds
    
    Returns:
        list: List of image info dicts with URL and metadata
    """
    # Enhance query with quality keywords for better results
    quality_keywords = [
        "高清", "高质量", "官方", "发布会", " keynote", "产品图",
        "官方宣传", "品牌", "logo", "标志", "高清壁纸"
    ]
    
    # Try original query first, then with quality keywords
    search_queries = [query]
    for kw in quality_keywords[:3]:
        if kw not in query:
            search_queries.append(f"{query} {kw}")
    
    all_images = []
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://image.baidu.com/"
    }
    
    for search_query in search_queries[:2]:  # Try up to 2 queries
        url = "https://image.baidu.com/search/flip"
        params = {
            "tn": "baiduimage",
            "word": search_query,
            "pn": 0,
            "rn": max_results * 3,  # Get more to filter
            "istype": "2",
            "ie": "utf-8",
            "oe": "utf-8",
            "z": "3"  # Large size filter
        }
        
        try:
            response = requests.get(url, params=params, headers=headers, timeout=timeout)
            response.raise_for_status()
            
            # Check if redirected to captcha page
            if 'captcha' in response.url or 'tuxing' in response.url:
                raise Exception("百度反爬检测：遇到验证码页面。请稍后重试或降低请求频率。")
            
            # Extract image URLs from HTML using regex
            thumb_urls = re.findall(r'"thumbURL":"([^"]+)"', response.text)
            middle_urls = re.findall(r'"middleURL":"([^"]+)"', response.text)
            titles = re.findall(r'"fromTitle":"([^"]+)"', response.text)
            
            # Combine into image list with quality scoring
            for i in range(min(len(thumb_urls), len(middle_urls))):
                title = titles[i] if i < len(titles) else ''
                
                # Calculate quality score
                quality_score = 0
                title_lower = title.lower()
                
                # Prefer official/brand sources
                official_keywords = ['官方', '官网', '品牌', 'logo', '标志', 'keynote', '发布会']
                for kw in official_keywords:
                    if kw in title_lower or kw in search_query.lower():
                        quality_score += 10
                
                # Prefer recent content (check URL patterns - last 2 years)
                url = thumb_urls[i] if i < len(thumb_urls) else ''
                from datetime import datetime
                current_year = datetime.now().year
                recent_years = [str(current_year), str(current_year - 1)]
                if any(year in url for year in recent_years):
                    quality_score += 5
                
                # Penalize low-quality patterns
                low_quality_patterns = ['表情包', '斗图', '搞笑', '素材', 'png透明']
                for pattern in low_quality_patterns:
                    if pattern in title_lower:
                        quality_score -= 20
                
                image_info = {
                    'id': len(all_images),
                    'url': thumb_urls[i] if i < len(thumb_urls) else None,
                    'large_url': middle_urls[i] if i < len(middle_urls) else None,
                    'title': title,
                    'width': None,
                    'height': None,
                    'source': 'Baidu Image',
                    'quality_score': quality_score
                }
                
                if image_info['url'] or image_info['large_url']:
                    all_images.append(image_info)
            
        except Exception as e:
            print(f"  搜索尝试失败 ({search_query}): {e}", file=sys.stderr)
            continue
    
    # Sort by quality score (descending) and return best results
    all_images.sort(key=lambda x: x.get('quality_score', 0), reverse=True)
    
    return all_images[:max_results]


def check_image_resolution(image_path, min_width=800, min_height=600):
    """
    Check if image meets minimum resolution requirements.
    
    Args:
        image_path: Path to image file
        min_width: Minimum required width
        min_height: Minimum required height
    
    Returns:
        tuple: (is_valid: bool, width: int, height: int)
    """
    try:
        from PIL import Image
        with Image.open(image_path) as img:
            width, height = img.size
            is_valid = width >= min_width and height >= min_height
            return is_valid, width, height
    except Exception:
        return False, 0, 0


def download_image(image_info, output_dir, filename=None, min_width=800, min_height=600):
    """
    Download a single image and verify resolution.
    
    Args:
        image_info: Image info dict from search_baidu_images
        output_dir: Directory to save image
        filename: Output filename (optional)
        min_width: Minimum required width (default: 800)
        min_height: Minimum required height (default: 600)
    
    Returns:
        str: Saved file path or None if failed/low resolution
    """
    try:
        url = image_info.get('large_url') or image_info.get('url')
        if not url:
            return None
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://image.baidu.com/"
        }
        
        response = requests.get(url, headers=headers, timeout=30, stream=True)
        response.raise_for_status()
        
        # Determine file extension
        url_path = url.split('?')[0]
        ext = Path(url_path).suffix.lower()
        if not ext or ext not in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']:
            ext = '.jpg'
        
        # Generate filename
        if not filename:
            image_id = image_info.get('id', 'unknown')
            filename = f"baidu_{image_id}{ext}"
        elif not filename.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')):
            filename += ext
        
        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)
        
        # Save file to temp first
        import tempfile
        temp_fd, temp_path = tempfile.mkstemp(suffix=ext)
        os.close(temp_fd)
        
        with open(temp_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        
        # Check resolution
        is_valid, width, height = check_image_resolution(temp_path, min_width, min_height)
        
        if not is_valid:
            # Delete low-resolution image
            try:
                os.remove(temp_path)
            except:
                pass
            print(f"    ✗ 分辨率过低 ({width}x{height})，已跳过")
            return None
        
        # Move to final destination
        output_path = os.path.join(output_dir, filename)
        shutil.move(temp_path, output_path)
        
        return output_path
    
    except Exception as e:
        print(f"  下载失败：{e}", file=sys.stderr)
        return None


def search_and_download(query, output_dir, max_results=6, prefix="img"):
    """
    Search and download images from Baidu with quality filtering.
    
    Args:
        query: Search query string
        output_dir: Directory to save images
        max_results: Maximum number of images to download
        prefix: Filename prefix
    
    Returns:
        dict: Result with success status and downloaded files
    """
    print(f"百度搜索：{query}")
    print(f"最大数量：{max_results}")
    print(f"输出目录：{output_dir}")
    print("-" * 50)
    
    try:
        # Search with quality scoring
        images = search_baidu_images(query, max_results=max_results * 3)
        
        if not images:
            return {
                'success': False,
                'error': '未找到图片',
                'downloaded': [],
                'failed': []
            }
        
        print(f"找到 {len(images)} 张图片（已按质量排序）")
        print("-" * 50)
        
        # Download
        downloaded = []
        failed = []
        skipped_low_res = 0
        
        for i, image_info in enumerate(images[:max_results * 3], 1):
            # Stop if we have enough images
            if len(downloaded) >= max_results:
                break
            
            filename = f"{prefix}_{len(downloaded) + 1:02d}"
            
            title = image_info.get('title', '')[:30] or '无标题'
            source = image_info.get('source', '未知')
            quality_score = image_info.get('quality_score', 0)
            score_indicator = "★" * (quality_score // 10) if quality_score > 0 else ""
            print(f"[{len(downloaded) + 1}/{max_results}] {title}... (来源：{source}) {score_indicator}")
            
            result = download_image(image_info, output_dir, filename)
            if result:
                # Verify resolution after download
                is_valid, width, height = check_image_resolution(result)
                if not is_valid:
                    try:
                        os.remove(result)
                    except:
                        pass
                    skipped_low_res += 1
                    print(f"    ✗ 分辨率过低 ({width}x{height})，已跳过")
                    continue
                
                downloaded.append({
                    'path': result,
                    'url': image_info.get('url'),
                    'title': image_info.get('title', ''),
                    'source': source
                })
                print(f"  ✓ 已保存：{os.path.basename(result)} ({width}x{height})")
            else:
                failed.append(image_info.get('url'))
                print(f"  ✗ 失败")
        
        print("-" * 50)
        print(f"下载完成：{len(downloaded)}/{max_results}")
        
        return {
            'success': len(downloaded) > 0,
            'downloaded': downloaded,
            'failed': failed,
            'total_found': len(images)
        }
    
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'downloaded': [],
            'failed': []
        }


def main():
    parser = argparse.ArgumentParser(description='百度搜索并下载图片')
    parser.add_argument('query', help='搜索关键词')
    parser.add_argument('-o', '--output', default=None,
                        help='输出目录（默认：桌面输出根目录/baidu_images）')
    parser.add_argument('-n', '--num', type=int, default=6, help='下载数量（默认：6）')
    parser.add_argument('-p', '--prefix', default='img', help='文件名前缀（默认：img）')
    
    args = parser.parse_args()

    if args.output is None:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))
        from config_loader import get_output_dir
        args.output = get_output_dir("baidu_images")

    result = search_and_download(
        query=args.query,
        output_dir=args.output,
        max_results=args.num,
        prefix=args.prefix
    )
    
    if result['success']:
        print(f"\n✓ 成功下载 {len(result['downloaded'])} 张图片")
        for item in result['downloaded']:
            print(f"  - {item['path']}")
            print(f"    来源：{item['source']}")
    else:
        print(f"\n✗ 失败：{result.get('error', '未知错误')}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
