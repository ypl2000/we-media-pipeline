---
name: smart-search
description: 精准搜索助手，集成网页搜索、网页提取、图片搜索三大能力。搜索时自动附带高质量图片下载，图文并茂。
triggers:
  - "帮我搜一下"
  - "搜索教程"
  - "找个...教程"
  - "搜索产品"
  - "找个...产品"
  - "怎么学"
  - "哪里有"
  - "帮我找张图"
  - "搜个封面"
  - "找个图片"
---

# 精准搜索助手

**三大搜索能力：文字搜索 + 内容提取 + 图片搜索（自动附带）**

---

## 能力概览

| 能力 | 工具/脚本 | 用途 |
|------|-----------|------|
| 网页搜索 | `web_search` | 搜文字内容 |
| 内容提取 | `web_extract` | 抓页面完整内容 |
| Pexels 图片 | `image-searcher` 脚本 | 免费商用，英文优先 |
| 百度图片 | `image-searcherer` 脚本 | 中文友好，名人/品牌 |

**默认行为：搜索时自动下载 3-5 张高质量相关图片**

---

## 一、搜索 + 图片（默认行为）

### 工作流程

```
收到搜索请求
    ↓
同时执行：
  ├─ web_search 搜文字内容
  └─ image-searcher 搜相关图片
    ↓
返回：文字结果 + 图片列表
```

### 为什么要自动搜图

- 图文结合更直观
- 用户往往需要配图（文章封面、PPT、分享）
- 减少二次搜索的麻烦

---

## 二、网页搜索（内置工具）

### 1. 教程搜索

| 类型 | 操作符 | 示例 |
|------|--------|------|
| GitHub 教程 | `site:github.com intitle:"tutorial"` | `site:github.com intitle:"tutorial" Next.js` |
| 官方文档 | `site:docs.xxx.com` | `site:docs.python.org requests` |
| StackOverflow | `site:stackoverflow.com` | `site:stackoverflow.com python multiprocessing` |
| 掘金/思否 | `site:juejin.cn` | `site:juejin.cn Rust 入门` |
| 综合教程 | `intitle:"从入门到精通"` | `intitle:"从入门到精通" Python` |

### 2. 产品搜索

| 类型 | 操作符 | 示例 |
|------|--------|------|
| 产品评测 | `site:sspai.com` | `site:sspai.com 机械键盘 评测` |
| 产品对比 | `vs` + `site:zhihu.com` | `site:zhihu.com MacBook vs ThinkPad` |
| B站测评 | `site:bilibili.com` | `site:bilibili.com iPhone 测评` |
| 电商口碑 | `site:toutiao.com` | `site:toutiao.com AirPods 体验` |

### 3. 文档搜索

| 类型 | 操作符 | 示例 |
|------|--------|------|
| PDF手册 | `filetype:pdf` | `filetype:pdf TensorFlow 教程` |
| API文档 | `site:developer.xxx.com` | `site:developer.github.com API` |
| MD文档 | `site:github.com *.md` | `site:github.com README.md Kubernetes` |

### 4. 搜索技巧

```
# 组合技：GitHub + 教程 + Python
site:github.com intitle:"tutorial" Python

# 排除广告词
AirPods -广告 -推广

# 精确短语
"从入门到实践" Python
```

---

## 三、图片搜索（自动附带）

### 默认规则

| 场景 | 图片数量 | 来源 | 说明 |
|------|----------|------|------|
| 通用搜索 | 3-5 张 | Pexels 优先 | 封面图/配图 |
| 产品搜索 | 4-6 张 | 百度图片补充 | 产品图优先 |
| 名人/品牌 | 3-5 张 | 百度图片 | Pexels 搜不到 |
| 教程/技术 | 2-4 张 | Pexels | 示意图/封面 |

### 图片质量标准

**高质量图片特征：**
- ✅ 主题相关（logo、产品、概念图）
- ✅ 清晰锐利（无模糊/水印/马赛克）
- ✅ 原创/真实（非表情包/截图/素材）
- ✅ 适合展示（16:9 或 4:3 横版优先）

**排除以下图片：**
- ❌ 表情包、搞笑图
- ❌ 截图、二次加工图
- ❌ 水印遮挡严重的图
- ❌ 像素低、模糊不清
- ❌ 与主题无关的配图

### 图片来源优先级

```
Pexels（免费商用）→ 百度图片（中文/名人/品牌）→ 其他
```

**什么时候用百度图片：**
- 名人照片（马斯克、雷军、马化腾等）
- 品牌产品（iPhone、特斯拉、具体产品型号）
- 国内事件/新闻图片
- Pexels 搜不到时

### 搜索关键词构造

```
文字搜索词 → 图片搜索词

"Next.js 教程" → "Next.js coding programming"
"机械键盘" → "mechanical keyboard product"
"腾讯马维斯" → "腾讯 AI助手 科技产品"
```

---

## 四、内容提取（需要时调用）

### 什么时候用

- 用户说"要详细"、"看完整内容"
- 搜索结果只有摘要，需要深入
- 官方文档、操作手册类

### 工作流程

```
web_search → 定位好页面
    ↓
web_extract → 提取完整内容
    ↓
整理关键信息返回
```

### 工具用法

**web_search：**
```
web_search(query="site:github.com tutorial Next.js", limit=5)
```

**web_extract：**
```
web_extract(urls=["https://example.com/page"])
```
- 最多5个URL
- 大页面摘要（~5000字）
- PDF 直接转 Markdown

---

## 五、完整执行示例

### 搜索 "腾讯马维斯"

**Step 1: 文字搜索**
```
web_search: 腾讯马维斯 Marvis
```

**Step 2: 图片搜索（同步）**
```
image-searcher: "Tencent Marvis AI assistant" -n 4
image-searcherer: "腾讯马维斯" -n 3
```

**Step 3: 返回结果**
```
文字结果：8条相关内容（见上方列表）

相关图片：
1. [图片1] - Marvis 界面截图
2. [图片2] - 产品宣传图
3. [图片3] - 多端协同示意图
...
```

---

## 六、脚本调用参考

### Pexels 图片搜索

```bash
python ~/.hermes/skills/image-searcher/scripts/search_images.py "关键词" -n 5 -p "prefix" -o ./images
```

### 百度图片搜索

```bash
python ~/.hermes/skills/image-searcherer/scripts/search_baidu.py "关键词" -n 5 -p "prefix" -o ./images
```

### 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `query` | 搜索关键词 | 必需 |
| `-n` | 下载数量 | 5 |
| `-o` | 输出目录 | ./images |
| `-p` | 文件名前缀 | img |

---

## 七、注意事项

**搜索：**
- 先想清楚搜什么，再用操作符
- 教程优先 GitHub + 官方文档
- 产品优先评测网站

**图片：**
- **始终自动附带下载**，不需要用户提醒
- 优先 Pexels，版权风险低
- 百度图片仅补充名人/品牌/国内内容
- 质量第一，数量其次
- 批量下载间隔 1-2 秒，单次≤20张
