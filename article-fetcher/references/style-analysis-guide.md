# 风格分析指南



## 9+1 个分析维度（9个自动 + 1个手动 section）

每个分析维度对应 style.md 的一个 section（共9个，自动分析）：

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


**+1 个手动 section「特色」**：不属于自动分析，由人工在预置 style.md 中维护，记录特定主题特有的格式规范（如 emoji、引用符号、特定词汇偏好等）。



## 去重逻辑



- 同一 section 内的 bullet point 去重比较：**小写化后比较**

- 逻辑：`if p.lower() not in existing_lower`

- 适用：大小写不同/全角半角差异/标点变体等场景



## HTML 清理（关键）



`analyze_and_update_style.py` 的 `strip_html()` 函数必须按以下顺序处理，否则段落计数会严重偏差：



1. **先删 `<script>`、`<style>`、`<noscript>` 块**（用 `re.DOTALL` 正则）

2. **再把块级标签替换为 `\n`**（`</p>`、`</div>`、`<br>` 等），保留段落结构

3. **最后删剩余标签**，并将多个空格合并为1个



❌ 错误顺序：直接 strip 所有标签 → CSS/JS 内容混入正文 → 段落数从正常值变成几万

✅ 正确：`re.sub(r'<script[^>]*>[\s\S]*?</script>', '', text)` 先执行



## 数值型 bullets 去重



分析结果中包含动态数值的 bullets（如"全文约191个段落"、"标题长度约22字"、"配图约21张"）不能依赖 exact match 去重，因为每次跑的数值不同。



**解决方式**：在 `update_style_md()` 中，对以「全文约」「标题长度约」「配图约」开头的 bullets，用 prefix-based 替换而非追加：

- 重点：替换是按「组」做的，同组旧值被删除，不同组互不影响（如「使用单一强调色」和「重点色」各自独立）
- 强调色归一为灰色系：任意 r==g==b 的 rgb 统一写成「灰色(rgb(...))」，避免每篇写出不同灰阶值

- 新的来 → 先删旧的所有同类 prefix → 再追加新的

- 其他 bullets 仍走小写去重逻辑



## 预置风格指南来源



「科技热点分析」内置 style.md 源自 `article-writer/references/style-guide.md`（12篇公众号文章学习总结，2026-05-13）。



如需更新内置风格，以同样格式追加到各 section 即可。



## 语料聚合

单篇分析产出的「全文约N个段落」「标题长度约N字」「配图约N张」「使用单一强调色：某色」只描述那一篇，按单篇学习会让它们变成不公开的结论。

`aggregate_style.py` 重新分析主题下全部文章，把这些 bullet 换成语料均值（带「语料均值，N篇」标注），强调色与配图类型则变成频次统计。

每学完若干篇跑一次，不要每篇都跑。

### 编译稿不进语料

编译/编辑稿的句式是翻者的，不是原作者的，会把语料统计带偏。`aggregate_style.py` 按特征词（全文编译、本文编译、编译自、译文、翻译自）自动跳过，并打印 `Skipped:` 以便核对。

**不要用「转载」作为特征词**：微信页底部的「转载」按钮是 UI 噪音，会误判。自动识别不了的，在 `<topic>/exclude.txt` 里手工列出。

## 分析脚本调用方式



```bash

# fetcher 抓取（不保存 .txt，直接从 HTML 提取正文和图片）

python scripts/fetch_wechat_article.py "URL" -t "主题" -w 8 \

  -o ~/.hermes/skills/article-fetcher/references/articles



# 分析风格并更新（--images 传入图片元数据路径）

cat /path/to/article.html | python scripts/analyze_and_update_style.py \

  "主题" "文章标题" "URL" --images /path/to/article_images.json

```



## 微信公众号图片提取：关键陷阱



**问题**：微信公众号文章的图片是 JS 懒加载，HTML 源码里的 `<img>` 标签 `src` 是占位符（如 `'.concat(...)'`），真实 URL 在 `data-src` 属性中，只在 JS 执行后才填充。



**错误方式**：

- 静态解析 HTML → `src` 是 JS 代码片段，不是真实 URL

- `inner_html('#js_content')` → 返回 inner content 不含 `<section>` 标签本身，导致自定义 parser 的 `in_js_content` 标志永远进不去，图片全部被跳过



**正确方式**：用 Playwright 的 `page.evaluate()` 直接查 DOM：



```python

image_data = page.evaluate("""

    () => {

        const jsContent = document.getElementById('js_content');

        if (!jsContent) return [];

        const imgs = jsContent.querySelectorAll('img');

        return Array.from(imgs).map((img, i) => ({

            url: img.dataset.src || img.dataset.original || img.src || '',

            index: i,

            width: img.naturalWidth || img.width || 0,

            height: img.naturalHeight || img.height || 0,

            className: img.className || '',

            dataType: img.dataset.type || '',

            alt: img.alt || ''

        })).filter(img => img.url && !img.url.startsWith('data:'));

    }

""")

```



**wait_time 要足够**（建议 8 秒），确保 JS 执行完毕、`data-src` 完全填充后再提取。



## 注意点



- 空内容不会写入 style.md，直接跳过

- URL 相同时不会重复创建 index 条目

- style.md 每学一篇重建一次（parse → merge → rewrite）

- fetcher 不保存 `.txt` 文件；分析器的 `content_file` 参数可选，省略则从 stdin 读取 HTML 内容

- `update_style_md()` 中数值型 bullets（以「全文约」「标题长度约」「配图约」开头）走 prefix-based 去重



## 已发现的问题（须避免复现）



### STYLE_SECTIONS 必须与 style.md 同步

`update_style_md()` 按 `STYLE_SECTIONS` 顺序重建 style.md。如果 style.md 增加了新 section（如 `## 教程类型`）但 `STYLE_SECTIONS` 列表没有同步更新，该 section 会在**下次重建时丢失**。



每次在 style.md 中新增 section 时，必须同步更新 `scripts/analyze_and_update_style.py` 中的 `STYLE_SECTIONS` 列表。



### `###` 子标题格式不被 parse_style_md() 识别

`parse_style_md()` 只识别 `## heading`，`### subsection` 会被当作正文丢弃。当前 `style.md` 中 `## 教程类型` 下的两个子类型（`### 操作步骤型` / `### 案例展示型`）能保留，纯属侥幸——它们夹在 `##` 标记之间，作为普通文本幸存下来，但任何一次完整重建都会使其消失。



**不要依赖 `###` 做关键结构分层**。如需在 section 下组织子类型，优先使用 flat `- bullet` 列表，或扩展 `parse_style_md()` 支持 `###` 解析。

