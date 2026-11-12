# 完整跑一遍：从搜新闻到出成片

把下面整段贴进新会话。**只需要改一处**：第一行的议题方向（不写就让 agent 自己从今天的 AI 新闻里挑）。

---

```
按 We-media-pipeline 的 DSH 移植层，从搜新闻开始跑一条完整流水线，最后出成片。

议题方向：<留空则从今天的 AI 新闻里自己挑，挑「读者今天就能用到或被直接影响」的>

## 开工前先读（按顺序，别跳）
1. <repo>\README.md      ← 仓库是干什么的、依赖、配置
2. <repo>\.dsh\START-HERE.md  ← 怎么跑、两个坑、出错对照
3. <repo>\Docs\storyboard-spec.md  ← 分镜的字段与硬规则

读完按里面的说明执行。不要自己改脚本，不要改 .claude/ 下的文件，不要 git commit。

## 参数（全程保持一致，不许中途改）
topic：你根据选题起一个短名（中文，不要空格、不要标点）
output_dir：留空即可（走 config.json 的 default_output_dir，当前是 <output>）
duration：30

所有产物必须落 <output_dir>\<topic>\，**不许写到桌面或仓库里**。写完用 config_loader 核对一次路径。

## 第 1 段：搜新闻 + 写稿（01-research.js）
跑完必须得到 <output_dir>\<topic>\03_article.md，至少 1500 汉字。

- 缺搜索 key 时的降级：Search 阶段会因为缺 METASO_API_KEY / TAVILY_API_KEY 失败，
  改用仓库自带适配器从 AIHOT 选题池挑题：
  python <repo>\news-searcher\scripts\search_aihot.py
  拿到原文链接后再跑 01 的 Article 及之后阶段，产物路径不变。
- 文章必须基于原文链接写，不许照抄聚合站摘要。
- 写完后确认：每个数字都能对回原文，对不上的删掉，不要猜。

## 第 2 段：配图 + Word（02-assets.js）
产物 images_good\ 与 05_<标题>.docx。
数据图里的数字必须有出处；生图模型只画画面不画字，中文标注由脚本叠加。

## 第 3 段：分镜 + 交接文件（03-video.js）
产物 06_content.json、06_storyboard.json、08_eac_handoff.json。

三道闸门必须真跑（不许口头声称通过）：
1. python <repo>\we-media-pipeline\scripts\validate_storyboard.py <06_storyboard.json>
   必须 exit 0 且首行 PASS
2. 五问盲读必须 verdict=clear：
   换个"关注 AI 的读者"视角，只看旁白，问 谁/什么时候/发生了什么/为什么/所以呢，
   再问「这跟我有什么关系」。partly 一律打回重写，最多两轮；
   两轮仍不是 clear 就停下报告，**不要带着 partly 往下走**。
   判定只卡口径（指代、分子分母、倍数与基数），不卡术语——读者懂 token/上下文/agent。
3. python <repo>\we-media-pipeline\scripts\build_handoff.py <06_storyboard.json>
   生成后加 --verify，必须 exit 0

## 第 4 段：出片（用 EAC 的 MCP 工具，不是 workflow）
先调 eac_status 确认插件在线。按 08_eac_handoff.json 的 clips 做：

1. eac_project_create（1080×1920 / 30fps）
2. 画 6 张卡（1080×1920，底部 26% 压暗条留给字幕）：
   - **品牌必须从 config.json 的 brand 段读**，调 we-media-pipeline\scripts\brand.py 的 draw_brand，
     不许在卡片脚本里写死名字
   - 先跑一次 brand.py --preview 确认字号和留白，再批量画
3. eac_asset_import 逐张导入
4. eac_job_submit type=voice，音色 mambo-zh，文本用 handoff 的 vo_script
   （旁白里不能有阿拉伯数字、拉丁字母、%，必须中文读法）
5. 拿到旁白实测时长后，用句间静音位置定切点（不要平均分六份）
6. eac_job_submit type=compose 生成配乐，时长 ≥ 成片时长
7. eac_timeline_update 排时间线：clips（start/duration 按实测）+ captions + musicPath
8. eac_job_submit type=render（1080×1920 / 30fps）

## 出片硬规矩
- 字幕单行 ≤24 汉字（40px 字号；36 字会溢出被切边）
- 画面上的数字只能来自该镜 narration、elements 或 facts，**不许自己编**
  （金额、单价、次数、时长都算；账单类画面用打码或非具体值）
- 运镜只用 zoom-in / pan，禁用 zoom-out（满画幅素材会在镜尾露黑边）
- 不硬套 30 秒：按 TTS 实测时长排，超了就按实测走，配乐跟着重做

## 交付
- <output_dir>\<topic>\07_video.mp4
- review.jpg（12 帧审片表）
- 报告必须写清：
  · 时长 / 分辨率 / 音频峰值 / 有无黑场或静止帧
  · 哪些闸门是真跑过的（贴 exit code），哪些只是静态检查
  · 内容上有没有编造的数字，保留了哪些原文数字

## 不许做的
- 不许 git commit
- 不许改 .claude/ 里的 workflow
- 不许把产物写进仓库
- 不许声称跑过没跑过的步骤；失败的环节如实写失败原因
```

---

## 跑完之后检查这些

| 项 | 期望 |
|---|---|
| `03_article.md` | ≥1500 汉字，来源链接能点开 |
| `06_storyboard.json` | `validate_storyboard.py` PASS，盲读 verdict=clear |
| `08_eac_handoff.json` | `build_handoff.py --verify` exit 0 |
| `07_video.mp4` | 无黑场、无静止帧、音频峰值 < -1 dB |
| 字幕 | 每行 ≤24 汉字，没被切边 |
| 画面数字 | 每个都能对回 narration / elements / facts |
| 品牌 | 卡片左上角与 config.json 的 brand.name 一致 |

## 如果中途挂了

| 症状 | 处理 |
|---|---|
| Search 阶段缺 key | 换 AIHOT 适配器（见第 1 段） |
| storyboard 反复 partly | 先怀疑选题：术语密集、口径讲不清的题在 30 秒里做不出来，换题比改稿快 |
| handoff --verify 失败 | 分镜改过没重生成，跑一次生成再验证 |
| 渲染出来字幕错位 | 就是 handoff 过期，重生成再渲 |
| 产物落到桌面 | `config.json` 的 `default_output_dir` 没生效，用 `config_loader --get` 核对 |
| 品牌还是旧名字 | 卡片是烘进图的，改配置后必须重画卡片 + 重新导入 + 重渲 |
