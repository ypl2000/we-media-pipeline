---
name: news-searcher
description: Search latest news and information using Tavily API. Use when user needs to find the most recent and accurate news about a specific topic, concept, or event. Supports time-based filtering, multiple output formats, and AI-generated summaries. Requires Tavily API key (free tier available at tavily.com).
---

# News Search

Search the latest news and information using Tavily AI search engine.

## Features

- **Automatic Translation**: Chinese queries are automatically translated to English for better search results
- **Multi-Query Expansion**: Searches with multiple query variations (original + translated + variations)
- **Result Deduplication**: Removes duplicate URLs across multiple queries
- **Relevance Ranking**: Results sorted by relevance score

## When to Use

- Need to find the most recent news about a topic
- Want accurate and up-to-date information
- Researching current events or trends
- Fact-checking recent developments
- Need AI-generated summary of news
- Writing articles that require latest data

## Prerequisites

**You need a Tavily API key (free tier available):**

1. Go to https://tavily.com/
2. Sign up for an account
3. Get your API key from the dashboard
4. Configure your API key (choose one method):

**Required Python packages:**
```bash
pip install requests translate
```

**Free tier includes:**
- 1,000 API calls/month
- Real-time search results
- AI-generated answers
- Advanced search depth

## Quick Start

### Setup (One-time)

**Option 1: Environment Variable (recommended for standalone use)**

```bash
# Windows PowerShell
$env:TAVILY_API_KEY="your_api_key_here"

# Windows CMD
set TAVILY_API_KEY=your_api_key_here
```

**Option 2: Config File (recommended when using with we-media-pipeline)**

Edit 项目根目录的 `config.json`（所有 API key 都放这一份）:

```json
{
  "metaso_api_key": "your_metaso_key_here",
  "tavily_api_key": "your_tavily_key_here"
}
```

**搜索优先级**：Tavily > 秘塔（Metaso），Tavily 失败自动回退到秘塔。

**Priority**: CLI arg > Environment variable > Project config.json > news-searcher/config.json（与 `get_config_value()` 实际顺序一致）

### Option 3: Local Config File (standalone use)

Edit `news-searcher/config.json`:

```json
{
  "tavily_api_key": "your_api_key_here",
  "default_days": 7,
  "default_results": 10
}
```

**Note**: When used within We-media-pipeline project, project `config.json` takes precedence over skill-local config.

### Quick Start

```bash
# Search latest news (default: last 7 days)
python scripts/search_news.py "xAI解散"

# Search with custom time range (last 30 days)
python scripts/search_news.py "AI发展趋势" -d 30

# Get more results
python scripts/search_news.py "马斯克" -n 20

# Output as JSON
python scripts/search_news.py "ChatGPT" -f json

# Output as Markdown
python scripts/search_news.py "OpenAI" -f markdown

# Save to file
python scripts/search_news.py "人工智能" -o news.md -f markdown

# Full example
python scripts/search_news.py "科技新闻" -k YOUR_KEY -d 7 -n 15 -f markdown -o latest_news.md
```

## Features

### Search Capabilities

- **Real-time news**: Search latest information from last N days
- **AI summary**: Get AI-generated answer to your query
- **Relevance scoring**: Results ranked by relevance
- **Source diversity**: Multiple news sources
- **Advanced search**: Deep search for comprehensive results

### Output Formats

| Format | Description | Use Case |
|--------|-------------|----------|
| **text** | Plain text, console-friendly | Quick reading |
| **json** | Structured JSON data | Programmatic use |
| **markdown** | Formatted Markdown | Articles, reports |

### Time Filtering

- Default: Last 7 days
- Custom: 1-30 days
- Focus on recent, relevant news

**⚠️ Critical implementation note**: The `days` parameter is mapped to Tavily's `time_range` and `topic` parameters in the API payload:
  - `days ≤ 1` → `time_range: "day"`
  - `days ≤ 7` → `time_range: "week"` (pipeline default)
  - `days ≤ 30` → `time_range: "month"`
  - `days > 30` → `time_range: "year"`
  - `topic: "news"` is always set to restrict to news content

If Tavily returns stale/irrelevant news, check that: (1) your `days` parameter is being passed correctly, (2) the API key has quota remaining.

## Output Format

### Text Format (Default)

```
Search: xAI解散
Time Range: Last 7 days
Results: 10
------------------------------------------------------------

[AI Summary]
xAI, Elon Musk's AI company, has reportedly dissolved its core team...
------------------------------------------------------------

[News Articles]

1. xAI核心团队解散，马斯克的大模型梦碎了
   Source: TechCrunch
   Published: 2025-05-10
   URL: https://techcrunch.com/...
   Score: 0.95
   Elon Musk's xAI has dissolved its core engineering team...
```

### Markdown Format

```markdown
# Search Results: xAI解散

**Time Range:** Last 7 days
**Results:** 10

---

## AI Summary

xAI, Elon Musk's AI company, has reportedly dissolved...

---

## News Articles

### 1. xAI核心团队解散，马斯克的大模型梦碎了
**Source:** TechCrunch
**Published:** 2025-05-10
**URL:** https://techcrunch.com/...
**Relevance Score:** 0.95

Elon Musk's xAI has dissolved its core engineering team...
```

### JSON Format

```json
{
  "success": true,
  "query": "xAI解散",
  "time_range": "Last 7 days",
  "answer": "AI-generated summary...",
  "results": [
    {
      "title": "xAI核心团队解散...",
      "url": "https://...",
      "content": "Article content...",
      "score": 0.95,
      "published_date": "2025-05-10",
      "source": "TechCrunch"
    }
  ]
}
```

## Integration with article-generator

Combine with article-generator for data-driven articles:

```bash
# Step 1: Search latest news
python news-searcher/scripts/search_news.py "AI最新动态" -f markdown -o research.md

# Step 2: Generate article based on research
python article-generator/scripts/generate_article.py "基于最新研究的AI文章" --research research.md
```

## Script Reference

### `scripts/search_news.py`

**Purpose**: Search latest news using Tavily API

**Requirements**:
- Python 3.8+
- requests: `pip install requests`

**Arguments**:
- `query` (required): Search query string
- `-n, --num`: Number of results (default: 10, max: 20)
- `-d, --days`: Search last N days (default: 7)
- `-k, --key`: Tavily API key (optional if set via env var)
- `-f, --format`: Output format: text/json/markdown (default: text)
- `-o, --output`: Save results to file (optional)

**Returns**:
```python
{
    'success': True/False,
    'query': 'search query',
    'time_range': 'Last 7 days',
    'answer': 'AI-generated summary',
    'results': [
        {
            'title': 'Article title',
            'url': 'https://...',
            'content': 'Article content...',
            'score': 0.95,
            'published_date': '2025-05-10',
            'source': 'News Source'
        }
    ],
    'error': 'error message'  # Only if success is False
}
```

## Limitations

- Requires Tavily API key (free registration)
- Rate limit: 1,000 requests/month on free tier
- Search limited to publicly available web content
- Time filtering is approximate
- Some sources may not have published dates

## Future Enhancements

- [ ] Support for specific news sources
- [ ] Sentiment analysis of news
- [ ] Trend detection over time
- [ ] Multi-language support
- [ ] Integration with RSS feeds
- [ ] Automatic fact-checking
- [ ] News clustering by topic
