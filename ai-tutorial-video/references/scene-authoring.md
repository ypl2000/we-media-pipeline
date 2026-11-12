# 教程/科普视频 · 场景写法（AI 不够酷 竖版 1080x1920）

## 工程结构
```
index.html                  根 composition，挂所有场景槽位 + 配音轨（由 tutorial_build.py build 生成，别手改）
compositions/<id>.html      一个场景 = 一个 <template>（只有画面）
compositions/captions.html  字幕子合成（由 tutorial_build.py build 生成，别手改）
assets/voice/vo_<id>.mp3    场景配音（由 tutorial_build.py tts 生成）
assets/logos/ai_not_cool_logo.png   品牌 logo（根 composition 常驻，脚本已放）
   ↑ 真源是 we-video-generator/assets/logos/ai_not_cool_logo.png，`init` 时自动拷过去并裁掉白边
     （所以视频里是 1082×391 白底横幅，不是旧版圆形头像）
assets/music/ai_not_cool_bgm.mp3    BGM
```

**分工**：你只写 `compositions/<id>.html` 里的**画面**。字幕和配音是脚本按 edge-tts
词级时间戳注入的（`captions.html` + `index.html` 里的 `<audio>`），你在场景文件里写
`<audio>` 或 `.sub` 字幕 div 会造成重复，check 会报 `multiple_caption_tracks` / 音频重复。

现成的样例（已通过 check 0 error / 0 warning）在本目录 `example-scenes/`：
`hook.html`（钩子）、`split.html`（讲解）、`numbers.html`（数据）、`outro.html`（收尾）、
`captions.html`（脚本生成的字幕子合成，别手改）。

## 场景文件骨架
```html
<template>
  <style>
    #root { position: absolute; inset: 0; background: radial-gradient(ellipse at 50% 38%, #ffffff 0%, #e9ecf1 78%); overflow: hidden; }
    #xx-title { position: absolute; top: 380px; left: 0; right: 0; text-align: center; color: #141519; font-size: 80px; font-weight: 900; }
  </style>
  <div id="root" data-composition-id="<场景id>" data-width="1080" data-height="1920">
    <div id="xx-title" class="clip" data-start="0.3" data-duration="6.0" data-track-index="1">标题</div>
  </div>
  <script>
    const tl = gsap.timeline({ paused: true });
    tl.fromTo("#xx-title", { opacity: 0, y: 24 }, { opacity: 1, y: 0, duration: 0.55, ease: "power3.out" }, 0.3);
    window.__timelines["<场景id>"] = tl;
  </script>
</template>
```

**不要**在场景文件里写 `<audio>` 或 `.sub` 字幕 div / 字幕 tween —— 配音和字幕由脚本按配音时间戳注入，重复注入会冲突。

## 画面节奏（check 的 craft 规则）
这两条不满足会出 warning（不挡渲染，但画面确实不好）：

1. **一行字在屏上至少停 0.5 + 0.3 × 词数 秒**（3 个词 1.05s，7 个词 1.95s；整片最后一行要 2s）。
   词数按 HyperFrames 的 `Intl.Segmenter("ja")` 算，中文一个字常常就是 1 个词。
   → 写 `data-duration` 时按句子长度估，宁可多停。
2. **不能有超过 3 秒画面完全不动**（`dead_stretch`）。
   出场动画别都挤在开头，要跟旁白节奏对齐，尾部再补一拍（缩放/换行/淡出都算变化）。
   确实要静止停住（刻意留白），给那个元素加 `data-hold`。

其它相关 warning：`text_below_floor`（字小于 28px）、`first_frame_empty`（第 0 帧全空）。

## 手绘图形（放大镜这类 CSS 图形）
用 div 拼放大镜/箭头/圆环这类图形，**方向和接点必须算清楚**，否则一眼假：

- **CSS 的 `rotate(正角)` = 顺时针**。一根竖直的杆子 `rotate(45deg)` 会朝**左下**倒，`rotate(-45deg)` 才朝**右下**倒。
  放大镜手柄要朝「远离镜片」的方向：镜片在右下 → `rotate(-45deg)`；镜片在左下 → `rotate(45deg)`。
- **接点用圆心算**：镜片是 `R` 宽的圆、中心在 `(R/2, R/2)`，手柄接在 45° 方向的边缘点 `(R/2 + R/2·cos45, R/2 + R/2·sin45)`，
  手柄用 `transform-origin: top center` + `rotate()`，把它的 top-center 对准这个点。
- **碎裂/碎片**用从中心辐射的楔形 `clip-path: polygon(50% 50%, …)`，碎片颜色用半透明（浅底用 `rgba(20,21,25,0.25)`），
  不然灰扑扑的实心块看着像色斑，不像玻璃。
- 外层容器要比图形本身**大一圈**，让手柄/碎片飞出时不出框（check 会报 `escaped_container`）。

## 文字叠在卡片上
问题标号「?」、红点这类**故意压在卡片背景上**的标记，要加 `data-layout-allow-occlusion`，
否则 check 会报 `text_occluded` 错误（明明是故意叠的）。

## 画面文字 ≠ 字幕（最常见的问题）
字幕带在画面底部，把旁白**原样**打出来。画面再写一遍同样的字 = 白占一屏，观众眼睛来回扫。
所以画面文字只写旁白里**没有**的信息：

| 该写 | 不该写 |
|---|---|
| 数字（1 个 token ≈ 1 个汉字） | 把旁白整句放大字 |
| 专有名词（Darwin Gödel Machine） | 旁白里的动词和连接词 |
| 对比项（接得顺 / 事实正确） | 「其实」「但是」这种口播词 |
| 流程节点名（检索 / 生成） | 旁白原句的缩写版 |
| 方块、表格里的字（数字、时间、人名） | — |

- 钩子的大字也最多 12 字，别抄整句旁白。
- 旁白说「模型不认识单字，只认识词块」→ 画面画一排方块，标「TOKEN / 词块」，**不要再打那句旁白**。
- `tutorial_build.py verify` 会统计画面文字和字幕的重复比例：讲解场景 > 45%、首尾场景 > 75% 判失败，
  并点名是哪几段在复读。照着改画面，别改旁白。

## 硬约束（踩过的坑）
1. `data-composition-id` 必须等于文件名去掉 `.html`；`window.__timelines["<同一个 id>"]` 必须注册。
2. 每个要动的元素：`class="clip"` + `data-start`（场景内相对秒）+ `data-duration`。
3. **动画用 `fromTo`，不要用 `from`**。`from` 的 initial state 立即生效，起点晚于元素 clip 窗口时，整个窗口都看不见。
4. **不要给 `.clip` 元素补间 display/visibility/autoAlpha**，会跟 clip 的显隐打架。要淡入就淡入子元素。
5. **不要 `Date.now()`、不要无种子随机**，渲染要可复现。
6. 场景内所有 `data-start` / `data-duration` 必须落在 `[0, 场景时长]` 内，`data-start + data-duration` 不能超出场景时长。
7. **id 全页唯一**。跨场景用前缀：hook→`hk-`、split→`sp-`、numbers→`nm-`、outro→`ot-`；新场景用场景 id 前 2 字母。
8. 字体：根 composition 已声明 `@font-face` YaHei / YaHeiBold（`local()`）。正文用 `"YaHei", sans-serif`，强调数字用 `"YaHeiBold"`。
9. 资产路径写 `assets/...`（相对工程根）。

## 特效音（克制使用）
- 关键元素入场在元素上加 `data-sfx="pop|whoosh|ding"`，build 时按该元素的 `data-start` 自动注入低音量音效（音量 0.12~0.16，脚本管，不用管）：
  - `pop`「噗」0.15s：卡片/标签翻入、方块点亮
  - `whoosh`「唰」0.45s：转场、箭头/长条扫入
  - `ding`「叮」0.7s：数字特写、要点亮相
- **全片 ≤4 处**：只给「钩子大字 reveal、数字特写、结尾 CTA 弹入」这类重点时刻。普通文字、场景切换一律不加（BGM/配音已有节奏，别机关枪）。
  相邻 <0.4s 的脚本自动丢弃；全片 >6 条只留前 6 条。
- 带 `data-sfx` 的元素要有 `class="clip"` + `data-start`；**场景里不要写 `<audio>`**（配音/音效统一由脚本挂，verify 会拦）。

## 品牌样式（固定，别自创）—— 全系列**浅色背景**
| 用途 | 值 |
|---|---|
| 背景 | `radial-gradient(ellipse at 50% 38%, #ffffff 0%, #e9ecf1 78%)`（浅色系，深色视频已废弃） |
| 主文字 | `#141519` |
| 次要/注释 | `#4b5260`（浅底上别用浅灰，contrast 检查会挂） |
| 强调字 | `#6f5700`（浅底上的金色正文）；`#ffd700` 只做描边/装饰，或深色块上的字（浅底上做正文看不清） |
| 卡片底 | `#ffffff`，边框 `#d6dae2`，阴影 `0 8px 28px rgba(20,21,25,.08)` |
| 深色块（反衬用） | 底 `#1b1d24`，字 `#f2f3f5` |
| Logo | 根 composition 常驻，top 80px，**210px 宽横幅**（图是 1082×391 白底横幅，别再圆形裁切）。**场景里不要再放 logo 图片** —— 顶部已有常驻水印，重复 |
| 品牌名胶囊 | **不放**。顶部常驻 logo 已承担品牌曝光，结尾场景不再出现「AI不够酷」品牌名胶囊 |
| 结尾 CTA | 「点赞 · 关注」**固定 top:1366px 居中**（紧贴字幕带上沿，全系列统一）：`background:#1e212b; border:3px solid #ffd700; border-radius:999px; padding:16px 52px; color:#f2f3f5; font-size:44px; font-weight:900; letter-spacing:6px; box-shadow:0 0 26px rgba(255,215,0,.28)`；入场 `back.out(2.2)` 从 scale .55 弹到 1，末尾一次 scale 1.07 轻脉冲。**CTA 附近不放 logo** |
| 字幕 | 黑底白字胶囊（脚本注入，别自己写） |

## 版面安全区（1080x1920 竖版）
- Logo 区：y = 80~160，正文别往上顶到那里
- 字幕带：y = 1500~1620（脚本注入，bottom 300px）
- **画面内容不要越过 y = 1500**，会和字幕打架
- **结尾 CTA 区：y = 1366~1456，居中**（紧贴字幕带上沿，不要放右上角；全系列固定这个位置）
- 常用纵向锚点：标题 380 / 大标题 700 / 卡片 560、840 / 注释 1050 / 小结 1300

## 字号速查
- 大标题 78~80px / 小标题 56px / 正文 44~52px / 注释 34~36px / 数字特写 110px

## 动画节奏
- 入场：`fromTo(..., {opacity:0, y:24}, {opacity:1, y:0, duration:0.55, ease:"power3.out"})`
- 逐字：`splitChars()` 拆成 `<span class="ch">`，`stagger: 0.04`
- 强调脉冲：`tl.to(el, { scale: 1.05, duration: 0.28, ease: "power2.inOut", yoyo: true, repeat: 1 }, t)`

## 校验
```
python ..\..\scripts\tutorial_build.py hf --run-dir "." check --json     # 必须 0 error 才进渲染
```
（包装命令会把 ffmpeg/ffprobe 加进 PATH；Windows 上 npx 是 `.cmd`，直接 `npx` 会报 WinError 2。）

常见 error：`data-composition-id` 不匹配、clip 时间越界、id 重复、对比度不足、`.clip` 上补间了 display。

## 字幕怎么来的（别自己写）
`tutorial_build.py tts` 用 edge-tts 拿到每个场景的**词级**时间戳（WordBoundary），
再按 HyperFrames 同款 `Intl.Segmenter("ja")` 分词、标点处断句、每组最多 14 字，
合成字幕组。语音给的时间不够读时，**先把下一条字幕的出场往后推**（字幕比语音慢
半拍是正常观感），推不动才合并相邻字幕；合并不跨句号，跨逗号只拼 ≤2 词的小段并
补空格当停顿。≤2 词的短行至少停 0.9s（两三个字一闪而过像机器切的）。
字幕文字**不带标点**，位置固定 `bottom: 300px`（黑底白字胶囊），由 `captions.html` 统一渲染。

写旁白时配合字幕切分：每个逗号小段 4~14 字、句长有长短差，切出来的字幕行就自然。
审稿用 `python scripts/tutorial_build.py subs-preview --storyboard <storyboard.json>`
预览实际字幕行（不跑 TTS）。

## 实测结论（2026-11 首跑验证，试过错才知道的）
- **配音音色**：`zh-CN-YunxiNeural`（男声科普）为默认；备选 `XiaoxiaoNeural`（女声）、`YunyangNeural`（播音腔）。
- **edge-tts 报 403** = 微软 DRM token 过期，`pip install -U edge-tts` 即修。
- **TTS 后必须自查时长漂移**：旁白写超了时长会暴涨（首跑 41.4s 超目标 30s 达 +38%），改旁白压回来再进下一步。
- **渲染坑**：目标 mp4 被播放器占用时 HyperFrames 写不进去，但输出**看起来像成功**——渲染前确认文件没被占用，或直接输出到新文件名；别用 grep 过滤渲染输出，会吞掉错误。验片用「底部字幕带白字像素计数」比抽帧肉眼快。
- **lint 基线**：雅黑 `@font-face local()` 有 2 条 warning 属正常；要清掉就把字体打成 `assets/fonts/` 本地 woff2。
- 参考：28~30s 竖版 1080x1920 渲染约 50 秒（本地 Chrome + ffmpeg）。
