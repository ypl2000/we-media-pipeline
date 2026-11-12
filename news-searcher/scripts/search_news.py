#!/usr/bin/env python3
"""
Search latest news using Metaso API (优先) or Tavily API.
Requires METASO_API_KEY or TAVILY_API_KEY environment variable or config.json.
Get Metaso API key at: https://metaso.cn/ (注册送5000点)
Get Tavily API key at: https://tavily.com/

默认优先使用秘塔 API（中国优化），失败后自动回退到 Tavily。
"""

import sys
import argparse
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))
from config_loader import get_config_value


def get_api_key(cli_key=None):
    """Get Tavily API key with priority: CLI arg > env var > project config > skill config."""
    if cli_key and cli_key.strip():
        return cli_key.strip()

    return (get_config_value('tavily_api_key', skill_name='news-searcher') or '').strip() or None


def get_metaso_key(cli_key=None):
    """Get Metaso API key with priority: CLI arg > env var > project config > skill config."""
    if cli_key and cli_key.strip():
        return cli_key.strip()

    return (get_config_value('metaso_api_key', skill_name='news-searcher') or '').strip() or None


def get_default_days():
    return get_config_value('news_search.default_days', 7, skill_name='news-searcher')


def get_default_results():
    return get_config_value('news_search.default_results', 10, skill_name='news-searcher')


def _single_search_tavily(query, api_key, max_results, days, content_type):
    """
    Perform a single Tavily search request.
    
    Args:
        query: Search query
        api_key: Tavily API key
        max_results: Maximum number of results
        days: Number of days to search back
        content_type: Content type
    
    Returns:
        dict: Search results or None on error
    """
    try:
        import requests
    except ImportError:
        return None
    
    try:
        url = "https://api.tavily.com/search"
        
        topic_map = {
            'news': 'news',
            'tutorial': 'general',
            'product': 'general'
        }
        
        payload = {
            "api_key": api_key,
            "query": query,
            "search_depth": "advanced",
            "topic": topic_map.get(content_type, "news"),
            "include_answer": True,
            "include_images": True,
            "include_raw_content": False,
            "time_range": ("day" if days <= 1 else "week" if days <= 7 else "month" if days <= 30 else "year"),
            "max_results": min(max_results, 20)
        }
        
        headers = {
            "Content-Type": "application/json"
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=120)

        if response.status_code != 200:
            print(f"  Tavily HTTP {response.status_code}: {response.text[:150]}", file=sys.stderr)
            return None

        response.raise_for_status()
        return response.json()

    except Exception as e:
        print(f"  Tavily 请求失败: {type(e).__name__}: {str(e)[:120]}", file=sys.stderr)
        return None


def parse_date(text):
    """Metaso 给 '2026年10月13日'，Tavily 给 'Fri, 09 Oct 2026'，都解析成 date。"""
    if not text:
        return None
    text = str(text).strip()
    m = re.search(r'(\d{4})\s*[年\-/.]\s*(\d{1,2})\s*[月\-/.]\s*(\d{1,2})', text)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
        except ValueError:
            return None
    try:  # Tavily 用 RFC 2822
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(text).date()
    except (TypeError, ValueError):
        return None


def _single_search_metaso(query, api_key, max_results, days, content_type):
    """
    Perform a single Metaso search request.
    
    Args:
        query: Search query
        api_key: Metaso API key
        max_results: Maximum number of results
        days: Number of days to search back
        content_type: Content type (not used for Metaso)
    
    Returns:
        dict: Search results or None on error
    """
    try:
        import http.client
        import json
    except ImportError:
        return None
    
    try:
        conn = http.client.HTTPSConnection("metaso.cn", timeout=60)

        # recency_days 被这个接口静默丢弃（响应回显的 searchParameters 里没有它），
        # 所以要多拉一些再由调用方按 date 本地过滤。
        payload = json.dumps({
            "q": query,
            "scope": "webpage",
            "includeSummary": True,
            "includeRowContent": False,
            "size": str(min(max(max_results * 3, 20), 50)),
            "recency_days": str(days)
        })
        
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        conn.request("POST", "/api/v1/search", payload, headers)
        res = conn.getresponse()
        data = json.loads(res.read().decode("utf-8"))
        
        if res.status != 200:
            print(f"  Metaso API error: status={res.status}, data={str(data)[:200]}", file=sys.stderr)
            return None
        
        return data
    
    except Exception as e:
        print(f"  Metaso API error: {e}", file=sys.stderr)
        return None


def search_news_metaso(query, max_results=10, days=7, api_key=None, content_type='news'):
    """
    Search news using Metaso API.
    
    Args:
        query: Search query
        max_results: Maximum number of results (default: 10)
        days: Search news from last N days (default: 7)
        api_key: Metaso API key
        content_type: Content type ('news', 'tutorial', 'product')
    
    Returns:
        dict: Search results
    """
    try:
        import http.client
        import json
    except ImportError:
        return {
            'success': False,
            'error': 'http.client and json libraries required'
        }
    
    if not api_key:
        api_key = get_metaso_key()
    
    if not api_key:
        return {
            'success': False,
            'error': 'Metaso API key required',
            'fallback': 'tavily'
        }
    
    all_results = []
    all_images = []
    answers = []
    
    data = _single_search_metaso(query, api_key, max_results, days, content_type)
    if not data:
        return {
            'success': False,
            'error': f'No results from Metaso for query: {query}',
            'fallback': 'tavily'
        }
    
    # Parse Metaso results (API returns 'webpages' not 'results')
    webpages = data.get('webpages', []) or data.get('results', [])
    if webpages:
        for result in webpages:
            processed = {
                'title': result.get('title', ''),
                'url': result.get('link', '') or result.get('url', ''),
                'content': result.get('snippet', '') or result.get('content', ''),
                'score': 1.0,  # Metaso doesn't provide scores
                'published_date': result.get('published_at', '') or result.get('date', ''),
                'source': result.get('source', '') or _extract_domain(result.get('link', '') or result.get('url', '')),
                'images': []
            }
            all_results.append(processed)
    
    # Get AI summary if available
    if 'summary' in data:
        answers.append(data['summary'])
    if 'answer' in data:
        answers.append(data['answer'])

    if not all_results:
        return {
            'success': False,
            'error': f'No results found for query: {query}',
            'fallback': 'tavily'
        }

    # 接口不认 recency_days，只能自己按日期筛。日期认不出来的保留 —— 它可能本身就是新的。
    cutoff = (datetime.now() - timedelta(days=days)).date()
    kept = [r for r in all_results
            if parse_date(r['published_date']) is None or parse_date(r['published_date']) >= cutoff]
    dropped = len(all_results) - len(kept)
    if dropped:
        print(f"  Metaso: {dropped}/{len(all_results)} 条超出近 {days} 天，已丢弃", file=sys.stderr)

    # 筛得太狠说明 Metaso 这条路给不了近期结果，交给调用方回退 Tavily
    if len(kept) < 3:
        return {
            'success': False,
            'error': f'Metaso 近 {days} 天内只有 {len(kept)} 条结果',
            'fallback': 'tavily'
        }

    all_results = kept

    # Combine answers for AI summary
    combined_answer = ' | '.join(answers[:3]) if answers else ''

    return {
        'success': True,
        'query': query,
        'time_range': f"Last {days} days",
        'answer': combined_answer,
        'results': all_results[:max_results],
        'images': all_images[:50]
    }


def _extract_domain(url):
    """Extract domain from URL."""
    if not url:
        return ''
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc
    except:
        return ''


def search_news_tavily(query, max_results=10, days=7, api_key=None, content_type='news'):
    """
    Search news using Tavily API with automatic query expansion and translation.
    
    For Chinese queries, automatically translates to English and searches both
    to improve relevance of results.
    
    Args:
        query: Search query
        max_results: Maximum number of results (default: 10)
        days: Search news from last N days (default: 7)
        api_key: Tavily API key
        content_type: Content type ('news', 'tutorial', 'product')
    
    Returns:
        dict: Search results
    """
    try:
        import requests
    except ImportError:
        return {
            'success': False,
            'error': 'requests library required. Install with: pip install requests'
        }
    
    if not api_key:
        api_key = get_api_key()
    
    if not api_key:
        raise ValueError(
            "Tavily API key required. "
            "Get your free key at https://tavily.com/ "
            "and configure in:\n"
            "  1. Project config.json (recommended)\n"
            "  2. news-searcher/config.json\n"
            "  3. Environment variable TAVILY_API_KEY"
        )
    
    # 只搜原词，不做查询扩展。Tavily 一次请求要 ~100 秒，扩展成 4 个词就是 7 分钟。
    queries = [query]

    all_results = []
    all_images = []
    used_urls = set()
    answers = []

    for q in queries:
        data = _single_search_tavily(q, api_key, max_results, days, content_type)
        if not data:
            continue

        if 'answer' in data and data['answer']:
            answers.append(data['answer'])

        if 'results' in data:
            for result in data['results']:
                url = result.get('url', '')
                if url and url not in used_urls:
                    used_urls.add(url)
                    processed = {
                        'title': result.get('title', ''),
                        'url': url,
                        'content': result.get('content', ''),
                        'score': result.get('score', 0),
                        'published_date': result.get('published_date', ''),
                        'source': result.get('source', ''),
                        'images': result.get('images', [])
                    }
                    all_results.append(processed)
                    all_images.extend(processed['images'])

    if not all_results:
        return {
            'success': False,
            'error': f'No results found for query: {query}'
        }
    
    # Sort by relevance score
    all_results.sort(key=lambda x: x.get('score', 0), reverse=True)
    
    # Deduplicate images
    all_images = list(dict.fromkeys(all_images))
    
    # Combine answers for AI summary
    combined_answer = ' | '.join(answers[:3]) if answers else ''
    
    return {
        'success': True,
        'query': query,
        'expanded_queries': queries,
        'time_range': f"Last {days} days",
        'answer': combined_answer,
        'results': all_results[:max_results],
        'images': all_images[:50]  # Include aggregated images
    }


def format_output(results, format='text'):
    """
    Format search results for output.
    
    Args:
        results: Search results dict
        format: Output format ('text', 'json', 'markdown')
    
    Returns:
        str: Formatted output
    """
    if not results['success']:
        return f"Error: {results.get('error', 'Unknown error')}"
    
    if format == 'json':
        return json.dumps(results, indent=2, ensure_ascii=False)
    
    elif format == 'markdown':
        lines = []
        lines.append(f"# Search Results: {results['query']}")
        lines.append(f"\n**Time Range:** {results['time_range']}")
        lines.append(f"**Results:** {len(results['results'])}")
        lines.append("\n---\n")
        
        if results['answer']:
            lines.append("## AI Summary\n")
            lines.append(results['answer'])
            lines.append("\n---\n")
        
        lines.append("## News Articles\n")
        
        for i, result in enumerate(results['results'], 1):
            lines.append(f"### {i}. {result['title']}")
            lines.append(f"**Source:** {result['source']}")
            if result['published_date']:
                lines.append(f"**Published:** {result['published_date']}")
            lines.append(f"**URL:** {result['url']}")
            lines.append(f"**Relevance Score:** {result['score']:.2f}")
            if result.get('images'):
                lines.append(f"**Images:** {len(result['images'])} image(s)")
                for img_url in result['images'][:3]:
                    lines.append(f"- {img_url}")
            lines.append(f"\n{result['content'][:300]}...")
            lines.append("\n---\n")
        
        return '\n'.join(lines)
    
    else:
        lines = []
        lines.append(f"Search: {results['query']}")
        lines.append(f"Time Range: {results['time_range']}")
        lines.append(f"Results: {len(results['results'])}")
        lines.append("-" * 60)
        
        if results['answer']:
            lines.append("\n[AI Summary]")
            lines.append(results['answer'])
            lines.append("-" * 60)
        
        lines.append("\n[News Articles]\n")
        
        for i, result in enumerate(results['results'], 1):
            lines.append(f"\n{i}. {result['title']}")
            lines.append(f"   Source: {result['source']}")
            if result['published_date']:
                lines.append(f"   Published: {result['published_date']}")
            lines.append(f"   URL: {result['url']}")
            lines.append(f"   Score: {result['score']:.2f}")
            if result.get('images'):
                lines.append(f"   Images: {len(result['images'])} image(s)")
                for img_url in result['images'][:2]:
                    lines.append(f"   - {img_url}")
            lines.append(f"   {result['content'][:200]}...")
            lines.append("")
        
        return '\n'.join(lines)


def save_results(results, output_file, format='markdown'):
    """
    Save search results to file.

    Args:
        results: Search results dict
        output_file: Output file path
        format: Output format

    Returns:
        str: Saved file path
    """
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    output = format_output(results, format)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(output)
    
    return output_file


def main():
    parser = argparse.ArgumentParser(description='Search latest news using Metaso API (优先) or Tavily API')
    parser.add_argument('query', help='Search query')
    parser.add_argument('-n', '--num', type=int, default=None, help=f'Number of results (default: {get_default_results()})')
    parser.add_argument('-d', '--days', type=int, default=None, help=f'Search last N days (default: {get_default_days()})')
    parser.add_argument('-k', '--key', help='Metaso API key (overrides config)')
    parser.add_argument('-f', '--format', choices=['text', 'json', 'markdown'], default='text',
                        help='Output format (default: text)')
    parser.add_argument('-o', '--output', help='Save results to file')
    parser.add_argument('-t', '--type', choices=['news', 'tutorial', 'product'], default='news',
                        help='Content type (default: news)')
    parser.add_argument('--provider', choices=['metaso', 'tavily', 'auto'], default='auto',
                        help='Search provider: metaso, tavily, or auto (优先 Tavily，回退秘塔)')
    
    args = parser.parse_args()
    
    default_days = get_default_days()
    default_results = get_default_results()
    
    query = args.query
    days = args.days if args.days is not None else default_days
    num = args.num if args.num is not None else default_results
    content_type = args.type
    provider = args.provider
    
    metaso_key = get_metaso_key(args.key)
    tavily_key = get_api_key(args.key)  # Reuse get_api_key for Tavily

    # 首选 Tavily：它的 time_range 真生效，还带图片 URL。
    # Metaso 的 recency_days 是失效参数，且窄词只会返回官网/百科这类长期存在的页面
    # （日期老），只能当兜底。
    results = None
    used_provider = None

    for name in (['tavily', 'metaso'] if provider == 'auto' else [provider]):
        key = tavily_key if name == 'tavily' else metaso_key
        if not key:
            continue
        print(f"Searching with: {name} API", file=sys.stderr)
        search_fn = search_news_tavily if name == 'tavily' else search_news_metaso
        results = search_fn(
            query=query,
            max_results=num,
            days=days,
            api_key=key,
            content_type=content_type
        )
        if results.get('success'):
            used_provider = name
            break
        print(f"{name} failed: {results.get('error')}", file=sys.stderr)
    
    # Check results
    if not results or not results.get('success'):
        print("Error: 搜索失败。", file=sys.stderr)
        if not tavily_key and not metaso_key:
            print("两个搜索源都没有配 API key。", file=sys.stderr)
            print("  Tavily（首选）: https://tavily.com/  -> tavily_api_key", file=sys.stderr)
            print("  Metaso（备用）: https://metaso.cn/   -> metaso_api_key", file=sys.stderr)
            print("  可以放在环境变量（优先）或根目录 config.json 里。", file=sys.stderr)
        else:
            print(f"原因: {results.get('error') if results else '未知'}", file=sys.stderr)
            print("（近 N 天内没有足够结果时会这样 —— 换个更宽泛的搜索词再试）", file=sys.stderr)
        sys.exit(1)
    
    output = format_output(results, args.format)
    print(output)
    
    if args.output:
        saved_path = save_results(results, args.output, args.format)
        print(f"\n✓ Results saved to: {saved_path}")
        # 配图 URL 单独存一份，给下游 ImageDownload 用
        img_path = Path(saved_path).with_name('01_news_images.json')
        with open(img_path, 'w', encoding='utf-8') as f:
            json.dump(results.get('images', []), f, ensure_ascii=False)
        print(f"✓ Images saved to: {img_path}")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())