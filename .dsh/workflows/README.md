# 在 DSH 里跑 We-media-pipeline

这是 `.claude/workflows/run-pipeline.yml` 的 DSH 移植版，面向**只用 DSH、不装 Claude Code** 的人。
产物路径、文件名、编号（`01_`…`08_`）与原流水线一致；改动只有三处：脚本格式换成 DSH 的 workflow 体、
一条 1 小时的流水线拆成四段、去掉 `resumeFromRunId` 与阶段缓存。

当前目录实际内容：

| 文件 | 状态 |
|---|---|
| `01-research.js` | 已有（研究线） |
| `02-assets.js` | 已有（素材线） |
| `03-video.js` | 已有（分镜视频线） |
| `04-publish.js` | 已有（发布线） |
| `05-tutorial.js` | 另一条线（`tutorial-video.yml` 的移植），与 01→04 无关，单独跑 |

---

## 1. 为什么不能直接用 `.claude/workflows/*.yml`

两个运行时的**接口不一样**，不是换个扩展名就能跑：

| 维度 | `.claude/workflows/*.yml`（Claude Code） | `.dsh/workflows/*.js`（DSH） |
|---|---|---|
| 文件形态 | ES module，开头 `export const meta = {...}`，靠 Workflow 工具的 `scriptPath` 载入 | 纯 JS body：可写 `const`、顶层 `await`，结尾 `return {...}` |
| meta 位置 | 代码里的 `export const meta` | 第 1 行注释 `// META: {json}`，调用时复制成工具的 `meta` 参数 |
| 可用 hook | `agent` / `phase` / `log` / `args`（本仓库 yml 只用到这四个），另有调用方参数 `resumeFromRunId` 与阶段缓存 | 只有 `agent(prompt,{schema,label,phase})`、`phase(title)`、`log(msg)`、`args`、`parallel`、`pipeline`；**没有** resume、没有缓存 |
| 断点续跑 | 失败后带 `resumeFromRunId` 重启，已完成阶段走缓存 | 不支持；只能整段重跑，靠产物落盘当断点（见第 4 节） |
| 子代理工具名 | 子代理提示里写 `Read` / `Write` / `Bash` / `Edit` / `Glob` / `Grep` | 子代理的工具是 读取 / 写入 / pwsh 运行 / 编辑；本目录脚本的提示词已按这套中性名改写 |
| 参数入口 | `Workflow({ scriptPath, args })` | `workflow({ meta, script, args })`，`args` 从 `// ARGS:` 那行取 |
| schema 支持 | 较宽的 JSON Schema | 仅子集：`type` / `properties` / `required` / `additionalProperties` / `items` / `enum` / `const` / `oneOf` |

直接照搬会出两种错：一是 `export` 语句在 DSH 的 script 里是语法错误，整段跑不起来；
二是即使删掉 `export`，脚本里假设的 `resumeFromRunId`、阶段缓存、`Read/Bash` 工具名在 DSH 都不存在，
子代理会找不到工具或行为跑偏。

另外一条实测坑：`meta.phases` 的每一项**必须是对象** `{"title": "..."}`，
写成字符串数组 `["Publish"]` 会被工具直接拒：`invalid arguments: "meta.phases[0]" must be an object`。

---

## 2. 怎么在 DSH 里跑

每段都是同一个动作：**取三样东西，交给 `workflow` 工具**。

1. 读取 `.dsh/workflows/0X-*.js` 的完整内容；
2. 取第 1 行 `// META:` 后面的 JSON → 工具的 `meta`；
3. 取 `// ARGS:` 那行后面的 JSON → 工具的 `args`（按本次选题改值）；
4. 文件余下的正文 → 工具的 `script`（顶层 `await` 和结尾 `return` 都保留）。

形状大致是：

```
workflow({
  meta:   {"name":"04-publish","description":"...","phases":[{"title":"Publish"}]},
  script: "<04-publish.js 的正文>",
  args:   {"topic":"某选题","output_dir":"","publish":true}
})
```

注意：

- `read` 工具返回的内容带行号，粘进 `script` 前要去掉行号，否则不是合法 JS。
  偷懒也可以把整份文件当 `script`——`// META:` 和 `// ARGS:` 本身是注释，不影响语法；但 `meta`/`args` 仍要单独取。
- 同一轮流水线的四段，**`topic` 与 `output_dir` 必须完全一致**，否则下一段找不到上一段的产物。
- `output_dir` 是**输出根目录**，不是项目子目录；项目子目录由 `topic` 拼出来（`<输出根>/<topic>`）。
- `output_dir` 留空时走 `config.json` 的 `default_output_dir`。本仓库没有 `config.json`（被 `.gitignore` 忽略），
  所以会回落到 `shared/config_loader.py` 的默认值：桌面下的 `自媒体输出`（即 `E:\Desktop\自媒体输出`）。
- 产物不许落进代码仓库，01/02/04 都有守卫会直接报错。

### 01→04 的顺序、输入与产物

| 顺序 | 文件 | 主要输入 | 落盘产物 |
|---|---|---|---|
| 1 | `01-research.js`（已有） | `topic`、`output_dir`、`days`、`num_results` | `01_search_results.md`、`01_news_images.json`、`02_raw_article.md`、`03_article.md` |
| 2 | `02-assets.js`（已有） | `topic`、`output_dir`、`article`（默认 `03_article.md`） | `images-all/`（候选池）、`images_good/`（入选图 + `diagram_*.png`）、`images_good/ppt_slides/`、`05_文章标题.docx` |
| 3 | `03-video.js`（已有） | `03_article.md`（事实源）、`topic`、`duration` | `06_content.json`、`06_storyboard.json`；时长 >12s 时另出 `08_eac_handoff.json`，≤12s 的模板线出 `07_video.mp4` |
| 4 | `04-publish.js`（已有） | `03_article.md`、`images_good/`、`publish` | 公众号后台草稿箱里的一条草稿（返回 `media_id`、实际标题、`stage`） |

每段返回的 JSON 里都带完整路径字段（`output_dir`、`article_file`、`word_file`、`ppt_cover`、`publish_media_id` 等），
下一段可直接照抄。任一段想单独重跑，把同样的 `args` 再交一次就行。

> 原文里**没有**独立的 `diagrams/` 目录：数据图落在 `images_good/diagram_*.png`，_work 只放中间件。
> 看到 `images-all/` 与 `images_good/` 两个目录就对了，前者是没采用的候选池。

---

## 3. 四条线的分工与产物

| 线 | 脚本 | 阶段 | 产物 | 人工介入点 |
|---|---|---|---|---|
| 研究线 | `01-research.js` | Search → Article → Review-Article → DeAI | `01_search_results.md`、`01_news_images.json`、`02_raw_article.md`、`03_article.md` | 审稿最多自动重写 5 轮；`human_review: true` 时在审稿前停 |
| 素材线 | `02-assets.js` | Xiaohei → Illustrate → Diagram → PPT → ImageDownload → Word | `images-all/`、`images_good/`（含 `diagram_*.png`）、`images_good/ppt_slides/`、`05_文章标题.docx` | 图片报废就重跑本段；`slide_01.png` 就是封面，别改名别换顺序 |
| 分镜视频线 | `03-video.js` | Summarize → Review-Summary → Storyboard → Review-Storyboard → Video | `06_content.json`（旁白）、`06_storyboard.json`（分镜）、`08_eac_handoff.json` | 五问闸门不过就打回重写；12 秒是模板线/EAC 线的分界 |
| 发布线 | `04-publish.js` | Publish | 公众号草稿箱里的草稿 | 最后一步在公众号后台手动点“发布” |

发布线的四条硬规则（移植时原样保留）：

1. 个人未认证订阅号**只到草稿箱**：脚本不加 `--publish`，加了也没用（`freepublish` 权限已收回，报 48001）。
2. 缺 `WECHAT_APP_ID` / `WECHAT_APP_SECRET` 时**跳过不报错**：返回 `publish_stage: "skipped"`。
3. `publish: false` 整段关掉，不碰微信接口。
4. 封面优先 `images_good/ppt_slides/slide_01.png`，没有再从 `images_good/news_*.jpg` 里挑横图；都没有就报
   `no cover candidate` 并给出手动命令——微信草稿不带封面会直接失败。
5. JSON 里的中文必须是 UTF-8 明文（`json.dumps(ensure_ascii=False)`），用 `\uXXXX` 转义微信不解码，草稿会全是乱码。

发布失败不会回滚前 3 段：重试 3 次后置 `publish_stage: "failed"`，并在日志里留一条手动命令。

---

## 4. 为什么拆成四段

因为 DSH **没有** `resumeFromRunId`，也没有阶段缓存。

整条流水线跑一次约 1 小时 / 30 万 token。原来挂在第 13 个阶段（视频）上，带 `resumeFromRunId` 重启只重跑断点；
在 DSH 里同样的失败只能从 Search 重来，重来还要再烧一次 30 万 token——一次偶发 429 就赔掉整条。

拆开后的收益是“产物落盘即断点”：

- 文章改一句，只重跑 `04-publish.js`，不用重新搜索、配图、做视频；
- 图片报废，只重跑 `02-assets.js`，它自己会复用已生成的图，缺什么补什么；
- 分镜五问不过，只重跑 03 段，`06_content.json` 和文章都还在。

代价是四段之间**没有共享内存**，只靠目录和文件名衔接：`args` 必须对齐（同 `topic` + 同 `output_dir`），
上一段的产物被手动改名或挪走，下一段就会找不到。段与段之间宁可多跑一次 setup agent 重新解析路径，也不做隐式依赖。

---

## 5. 视频线在 DSH 里到哪为止

**到 `08_eac_handoff.json` 为止。**

- `06_content.json`：旁白文本与镜表（写稿用 5.5 字/秒估字数，定稿前必须 TTS 实测回填时长）。
- `06_storyboard.json`：分镜，过五问闸门（谁 / 什么时候 / 发生了什么 / 为什么 / 所以呢 + 句间承接 + 末镜落到读者）。
- `08_eac_handoff.json`：**交接单**，把时长、镜号、旁白、画面要求、素材交给 EAC 精品线。

真正的渲染在 EAC 侧，用 EAC 的 MCP 工具完成：`eac_project_create` 建项目 → `eac_asset_import` 导入素材 →
`eac_job_submit`（voice / beats / render …）跑任务。这些 MCP 工具**在 DSH 的 workflow 脚本里调不到**——
workflow 的 script 只有 agent / phase / log / args 几个 hook，没有 MCP 通道。所以视频线的终点就是交接单，
剩下的必须在 EAC 会话里做。

---

## 6. 已知限制

- **无断点续跑**：DSH 没有 `resumeFromRunId`，段内失败只有脚本自己的 `MAX_RETRIES = 3` 重试；再失败就整段重跑。
- **`agent` 的 schema 只支持子集**：`type` / `properties` / `required` / `additionalProperties` / `items` / `enum` / `const` / `oneOf`。
  用了别的关键字（如 `pattern`、`format`、`minimum`）不会生效，写成非法 schema 会直接终止整个脚本。
- **脚本内没有文件系统**：读文件、写文件、跑 python、`git rev-parse` 全部由子代理代劳。所以每段开头都有一个
  setup agent 解析路径——这步本身要花 token，也别指望脚本能自己 `fs.existsSync`。
- **工具名是中性化的**：子代理实际只有 读取 / 写入 / pwsh 运行。它有时仍会用 `Read`/`Bash` 的旧词描述动作，
  以实际工具为准。
- **速率限制**：子代理撞 429 属于偶发，重试即过；同一段连续失败，先看是不是 `python` 或 API key 的问题，再重跑。
- **发布线不自动发布**：个人未认证订阅号没有 `freepublish` 权限，草稿进后台后必须人工点发布。
- **四段之间是文件名契约**：没有共享状态，改 `topic` 或挪产物，下一段就断链。
