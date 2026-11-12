# We-media-pipeline 自媒体流水线

从新闻选题 → 文章 → 配图 → 视频 → 公众号发布的全自动流水线。干活前先对照本文件的规矩。

## 产物输出（最重要）

- 所有产物写到 `config.json` 的 `default_output_dir` 下（当前为 `<output>`，别再写死桌面路径），按项目名建子目录。
- 代码一律用 `shared/config_loader.py` 的 `get_output_dir(子目录)` 取路径。禁止硬编码桌面/绝对路径，禁止把产物写进本仓库（loader 里有守卫，会报错）。
- 成片固定为 `<输出根>/<项目名>/07_video.mp4`，和 Word 稿（`05_文章标题.docx`）同放。
- 调试用的抽帧、截图、临时脚本一律写到系统临时目录（`%TEMP%`）或运行目录 `_work/`，不许留在仓库根目录。

## 配置读取

- 一切配置走 `shared/config_loader.py`（`get_config_value` / `get_output_dir` / 各 `get_*_api_key`），不要自己写读 config 的代码。
- 优先级：环境变量 > 项目 `config.json` > skill 本地 `config.json` > 代码默认值。
- API key 明文放项目 `config.json`（私有仓库，可接受）；新 key 统一加在这里，不散落到脚本里。

## 流水线入口

- 文章流水线：`.claude/workflows/run-pipeline.yml`；教程视频：`.claude/workflows/tutorial-video.yml`。用 Workflow 工具以 `scriptPath` 方式调用（未注册名字，`Workflow({name})` 找不到）。
- 产物按编号命名（`01_` 素材、`05_` 文章 docx、`07_` 视频 …），编号是流水线契约，不要改名。
- **workflow 是流水线的唯一事实源**；各目录的 `SKILL.md` 只是手动工具说明书，流水线不读它们，两者不一致时以 workflow 为准。
- workflow 跑一次约 1 小时 / 30 万 token，子代理可能撞 429 上限，**重试即过**；失败后带 `resumeFromRunId` 重启，已完成阶段走缓存，只重跑断点处。

### DSH 移植层（`.dsh/workflows/`）

只用 DSH、不装 Claude Code 时走这一层：`.claude/workflows/*.yml` 的移植版，**逻辑与产物契约完全一致**（`01_`…`08_` 编号不变），差别只有三处：`meta` 从 `export` 挪到文件头注释、子代理工具名中性化（读取 / 写入 / pwsh / 编辑）、没有 `resumeFromRunId` 与阶段缓存。→ 为什么：两套运行时接口不同，直接改扩展名会因 `export` 语法和缺 hook 跑不起来。细节看 `.dsh/workflows/README.md`。

| 文件 | 阶段 | 产物 |
|---|---|---|
| `01-research.js` | Search → Article → Review-Article → DeAI | `01_search_results.md`、`02_raw_article.md`、`03_article.md` |
| `02-assets.js` | Xiaohei → Illustrate → Diagram → PPT → ImageDownload → Word | `images-all/`、`images_good/`、`05_文章标题.docx` |
| `03-video.js` | Summarize → Review-Summary → Storyboard → Review-Storyboard → Video | `06_content.json`、`06_storyboard.json`；>12s 出 `08_eac_handoff.json`，≤12s 出 `07_video.mp4` |
| `04-publish.js` | Publish | 公众号草稿箱里一条草稿 |
| `05-tutorial.js` | Outline → ScriptQA → TTS → Compose → Check → Review → Render（七阶段） | 教程竖版 mp4；与 01→04 无关，单独跑 |

**怎么跑**：每段都是同一个动作——取三样交给 DSH 的 `workflow` 工具。

1. 读整份 `.dsh/workflows/0X-*.js`；
2. 第 1 行 `// META:` 后面的 JSON → `meta`；
3. `// ARGS:` 那行后面的 JSON → `args`（同一条线的几段必须同 `topic` + 同 `output_dir`，否则下一段找不到上一段产物）；
4. 余下正文 → `script`（顶层 `await` 和结尾 `return` 都保留）。

两个坑：

- `meta.phases` 每一项**必须是对象** `[{"title":"Publish"}]`；写成字符串数组会被工具直接拒（`"meta.phases[0]" must be an object`）。→ 为什么：schema 只认对象数组，字符串传进去连脚本都进不去。
- 用 `read` 读脚本会带行号，**粘进 `script` 前必须去掉行号**，否则不是合法 JS。（偷懒可以把整份文件当 `script`——`// META:` / `// ARGS:` 本身是注释不影响语法；但 `meta` / `args` 仍要单独取。）

**分工**：视频线在 DSH 里**止于 `08_eac_handoff.json`**。真正的渲染要用 EAC 的 MCP 工具（`eac_project_create` → `eac_asset_import` → `eac_job_submit`），而 workflow 的 script 只有 `agent` / `phase` / `log` / `args` 几个 hook，**调不到 MCP**。→ 为什么：硬调只会产出空跑记录，剩下的必须在 EAC 会话里完成。

**handoff 是派生产物**：`08_eac_handoff.json` 由 `we-media-pipeline/scripts/build_handoff.py` 从 `06_storyboard.json` 确定性生成（同一份分镜永远生成同一份，只有 `generated_at` 会变），**不要手改**；改稿后必须重跑生成，否则会静默过期。→ 为什么：手写的 handoff 改稿后就对不上了，渲染出来是旧镜头表还看不出来。

渲染前纪律：**先 `python we-media-pipeline/scripts/build_handoff.py <分镜路径> --verify`，exit 0 才能渲**；不一致会打印「第 N 镜：字段 X 期望…实际…」，照它改分镜再重新生成。→ 为什么：`--verify` 拿分镜的 sha256 和逐镜字段比对，是拦「拿旧 handoff 去渲」的唯一一道闸。

## 配图与视频约定

- 小黑风格配图用 agnes/glm 生图（provider 链在 `config.json` 的 `image_provider_chain`）：**模型只画画面不画字**，中文标注一律由脚本（overlay_labels）叠加，保证文字 100% 正确。
- 视频上传视频号/抖音后若画质发暗发虚：转码用 `yuv420p` 像素格式。
- 教程/科普视频统一**浅色背景**：场景根 `radial-gradient(ellipse at 50% 38%, #ffffff 0%, #e9ecf1 78%)`，正文 `#141519`、注释 `#4b5260`、浅底上的金字用 `#6f5700`（`#ffd700` 只做描边/装饰）。
- 品牌 logo 由脚本在根 composition 常驻顶部（y=80，210px 横幅），**场景里不要再放 logo**，结尾「点赞 · 关注」CTA 附近更不许有。
- 品牌名与 logo 由 `config.json` 的 `brand` 段控制（`name` / `logo_image` / `mode`），脚本不许写死；换品牌只改配置，**重画卡片、重渲视频**即可。
- 公众号排版走后台 docx 导入（格式全保真），不需要 Markdown→微信 HTML 工具。

### 公众号发布（实测规则）

- 账号「AI不够酷」是**个人未认证订阅号**：`draft/add` 存草稿可用，`freepublish` 发布权限已被收回 —— **流水线只到草稿箱，最后一步由人工在公众号后台点发布**。
- 发草稿用 `we-media-pipeline/scripts/wechat_draft.py`，封面用 `ppt_slides/slide_01.png`；缺 `WECHAT_APP_ID`/`WECHAT_APP_SECRET` 时跳过不报错，`publish: false` 可关。
- 微信接口字段限长**按 UTF-8 字节**算：标题 64B（≈21 汉字）、摘要 120B、作者 8B（≈2 汉字，超长报 45110）、正文 20000 字符。脚本会自动截断，但别给它超长值。
- JSON 里的中文必须 UTF-8 明文（`json.dumps(ensure_ascii=False)`），用 `\uXXXX` 转义微信不解码，草稿会全是乱码 —— 代码已处理，别改回去。

### 视频叙事规范（2026-11 增补）

2026-11 两版视频（9 秒 / 30 秒）翻车换来的规矩，写分镜和旁白时逐条对照。分镜文件的字段与 R1–R10 判定口径见 `Docs/storyboard-spec.md`。

1. **首镜必须是「谁 + 何时 + 发生了什么」**，不许以数字开头。反例：以「百分之四十一点三的活」开场，观众不知道 41.3% 是谁的。→ 为什么：前三秒没定位到主语，后面所有论据都成了无主数字，观众直接划走。
2. **五问闸门**：旁白文本必须能回答「谁 / 什么时候 / 发生了什么 / 为什么 / 所以呢」，任一答不上就打回重写；五问之外还要求**句间有承接**（因果/转折/递进/指代），拿「另外」「此外」把事实并排堆起来算不合格（R2b）；末镜的「所以呢」必须**落到读者身上**（R2c）——要有「你/你们」或读者能做的动作，只写机构能力、行业判断、厂商战略不算说完。→ 为什么：观众记住的是因果链和主线，不是并列清单；六句并列事实每句都能答出五问照样没主线，末镜只写「公司能自己托管」观众只会问「关我什么事」。
3. **语速用 5.5 字/秒**（曼波中文实测），不是 4.5；`duration_s × 5.5` 才是旁白字数预算。写 131 字只出 23.4 秒是实测结论。→ 为什么：按 4.5 估算会超时约 20%，等 TTS 跑完才发现，返工的是整条片子。（`tutorial-video.yml` 里的 `duration*4.5` 是旧值，本次只改文档；写稿按 5.5 算，超出的在 QA 轮裁掉。）**5.5 只是写稿估值，不是成片承诺**：端到端实测 176 汉字合成 37.84 秒（4.65 字/秒，实测区间 4.6–5.6），定稿前必须跑 TTS 实测、用实测值回填 `duration_s`。
4. **数字念法**：旁白里的数字必须写成中文读法（`41.3%` → `百分之四十一点三`），TTS 不能吃拉丁字母与符号。→ 为什么：`41.3%` 会被念成「四十一点三百分号」或直接吞掉，观众听到的和你写的不是一个东西。英文名/版本号放画面文字（`visual`），旁白念中文读法。
5. **时长路由**：≤12s 走模板线（9s 兼容），≥13s 走 EAC 精品线（MCP 工具、人在环，产出 `08_eac_handoff.json`）。→ 为什么：两条线的成本和上限差一个量级，中间留 13–19s 的灰区只会两边都做不好，所以按 12 秒一刀切，13s 起一律 EAC。
6. **画面节奏**：两条同时生效——① 相邻两镜视觉类型**不得相同**；② 相邻两镜不得都是「没人」画面（`chart`/`statement`），`chart` 接 `statement` 类型虽不同、两屏都没人，同样打回。另：每 3 镜至少 1 镜是 `event`/`order`（有人、有动作）。→ 为什么：同类画面连排像 PPT 翻页，类型不同但都没人的两屏同样让人掉线；两条一起才挡得住「数字密度高但没人」的片子。
7. **术语与口径**：术语按受众定——「AI 不够酷」的读者懂 token / 上下文 / agent，别为了「好懂」把这些词翻译掉，翻译反而显得外行；要卡的是**口径**：指代（「它」「总量」「四次」到底指什么）、分子分母与单位、倍数和基数的对应关系。→ 为什么：懂 token 的人照样会卡在「谁的四次、哪个总量、第三次是第几次」，把术语当硬伤去改，只会把片子改成给完全外行看的版本。

上屏与运镜另有两条硬规则，口径见 `Docs/storyboard-spec.md` 的 R8/R9：上屏单行 ≤24 个汉字（1080 宽、40px 字号；54px 下 33–38 字的长句会被截断）；运镜只用 `zoom-in`/`pan`，**禁用 `zoom-out`**（满画幅素材会在镜尾露黑边）。→ 为什么：这两条是端到端实跑踩出来的出片硬伤，不是审美偏好。

## 目录导航

| 目录 | 是什么 |
|---|---|
| `we-media-pipeline/` | 文章流水线的脚本（搜图/下载/校验/排版/PPT） |
| `article-fetcher` `article-writer` `image-searcher` `news-searcher` | 手动工具，各自的 SKILL.md 是说明书 |
| `we-video-generator/` | legacy 视频引擎；默认引擎是 HyperFrames 版（`run_video_generator_hf.py`） |
| `ai-tutorial-video/` | 教程科普视频工程 |
| `shared/config_loader.py` | 配置唯一入口 |
| `tests/` | pytest 测试（`python -m pytest tests/ -q`） |
