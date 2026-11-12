# We-media-pipeline

把一条 AI 新闻变成**一篇公众号长文 + 一条竖版视频**的自动化流水线。

不是"一键生成"：它把写作拆成搜新闻、写稿、审稿、去 AI 味、配图、排 Word、写分镜、出片、进草稿箱这些环节，每一步都有产物落盘，可以在任何一步停下来人工看。

支持两套运行时——Claude Code（`.claude/workflows/`）和 DSH（`.dsh/workflows/`）。只用 DSH 的话直接看 [.dsh/START-HERE.md](.dsh/START-HERE.md)。

---

## 一条片子会留下什么

```
<output>\<topic>\
├── 01_search_results.md     搜到的候选新闻 + 链接
├── 03_article.md            公众号长文（1500+ 汉字）
├── 05_<标题>.docx           排好版的 Word 稿（公众号后台直接导入）
├── images_good/             配图与数据图
├── 06_content.json          视频摘要（三段 + 大标题）
├── 06_storyboard.json       分镜（六镜，每镜旁白/画面/时长）
├── 08_eac_handoff.json      交给 EAC 的镜头清单（派生产物）
├── cards/                   六张竖版卡片
├── 07_video.mp4             成片
└── review.jpg               12 帧审片表
```

---

## 流程

```
选题/搜新闻 ──> 写长文 ──> AI 审稿 ──> 去 AI 味 ──┐
                                                  ├─> 配图 ──> Word 稿
                                                  └─> 分镜 ──> 校验 ──> 交接文件 ──> EAC 渲染 ──> 成片
                                                                                        │
                                                          公众号草稿箱 <────────────────┘
```

拆成四段，因为 DSH 没有断点续跑——产物落盘就是断点，挂了只重跑那一段。

### 第 1 段：研究（`01-research.js`）

| 阶段 | 做什么 | 产物 |
|---|---|---|
| Search | 用秘塔/Tavily 搜近期 AI 新闻，或从 AIHOT 选题池挑 | `01_search_results.md` |
| Article | 逐篇读原文，写成公众号长文 | `02_raw_article.md` |
| Review-Article | AI 评审判定，最多 5 轮重写 | — |
| DeAI | 去掉 AI 腔（排比、空洞总结、过度对仗） | `03_article.md` |

**闸门**：文章必须基于原文链接，不许照抄聚合站摘要。

### 第 2 段：素材（`02-assets.js`）

小黑风格配图 → 通用插图 → 数据图 → PPT 截图 → 下图 → 排 Word 稿。

**闸门**：模型只画画面不画字，中文标注由脚本叠加——保证文字 100% 正确。

### 第 3 段：视频（`03-video.js`）

| 阶段 | 做什么 | 产物 |
|---|---|---|
| Summarize | 长文压成三段摘要 | `06_content.json` |
| Review-Summary | 摘要的字数与结构校验 | — |
| Storyboard | 写六镜分镜 | `06_storyboard.json` |
| Review-Storyboard | 五问盲读（只看旁白），必须 verdict=clear | — |
| Video | ≤12s 走模板线；>12s 只出交接文件 | `08_eac_handoff.json` |

**三道闸门**（必须真跑，不是口头声称）：

1. `validate_storyboard.py` —— 首镜不许是数字、字数预算、相邻镜头类型、视觉节奏
2. 五问盲读 —— 谁 / 何时 / 发生了什么 / 为什么 / 所以呢 + 末镜落到读者身上，`partly` 一律打回
3. `build_handoff.py --verify` —— 分镜改过没重生成交接文件，这里会报「第 N 镜：字段 X 期望…实际…」

### 第 4 段：出片（EAC，不是 workflow）

workflow 脚本只有 `agent` / `phase` / `log` / `args` 几个 hook，**调不到 MCP**，所以视频线止于交接文件。真正的渲染在 EAC 会话里做：

```
eac_project_create  →  画卡片  →  eac_asset_import  →  eac_job_submit(voice)
   →  按旁白实测时长定切点  →  eac_job_submit(compose)  →  eac_timeline_update  →  eac_job_submit(render)
```

### 第 5 段：发布（`04-publish.js`）

推进公众号草稿箱。**个人未认证订阅号没有发布权限**，最后一步人工点。

---

## 依赖

### 环境

| 需要 | 版本 | 用途 | 必须吗 |
|---|---|---|---|
| Python | 3.10+ | 所有脚本 | 必须 |
| Node.js | 18+ | HyperFrames 模板线（≤12s 视频） | 可选 |
| EAC design world 插件 | — | 出片、配音、配乐 | 出视频必须 |
| Git | — | workflow 用 `git rev-parse` 找项目根 | 必须 |

### Python 包

```bash
pip install -r requirements.txt
```

```
requests>=2.28.0      抓网页、调 API
pillow>=10.0.0        画卡片、叠字
matplotlib>=3.7.0     数据图
plotly>=5.17.0        交互图表
pytest>=7.0.0         测试
```

另外几个脚本用到 `python-docx`（Word）、`beautifulsoup4`（解析 HTML），装的时候一起：

```bash
pip install python-docx beautifulsoup4
```

### 外部服务与密钥

能跑的**最小集**是零密钥——AIHOT 选题池免 Key，EAC 出片不需要外部 API。要完整功能才需要下面这些：

| 变量 | 服务 | 用途 | 缺了会怎样 |
|---|---|---|---|
| `METASO_API_KEY` 或 `TAVILY_API_KEY` | 秘塔 / Tavily | 搜新闻（秘塔优先，失败回退 Tavily） | Search 阶段失败，改用 AIHOT 适配器 |
| `AGNES_API_KEY` / `ZAI_API_KEY` | agnes / 智谱 GLM | 生成配图（provider 链，先成功者胜） | 跳过 AI 生图，用手工卡片 |
| `WECHAT_APP_ID` / `WECHAT_APP_SECRET` | 微信公众号 | 推草稿箱 | 发布阶段跳过，不报错 |
| `WECHAT_AUTHOR` | 微信公众号 | 作者署名（限 8 字节 ≈ 2 汉字） | 用默认值 |
| — | [AIHOT](https://aihot.news) | 选题池 + 原文链接 | 只能手动给选题 |

密钥优先级：**环境变量 > 项目 `config.json` > skill 本地 config > 代码默认值**（都走 `shared/config_loader.py`）。

### EAC 需要的插件能力

出片这条线依赖这些 MCP 工具，缺任何一个都跑不完：

| 工具 | 用途 |
|---|---|
| `eac_status` | 确认插件在线、能力可用 |
| `eac_project_create` | 建 1080×1920 项目 |
| `eac_asset_import` | 导入卡片 |
| `eac_job_submit` | `voice`（配音）/ `compose`（配乐）/ `render`（渲染） |
| `eac_timeline_update` | 排镜头、字幕、配乐 |
| `eac_job_status` | 轮询任务终态 |

配音音色固定 `mambo-zh`（曼波中文，GPT-SoVITS），中文 TTS 吃不了拉丁字母和 `%`——所以旁白里的数字必须写中文读法。

---

## 配置

所有旋钮在根目录 `config.json`：

```json
{
  "default_output_dir": "<output>",
  "brand": {
    "name": "AI不够酷",
    "logo_image": "",
    "mode": "text"
  },
  "image_provider_chain": ["glm", "agnes"]
}
```

| 字段 | 说明 |
|---|---|
| `default_output_dir` | 产物根目录，每条片子落 `<根>/<topic>/`。**不要写死路径**，一律走 `config_loader` |
| `brand.name` | 品牌文字 |
| `brand.logo_image` | logo 图路径（相对仓库根），留空退回文字 |
| `brand.mode` | `text` / `logo` / `both` |
| `image_provider_chain` | 生图 provider 顺序，先成功者胜 |

品牌也能用环境变量临时覆盖（优先级高于 `config.json`）：`BRAND_NAME`、`BRAND_LOGO_IMAGE`、`BRAND_MODE`，以及 `BRAND`（整段 JSON 字符串，覆盖全部字段）。适合试方案时不动配置文件。

改品牌看下面「怎么改品牌」一节。

---

## 怎么跑

把 [.dsh/PROMPT-FULL-RUN.md](.dsh/PROMPT-FULL-RUN.md) 里的整段提示词贴进新会话，改一下议题方向。

想手动控制就按 01 → 02 → 03 → 04 顺序跑，每段的调用方式见 [.dsh/START-HERE.md](.dsh/START-HERE.md)。

---

## 怎么改品牌（水印）

品牌出现在卡片左上角和视频结尾，由 `config.json` 的 `brand` 段控制，**不需要改代码**。

**1. 改配置**

```json
"brand": { "name": "新品牌名", "logo_image": "assets/logos/新logo.png", "mode": "both" }
```

**2. 先看预览，别直接渲片**

```bash
python we-media-pipeline/scripts/brand.py --preview %TEMP%/brand.png
python we-media-pipeline/scripts/brand.py --preview %TEMP%/brand.png --mode both --logo "assets/logos/新logo.png"
```

预览是 1080×240 白底图，字号、logo 高度、留白对不对一眼能看出。命令行参数优先级高于配置，可以拿它试方案。

**3. 重画卡片**（品牌是烘进图片的，不是图层）

```bash
cd <输出根>/<topic>/cards && python make_cards.py
```

**4. 重新导入 + 重渲**（卡片换了，EAC 里的素材也要换）

三个坑：

- logo 会**等比缩到 44px 高**，竖版或比例怪的图会糊；建议横版透明 PNG，至少 132px 高。
- 仓库自带的 `ai_not_cool_logo.png` 上写的是 "Awesome Intelligence"，跟品牌名对不上，换品牌顺手换掉。
- 模板线水印是「关注 {name}」、PPT 页脚是 `{name}`，读同一段配置，改一处全生效。

---

## 目录结构

| 目录 | 是什么 |
|---|---|
| `.claude/workflows/` | Claude Code 版流水线（YAML） |
| `.dsh/workflows/` | DSH 移植版（JS）+ 运行说明 |
| `Docs/` | 分镜规范等设计文档 |
| `shared/` | `config_loader.py` —— 配置唯一入口 |
| `we-media-pipeline/scripts/` | 主脚本：校验、生成、排版、发布 |
| `we-video-generator/` | 模板视频引擎（legacy PIL + HyperFrames） |
| `ai-tutorial-video/` | 独立的教程视频线 |
| `news-searcher/` `article-writer/` `image-searcher/` | 手动工具，各自的 `SKILL.md` 是说明书 |
| `baoyu-*` | 第三方配图/信息图技能 |
| `tests/` | pytest |

---

## 文档索引

| 文件 | 讲什么 |
|---|---|
| [.dsh/START-HERE.md](.dsh/START-HERE.md) | 新工作区怎么跑、两个必踩的坑、出错对照表 |
| [.dsh/PROMPT-FULL-RUN.md](.dsh/PROMPT-FULL-RUN.md) | 从搜新闻到出成片的完整提示词 |
| [.dsh/workflows/README.md](.dsh/workflows/README.md) | DSH 移植层的格式差异 |
| [Docs/storyboard-spec.md](Docs/storyboard-spec.md) | 分镜字段与 R1–R10 判定口径 |
| [CLAUDE.md](CLAUDE.md) | 全部工程约定（产物编号、发布规则、视频叙事规范） |

---

## 已知限制

- **DSH 没有断点续跑** → 拆成四段，产物落盘即断点。
- **`5.5 字/秒` 只是写稿估值** → 实测 4.6–5.6 浮动，定稿前必须 TTS 实测、按实测排。
- **字幕单行 ≤24 汉字**（1080 宽 / 40px）→ 36 字会被切边。
- **公众号只到草稿箱** → 个人未认证订阅号没有发布权限。
- **中文 TTS 吃不了拉丁字母、`%`、阿拉伯数字** → 旁白必须写中文读法，型号放画面。
- **分镜里的数字必须能算出分母** → 「总量涨二十多倍」这种口径混了的说法，读者会拿计算器验。
