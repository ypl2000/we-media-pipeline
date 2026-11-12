# 在新工作区里跑这条流水线

> 先读仓库根的 [README.md](../README.md)——仓库是干什么的、依赖、配置、品牌都在那儿。这份只讲「怎么在新会话里把它跑起来」。

## 前提（缺一样就跑不通）

1. **EAC design world 插件连上**——视频线要用它渲染、配音、配乐。新会话先让 agent 调一次 `eac_status`，看得到能力清单才算连上。
2. **python 在 PATH**——`validate_storyboard.py`、`build_handoff.py`、`config_loader.py` 都靠它。
3. **工作目录在仓库里**（或仓库子目录）：脚本用 `git rev-parse --show-toplevel` 找项目根，不在 git 仓库里会直接报错。
4. **`config.json` 里 `default_output_dir` 已配**——没配会回退到 `~/Desktop/自媒体输出`，产物就散到桌面去了。

## 最短路径：一句话让 agent 自己跑

**从选题出视频，要跑两段**（01 出稿，03 出分镜）。把这两句贴给新会话，topic 保持一致：

> 第一步：读 `<repo>\.dsh\START-HERE.md` 和 `.dsh\workflows\01-research.js`，按「怎么跑」把 01 跑完，args 用 `{"topic":"我的选题"}`。

跑完之后：

> 第二步：同样方式跑 `03-video.js`，topic 必须还是 `{"topic":"我的选题"}`，不要改。

只跑 `03-video.js` 的前提是 `<输出根>\<topic>\03_article.md` **已经存在**——它不会自己去搜新闻写稿。

要配图和 Word 稿再加一段 `02-assets.js`；要进公众号草稿箱再加 `04-publish.js`。顺序永远是 01 → 02 → 03 → 04，02 和 03 之间没有依赖，可以只跑 03。

**注意文件后缀是 `.js`**（DSH workflow 脚本是 JS），`.json` 只是数据产物。

## agent 实际要做的三步

`workflow` 工具要三样东西，都在文件里：

1. 读整份 `.dsh/workflows/0X-*.js`；
2. 第 1 行 `// META:` 后面那段 JSON → `meta`；
3. `// ARGS:` 那行后面那段 JSON → `args`（改 topic / duration / output_dir）；
4. 余下正文 → `script`。

偷懒写法：把**整份文件**原样当 `script` 传，`// META:` 和 `// ARGS:` 是注释，不影响语法；但 `meta` 和 `args` 仍要单独从注释里摘出来。

## 两个必踩的坑

- **`meta.phases` 必须是对象数组** `[{"title":"Search"}]`。传字符串数组会被工具直接拒：`"meta.phases[0]" must be an object`。
- **`read` 工具会带行号**。如果照着 read 的输出粘 `script`，第一行会变成 `1 const ...`，语法直接炸。要么用不带行号的方式取原文，要么整份文件当 script（见上）。

## 四条线的顺序与依赖

| 顺序 | 文件 | 产出 | 依赖 |
|---|---|---|---|
| 1 | `01-research.js` | `03_article.md` | 无 |
| 2 | `02-assets.js` | `images_good/`、`05_标题.docx` | 01 的稿 |
| 3 | `03-video.js` | `06_storyboard.json`、`08_eac_handoff.json` | 01 的稿 |
| 4 | `04-publish.js` | 公众号草稿 | 01 的稿 + 封面 |

**同一条线跑多段时，`topic` 和 `output_dir` 必须完全一致**，否则下一段找不到上一段的产物。`output_dir` 不传时走 `config.json` 的 `default_output_dir`（当前 `<output>`）。

`05-tutorial.js` 是独立的一条线，跟 01→04 无关，输入只有主题。

## 视频线到哪为止

`03-video.js` 产出 `08_eac_handoff.json` 就结束了——**它不渲染**。真正的成片要用 EAC 的 MCP 工具（`eac_project_create` → `eac_asset_import` → `eac_job_submit`），而 workflow 的 script 只有 `agent` / `phase` / `log` / `args` 几个 hook，**调不到 MCP**。

所以视频线实际是两段：
1. workflow 出分镜 + 交接文件；
2. EAC 会话里按交接文件排时间线、配音、渲染。

交接文件由 `build_handoff.py` 生成，渲染前必须 `--verify`，exit 0 才能渲。

## 出了错先看哪里

| 症状 | 大概率原因 |
|---|---|
| `Cannot find module` / 路径不存在 | 工作目录不在仓库里，`git rev-parse` 失败 |
| `meta.phases[0] must be an object` | phases 写成了字符串数组 |
| `SyntaxError: Unexpected number` | script 里混进了行号 |
| 产物落到了桌面 | `config.json` 的 `default_output_dir` 没配，走了兜底值 |
| 找不到上一段的产物 | 两段的 `topic` 或 `output_dir` 不一致 |
| 渲染出来字幕和旁白对不上 | 改过分镜没重跑 `build_handoff.py`，或没跑 `--verify` |

## 换品牌

品牌名、logo 和呈现方式都在 `config.json` 的 `brand` 段，脚本里不写死：

```json
"brand": {
  "name": "AI不够酷",
  "logo_image": "",
  "mode": "text"
}
```

- `name`：品牌名，卡片左上角、PPT 页脚、视频水印「关注 <name>」都读它
- `logo_image`：相对仓库根的图片路径；留空或文件不存在时，`logo`/`both` 自动退回 `text`
- `mode`：`text` 只画文字 / `logo` 只贴图 / `both` 图 + 字

改完先肉眼确认，再重画卡片、重渲视频：

```bash
python we-media-pipeline/scripts/brand.py --preview %TEMP%\brand.png
python we-media-pipeline/scripts/brand.py --preview %TEMP%\brand.png --mode logo --logo we-video-generator/assets/logos/ai_not_cool_logo.png
python we-media-pipeline/scripts/brand.py --preview %TEMP%\brand.png --mode both --name 测试品牌
```

预览是 1080×240 白底图，红条 / 文字 / logo 的位置与卡片一致。

