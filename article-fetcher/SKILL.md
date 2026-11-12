---
name: article-fetcher
description: 抓取微信公众号文章并学习写作风格。按主题分类保存，自动分析风格并增量更新到 style.md。
triggers:
  - "学习这篇文章"
  - "抓取这篇文章"
  - "分析这篇文章"
---

# 微信公众号文章抓取与风格学习

**用途**：抓取公众号文章，提取写作风格，增量学习到主题风格指南。

## 内置主题

**「科技热点分析」** — 预置主题，已内置风格指南（源自 article-writer/style-guide.md 的12篇文章总结）和4篇示例文章。可直接使用，也可追加学习。

**「产品使用教程」** — 预置主题，内置风格指南（教程类写作规范），已学8篇文章（SOLO写产品手册、TRAE×Unity、TRAE×IGA Pages、AI时代Git版本管理、短剧制作SOLO、Rules高效使用指南、OpenClaw部署、API文档到服务自动化）。

**「开源产品分享」** — 预置主题，内置风格指南（开源/产品分享写作规范），已学5篇文章（/howSkills指令、academic-research-skills论文流水线、PPT Master工具、6个小众开源项目合集、PinMe Skill）。

## 目录结构

```
<repo>/reference/
  └── {主题}/
      ├── index.json
      ├── style.md
      └── {文章标题}/
          ├── {文章标题}.html      # 原始HTML（含富文本格式）
          ├── {文章标题}.pdf
          ├── {文章标题}.png       # 首帧截图
          └── {文章标题}_images.json  # 配图元数据
```

## 使用方式

### 抓取并学习（指定主题）

```
学习这篇文章，主题是AI创业：https://mp.weixin.qq.com/s/xxxxx
```

执行流程（两步走）：
1. **抓取**：`fetch_wechat_article.py --topic "{主题}"`，保存 HTML/PDF/截图/_images.json 到主题目录
2. **分析**：`analyze_and_update_style.py "{主题}" "{标题}" "{URL}"`，分析风格并追加到 style.md，更新 index.json

### 语料聚合（学完若干篇后运行一次）

```
python scripts/aggregate_style.py "主题" -o reference
```

编译/编辑稿自动排除（特征词：全文编译、编译自、译文等）；需要手动排除时在 `<topic>/exclude.txt` 里一行写一个文章目录名。

重新分析主题下已存的全部文章，把「段落数/标题长度/配图数/强调色」这类单篇特有值改写为语料均值与频次（带「语料均值，N篇」标注），避免“最后一篇算数”带来的误导。

### 查看某主题已学到的风格

直接读取 `articles/{主题}/style.md` 展示。

### 查看某主题已存的文章

读取 `articles/{主题}/index.json` 展示。

## style.md 格式

知识点以 bullet point 形式存储，学到新的就追加，重复的不补充。共 10 个 section：**标题、开篇、句式、词汇、结尾、结构、配图位置、教程类型、排版格式、特色**。

## 9+1 个分析维度

| Section | 分析内容 |
|---------|---------|
| 标题 | 长度、句式、疑问句、数字、情绪词、转折符号 |
| 开篇 | 长度、切入点类型（场景/数据/故事/时间）|
| 句式 | 长短句比例、空行节奏、标点串联、排比 |
| 词汇 | 专业 vs 口语、场景化、情感化、数据化 |
| 结尾 | 长度、行动号召、金句/留白 |
| 结构 | 段落数量、文章类型（产品/教程/人物/研究）|
| 配图位置 | 图片数量、密度、分布位置、配图类型（技术截图 vs 场景素材）|
| 教程类型 | 操作步骤型 vs 案例展示型（句式/开篇/配图/结构各有不同）|
| 排版格式 | 加粗频率/用途、强调色种类及用途、大字号章节标题 |

**+1 个手动 section「特色」**：不属于自动分析，由人工在预置 style.md 中维护。

## 排版格式分析详解

分析器从 HTML 源码中提取富文本格式信息（加粗、颜色、字号），学习该公众号的排版风格：

| 分析维度 | 说明 |
|---------|------|
| 加粗频率 | 频繁加粗 vs 偶尔使用 |
| 加粗用途 | 短词组强调 vs 整句强调 |
| 强调色 | 颜色种类及 RGB 值 |
| 颜色用途 | 章节编号/小标签/重点词 |
| 大字号 | 章节标题用多大（≥28px）|

**WeChat HTML 特殊编码**：微信文章 HTML 里引号写成 `\x22`（4个字符），不是标准 HTML 实体 `&quot;`。`analyze_formatting()` 在正则匹配前做替换：
```python
decoded = decoded.replace('\\x22', chr(34)).replace('\\x3e', '>').replace('\\x3c', '<')
```

## 手动调用

```bash
# 抓取文章（自动提取配图元数据，默认输出到 <repo>/reference/{主题}/）
python scripts/fetch_wechat_article.py "URL" -t "主题" -w 8

# 分析风格并更新（--images 传入图片元数据路径）
cat /path/to/article.html | python scripts/analyze_and_update_style.py \
  "主题" "文章标题" "URL" --images /path/to/article_images.json
```

## 相关脚本

- `scripts/fetch_wechat_article.py` — 抓取文章（支持 --topic，自动提取配图元数据）
- `scripts/analyze_and_update_style.py` — 分析风格并增量更新 style.md + index.json
- `scripts/aggregate_style.py` — 语料聚合，把单篇特有值改为均值/频次

## Pitfalls

### STYLE_SECTIONS must include every section name in style.md
`analyze_and_update_style.py` rebuilds style.md from `STYLE_SECTIONS` list. If a section exists in style.md but is NOT in `STYLE_SECTIONS`, it is silently dropped on every subsequent run.

Symptom: `## 教程类型` section (or any new section) disappears after running the analyzer.
Fix: add the section name to `STYLE_SECTIONS` in `scripts/analyze_and_update_style.py` whenever introducing a new section in style.md.

### `###` subsection format is not parsed by `parse_style_md()`
`parse_style_md()` only recognizes `## heading` lines. Any `###` subsections (e.g., `### 操作步骤型`) are treated as body text. A full rebuild would lose the `###` hierarchy. Prefer flat `- bullet` points under each `##` section.

### Editing CRLF-encoded Python scripts on Windows
`fetch_wechat_article.py` and `analyze_and_update_style.py` are stored with Windows CRLF line endings on disk. The `patch` tool's write verification can fail because it normalizes line endings differently from Python's file read/write.

Workaround: use Python inline scripts to write file changes:
```python
with open('/path/to/script.py', 'r', encoding='utf-8') as f:
    content = f.read()
content = content.replace('old', 'new')
with open('/path/to/script.py', 'w', encoding='utf-8', newline='\n') as f:
    f.write(content)
```

### WeChat HTML uses \x22 instead of &quot;
微信文章 HTML 用 `\x22` 表示引号，不是标准 HTML 实体。直接用 `html.unescape()` 解码后正则匹配会失败。必须做字符串替换后再匹配。详见「排版格式分析详解」。

### fetch_wechat_article.py 默认输出目录（历史坑位）
早期版本 `-o/--output-dir` 默认值是 `.`（当前工作目录）且**无任何校验**——在 `scripts/` 目录下运行且不加 `-o` 时，文章会直接落在 `scripts/` 下，导致目录结构混乱（已发生）。

**现状**：默认目录已是 `<repo>/reference`；传入的 `-o` 路径若不以 `reference` 结尾，会自动追加 `reference/`，不会再写进仓库其他位置。风格分析（`aggregate_style.py`）默认也从 `<repo>/reference/{主题}/` 读语料，两端对齐。

**手动调用**：一般不用传 `-o`；要存到别处时显式指定并以 `reference` 结尾：
```bash
python scripts/fetch_wechat_article.py "URL" -t "主题" \
  -o /path/to/reference
```

## 参考文档

- `references/style-analysis-guide.md` — 9维分析详解、微信图片提取陷阱、数值型bullets去重逻辑
- `references/articles/{主题}/style.md` — 各主题风格指南
