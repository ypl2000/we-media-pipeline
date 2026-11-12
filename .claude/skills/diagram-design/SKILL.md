---
name: diagram-design
description: 为公众号文章生成精确的数据配图——条形对比、流程、漏斗、时间线、嵌套结构、瀑布图，手写 HTML+SVG 后导出 1080 宽 PNG，中文文字 100% 准确、可以带具体数字。当需要给文章配"数据图/对比图/流程图/时间线/拆解图/漏斗图"，或用户要求"配图里要显示数字""图表插进文章"时使用。情绪图、概念插画、封面图不用这个技能。
---

# 公众号数据配图

手写 HTML + 内联 SVG，导出 PNG 插进公众号文章。**数字和中文 100% 准确**，这是它相对 AI 生成配图的全部意义。

上游项目：<https://github.com/cathrynlavery/diagram-design>（45 种图型，MIT）。本技能是它的**公众号精简版**：只保留用得上的类型，并把字号压到手机能看清的尺寸。

## 0. 什么时候用它

**用它**：段落里有具体数字要讲清楚——金额、比例、数量、时间点、对比、拆解、流程。
"半年封了 1140 万个账号，其中 39.8 万申诉、4.2 万成功"这种，一张图胜过三段话。

**不用它**：
- 情绪图、场景插画、封面 → `baoyu-image-gen`（AI 位图，画面好看但画不准字）
- 整页 PPT 幻灯片 → `html-ppt-chart`（16:9 幻灯片，不是正文配图）
- 概念解释 → AI 位图 + 中文标注叠加更快

两者互补：一张文章里，数据图用这个，情绪图用 AI 位图，认知点不要重复。

## 1. 硬约束（先读 `references/wechat-spec.md`）

| 项 | 值 |
|---|---|
| viewBox 宽 | **1080**（不是上游的 1000） |
| 导出 PNG 宽 | **1080**（`export_png.py <in> <out> 1`，scale=1） |
| 汉字最小字号 | **40px**（= 12.6 CSS px 手机端） |
| 标题 / 副标题 | 60px / 44px |
| 关键数字 | 48–56px |
| 数据元素（条/节点/时间点） | **≤ 4 个** |
| 文本节点总数 | **≤ 10 个**（标题 1–2 + 每元素最多 2 处） |
| 强调色 #bf4520 | **≤ 2 处** |
| 字体栈 | `'Microsoft YaHei', 'PingFang SC', 'Noto Sans SC', sans-serif` |
| 配色 | paper #f5f5f5 / ink #2d3142 / muted #4f5d75 / accent #bf4520 |

汉字不用 mono 字体（Geist Mono 无汉字，会错宽）。不用衬线排汉字。不要阴影/渐变/emoji。

**标题必须画在 SVG 里**——`export_png.py` 只截 `<svg>` 元素，HTML 里的 `<h1>` 不会进 PNG。

## 2. 类型 → 参考文档

| 要表达的东西 | 用 | 参考 |
|---|---|---|
| 两个以上数量的横向比较 | 条形图 | `references/type-bar.md` |
| 有先后顺序的阶段、转化链路 | 流程 / 漏斗 / 金字塔 | `references/type-flowchart.md`、`type-pyramid.md` |
| 随时间发生的事 | 时间线 | `references/type-timeline.md` |
| 比例、构成、包含关系 | 嵌套 / 分层 | `references/type-nested.md`、`type-layers.md` |
| 总量被几项加减拆开 | 瀑布图 | `references/type-waterfall.md` |

版式几何、网格预算、绘制原语：`references/output-spec.md`、`layout-budget.md`、`primitives-core.md`。
配色与排版令牌：`references/style-guide.md`。

## 3. 做法

1. **选段**：在文章里挑含具体数字的段落。上限 2–3 张图，多了读者会滑过去。
2. **抄模板**：`assets/template-wx.html`（通用三节点流程），或 `assets/examples/` 里接近的：
   - `bar-flow-wx.html` — 三节点流程 + 比例标注（公众号密度标准写法）
   - `bar-dense.html` — 四条横向对比（标签在左、数字右对齐成列，条在下方）
   - `timeline.html` — 时间线
   - `nested.html` — 嵌套结构（双层股权那种）
3. **改**：换文案和数字，删掉不需要的节点。**不要**为了塞内容而缩字号。
4. **校验**（两个都要跑）：
   ```bash
   python .claude/skills/diagram-design/scripts/self_check.py <file.html>            # 契约
   python .claude/skills/diagram-design/scripts/check_layout.py <file.html> --min-han 40   # 重叠/越界/小字
   ```
5. **导出**：
   ```bash
   python .claude/skills/diagram-design/scripts/export_png.py <file.html> <out.png> 1
   ```
6. **插图**：PNG 写到 `${输出目录}/images_good/diagram_01.png`（编号连续），在文章对应段落插一行：
   ```
   [[IMG: images_good/diagram_01.png]]
   ```

## 4. 容易踩的坑

- **图里出现的每个数字都必须来自原文**，不要自己推算或补充背景知识。
- **一张图只讲一件事**。想讲两件就拆两张。
- 删节点比缩字号好。上游允许 24 个节点，那是给 PDF 看的；公众号里 4 个数据元素、10 个文本节点是上限。
- 条形图的柱子宽度要诚实：等宽等距（除非是真按时间/比例排的）。
- 导出后确认 PNG 实际宽度是 1080（`python -c "from PIL import Image; print(Image.open(p).size)"`）。
- 临时文件放 `_work/`，不要 `rm -rf`。

## 5. 目录

```
.claude/skills/diagram-design/
  SKILL.md
  references/
    wechat-spec.md          ← 公众号尺寸规范（先读这个）
    style-guide.md          配色与排版令牌（上游）
    output-spec.md          版式与几何契约（上游）
    layout-budget.md        网格预算（上游）
    primitives-core.md      绘制原语（上游）
    type-*.md               8 种图型的版式语法（上游）
  assets/
    template-wx.html        公众号模板（1080 宽）
    examples/               4 张中文样例
  scripts/
    export_png.py           导出 PNG（上游）
    self_check.py           契约校验（上游）
    check_layout.py         文本重叠/越界/小字校验（本项目）
```
