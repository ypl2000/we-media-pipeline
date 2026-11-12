"""教程/科普视频工程构建脚本（HyperFrames 多场景）。

子命令:
  init   --run-dir D            从种子工程拷 assets/package.json/hyperframes.json, 建目录
  tts    --run-dir D --storyboard S   按分镜生成配音 mp3 + 词级字幕时间 + 场景槽位
  build  --run-dir D            生成 compositions/captions.html + index.html
  verify --run-dir D            一致性自检
  hf     --run-dir D -- <args>  在 run 目录里跑 hyperframes CLI（自动带上 ffmpeg 路径）

设计约定:
  - 声音是时钟: 场景槽位 = 配音时长 + 0.4s 余量, 场景内所有元素时间相对场景起点
  - 字幕是独立的 captions 子合成 (data-track-kind="captions"), 不塞进场景文件
  - 字幕时间戳来自 edge-tts 词级边界, 按标点切子句; 显示时去掉末尾标点
  - 场景文件只写画面, 全部时间/音频/字幕由本脚本生成
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

# 仓库根 = 本文件的上上级目录（ai-tutorial-video/scripts/ → 上上级），不写死绝对路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SEED_DIR = os.path.join(PROJECT_ROOT, "ai-tutorial-video", "hyperframes")
PUNCT_ALL = "，。？！、；：,.;?!：—…～~" + '"' + "'" + "（）()《》【】"

TAIL = 1.8  # 最后一个场景尾部多留一会儿, 让结尾字幕能停留满 2s

# 背景音乐: 留空 = 成片不带 BGM（当前阶段先关掉, 之后换歌改这一行即可）
BGM_SRC = ""  # 例: "assets/music/ai_not_cool_bgm.mp3"


def log(*a):
    print(*a, flush=True)


def find_ffprobe():
    for cand in (shutil.which("ffprobe"), r"D:\ffmpeg\bin\ffprobe.exe"):
        if cand and os.path.exists(cand):
            return cand
    raise SystemExit("找不到 ffprobe, 装 ffmpeg 或把它加进 PATH")


def ffmpeg_dir():
    for d in (r"D:\ffmpeg\bin", r"C:\ffmpeg\bin"):
        if os.path.exists(os.path.join(d, "ffmpeg.exe")):
            return d
    return None


def probe_duration(path):
    out = subprocess.run(
        [find_ffprobe(), "-v", "quiet", "-print_format", "json", "-show_format", path],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


# ─────────────────────────── init ───────────────────────────

CANON_LOGOS = os.path.join(PROJECT_ROOT, "we-video-generator", "assets", "logos")


def trim_logo(src, dst, pad=18):
    """裁掉 logo 的白边（视频里是白底横幅，白边留白会显得又小又偏）。"""
    from PIL import Image
    im = Image.open(src).convert("RGB")
    inv = im.convert("L").point(lambda p: 255 if p < 250 else 0)
    box = inv.getbbox()
    if not box:
        shutil.copyfile(src, dst)
        return
    x0, y0, x1, y1 = box
    box = (max(0, x0 - pad), max(0, y0 - pad),
           min(im.width, x1 + pad), min(im.height, y1 + pad))
    im.crop(box).save(dst)


def cmd_init(args):
    run = os.path.abspath(args.run_dir)
    for d in ("compositions", "_work", "assets"):
        os.makedirs(os.path.join(run, d), exist_ok=True)
    src_assets = os.path.join(SEED_DIR, "assets")
    dst_assets = os.path.join(run, "assets")
    for sub in ("logos", "music", "vendor", "fonts"):
        s = os.path.join(src_assets, sub)
        if os.path.isdir(s):
            shutil.copytree(s, os.path.join(dst_assets, sub), dirs_exist_ok=True)
    # 品牌 logo 以 we-video-generator/assets/logos 为准（唯一真源），裁掉白边
    if os.path.isdir(CANON_LOGOS):
        dst_logos = os.path.join(dst_assets, "logos")
        os.makedirs(dst_logos, exist_ok=True)
        for f in os.listdir(CANON_LOGOS):
            src = os.path.join(CANON_LOGOS, f)
            dst = os.path.join(dst_logos, os.path.splitext(f)[0] + ".png")
            trim_logo(src, dst)
    for f in ("package.json", "hyperframes.json"):
        shutil.copyfile(os.path.join(SEED_DIR, f), os.path.join(run, f))
    ensure_sfx(run)
    log(f"init ok: {run}")
    return run


# ─────────────────────────── tts ───────────────────────────

def caption_groups(text, max_chars=14):
    """用 node 的 Intl.Segmenter 分词并组词。

    返回 [{t, start, end, w}] —— start/end 是原文字符下标, w 是词数
    （= HyperFrames 的 readingWords 数，同款 Segmenter）。
    """
    proc = subprocess.run(
        ["node", os.path.join(os.path.dirname(os.path.abspath(__file__)), "caption_groups.js")],
        input=json.dumps({"text": text, "maxChars": max_chars}),
        capture_output=True, text=True, check=True,
    )
    data = json.loads(proc.stdout)
    out = []
    for g in data["groups"]:
        if not g["words"]:
            continue
        out.append({
            "t": g["t"],
            "start": g["start"],
            "end": g["end"],
            "w": len(g["words"]),
            "brk": g.get("brk", "chars"),
        })
    return out, data["words"]


def hold_floor(words, final=False):
    """一条字幕至少该在屏上多久: 0.5s + 0.3s/词, 结尾那句至少 2s。

    和 HyperFrames craftAudit 的 lineFloorSec 大体一致, 但 ≤2 词故意收得更紧
    (0.9s 而不是它的 0.4s): 两三个字一闪而过像机器切的, 观感差 —— 宁可让
    fit_cues 把它和邻居合并, 或把下一条的出场往后推。
    """
    floor = 0.9 if words <= 2 else 0.75 * (0.5 + 0.3 * words)
    return max(floor, 2.0) if final else floor


async def synth_scene(text, voice, mp3_path, rate):
    import edge_tts
    comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    audio = bytearray()
    words = []
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            words.append((
                chunk["text"],
                chunk["offset"] / 1e7,
                (chunk["offset"] + chunk["duration"]) / 1e7,
            ))
    with open(mp3_path, "wb") as f:
        f.write(audio)
    return words


def scene_cues(text, words):
    """把一段旁白切成字幕条目 [{t,s,e}]，时间相对这段旁白的开头。

    切分用 node 的 Intl.Segmenter（和 HyperFrames 一致），时间用 edge-tts 的
    WordBoundary。两者靠字符下标对齐: 每个 edge-tts 词覆盖的字符区间 ∩
    字幕组的字符区间 → 取该组内所有词的最小 start / 最大 end。
    """
    groups, _ = caption_groups(text)
    if not groups:
        return []

    # edge-tts 词 → 它覆盖的原文区间
    spans = []
    pos = 0
    for wt, st, en in words:
        # 找到这个词在原文里的位置
        idx = text.find(wt, pos)
        if idx < 0:
            continue
        spans.append((idx, idx + len(wt), st, en))
        pos = idx + len(wt)

    cues = []
    for g in groups:
        inside = [w for w in spans if w[0] < g["end"] and w[1] > g["start"]]
        if inside:
            s = round(min(w[2] for w in inside), 2)
            e = round(max(w[3] for w in inside), 2)
        else:
            # 找不到时间戳也不能丢这一组的字，先挂到上一条末尾，交给 fit_cues 合并
            s = cues[-1]["e"] if cues else 0.0
            e = s
        cues.append({"t": g["t"], "s": s, "e": e, "w": g["w"], "brk": g["brk"]})
    # 单调、不重叠；时间戳被四舍五入到同一时刻时补一个极短窗口，
    # 绝不能整条丢掉（丢掉就会「字幕最后几个字不显示」）
    clean = []
    for it in cues:
        if clean and it["s"] < clean[-1]["e"]:
            it["s"] = clean[-1]["e"]
        if it["e"] <= it["s"]:
            it["e"] = round(it["s"] + 0.01, 2)
        clean.append(it)
    return clean


def join_caption(a, b, sep=""):
    """合并两条字幕文字：中文接中文不留空格，其余情况留一个空格。

    sep 非空时强制用它隔开（跨逗号合并两个小句时补一个空格当停顿,
    否则「记住」「模型吃的不是字」拼成「记住模型吃的不是字」读不通）。
    """
    a, b = a.strip(), b.strip()
    if not a:
        return b
    if not b:
        return a
    if sep:
        return a + sep + b
    if re.match(r"[\u4e00-\u9fff]", a[-1]) and re.match(r"[\u4e00-\u9fff]", b[0]):
        return a + b
    return a + " " + b


MAX_CAPTION_LAG = 1.0  # 字幕比语音最多慢 1s, 再多就该合并而不是继续推


def fit_cues(cues, dur, final=False):
    """保证每条字幕在屏上的时间够读完：先平移出场时间，推不动才合并。

    第 i 条的显示窗口 = [出场_i, 出场_{i+1})，最后一条到场景末尾。语音给的
    窗口不够读（< hold_floor）时，先把下一条的出场往后推 —— 字幕比语音慢
    半拍是正常观感，也比把两句话拼成一行自然。只有当推会让某条滞后语音超过
    MAX_CAPTION_LAG、或最后一条在场景里停不够时才合并，且：
      - 不跨句号（两个句子拼一行读不通）；
      - 跨逗号只允许有一边是 ≤2 词的小段，拼接时补空格当停顿。

    返回 (排好的 cues, 是否全部满足)。
    """
    items = [dict(c) for c in cues]
    if not items:
        return [], True

    def floors(seq):
        return [hold_floor(c["w"], final=(final and i == len(seq) - 1))
                for i, c in enumerate(seq)]

    def layout(seq):
        """出场 = max(语音起点, 上一条停够的时刻)。返回 (出场表, 尾巴放得下?, 最大滞后)。"""
        fs = floors(seq)
        ds, prev_need, lag = [], 0.0, 0.0
        for c, f in zip(seq, fs):
            st = max(c["s"], prev_need)
            ds.append(st)
            lag = max(lag, st - c["s"])
            prev_need = st + f
        return ds, ds[-1] + fs[-1] <= dur + 1e-6, lag

    for _ in range(len(items)):
        ds, fits, lag = layout(items)
        if fits and lag <= MAX_CAPTION_LAG:
            break
        # 平移解决不了 → 合并一对（floors 不累加: 固定开销 0.5s 只付一次）
        for i in range(len(items) - 1):
            a, b = items[i], items[i + 1]
            if a["brk"] == "sentence":
                continue
            if a["brk"] == "soft" and a["w"] > 2 and b["w"] > 2:
                continue
            items[i:i + 2] = [{
                "t": join_caption(a["t"], b["t"], sep="" if a["brk"] == "chars" else " "),
                "s": a["s"], "e": b["e"], "w": a["w"] + b["w"], "brk": b["brk"],
            }]
            break
        else:
            break  # 没有可合并的对, 只能平移到哪算哪
    ds, fits, _ = layout(items)
    out = []
    for c, d in zip(items, ds):
        c["s"] = round(d, 2)
        if c["e"] <= c["s"]:
            c["e"] = round(c["s"] + 0.01, 2)
        out.append({k: c[k] for k in ("t", "s", "e", "w")})
    return out, fits


def step_rate(rate, delta):
    """'+0%' -> '-10%'（delta 为负数 = 更慢）。edge-tts 只认带符号的百分比。"""
    m = re.match(r"^([+-]?)(\d+)%$", rate.strip())
    if not m:
        return rate
    sign = -1 if m.group(1) == "-" else 1
    val = sign * int(m.group(2)) + delta
    return f"{'+' if val >= 0 else '-'}{abs(val)}%"


def cmd_tts(args):
    import asyncio
    run = os.path.abspath(args.run_dir)
    story = json.load(open(args.storyboard, encoding="utf-8"))
    scenes = story["scenes"]
    voice = args.voice or story.get("voice") or "zh-CN-YunxiNeural"
    base_rate = args.rate or story.get("rate") or "+0%"

    voice_dir = os.path.join(run, "assets", "voice")
    os.makedirs(voice_dir, exist_ok=True)

    subs, slots = {}, []
    cursor = 0.0
    prefixes = set()
    for i, sc in enumerate(scenes):
        sid = sc["id"]
        if sid[:2] in prefixes:
            raise SystemExit(f"场景 id 前 2 字母重复（字幕 id 会撞）: {sid}")
        prefixes.add(sid[:2])
        text = sc["narration"].strip()
        mp3 = os.path.join(voice_dir, f"vo_{sid}.mp3")

        # 字幕停留时间不够读 → 语速再慢一点重合成（craft 规则：0.5s + 0.3s/词）
        rate = base_rate
        clean, fitted = [], False
        is_last = i == len(scenes) - 1
        for attempt in range(3):
            words = asyncio.run(synth_scene(text, voice, mp3, rate))
            dur = probe_duration(mp3)
            raw = scene_cues(text, words)
            # 字幕能在场景槽位（配音 + 0.4s 余量 [+ 末场 TAIL]）里停够就算过,
            # 用纯配音时长会把末场结尾那句误判成停不下
            slot_dur = round(dur + 0.4, 2) + (TAIL if is_last else 0)
            clean, fitted = fit_cues(raw, slot_dur, final=is_last)
            if fitted or attempt == 2:
                break
            rate = step_rate(rate, -10)
            log(f"  {sid}: 字幕停留不足 → 语速调到 {rate} 重试")

        subs[sid] = {"dur": round(dur, 2),
                      "subs": [{k: c[k] for k in ("t", "s", "e")} for c in clean]}
        slots.append({
            "id": sid,
            "start": round(cursor, 2),
            "duration": slot_dur,
            "voice": f"assets/voice/vo_{sid}.mp3",
            "voice_dur": round(dur, 2),
        })
        cursor = round(cursor + slot_dur, 2)
        log(f"  {sid}: vo {dur:.2f}s, slot {slot_dur}s @ {slots[-1]['start']}s, "
            f"{len(clean)} 条字幕" + ("" if fitted else " ⚠ 停留时间仍不足"))

    total = round(cursor, 2)
    json.dump(subs, open(os.path.join(run, "_work", "subs.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump({"scenes": slots, "total": total},
              open(os.path.join(run, "_work", "slots.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    log(f"tts ok: {len(scenes)} 场景, 总时长 {total}s")


# ─────────────────────────── 特效音 ───────────────────────────
# 场景元素加 data-sfx="pop|whoosh|ding" 声明「这个元素入场时来一声音效」,
# 音频文件由 ffmpeg 合成（无版权问题）, build 时按元素时间注入 index.html。
# 音量刻意压低（0.12-0.16）, 只做点缀; 相邻两条间隔 <0.4s 的自动丢掉, 避免机关枪。

SFX_MAX = 6  # 全片硬上限（提示词要求 agent 控制在 4 处左右, 这里兜底）

SFX_SPECS = {
    # (lavfi 源, 滤镜, 时长, 注入音量)
    "pop":    ("aevalsrc=0.6*sin(2*PI*600*t)*exp(-18*t):d=0.15:s=44100",
               "anull", 0.15, 0.16),   # 短促「噗」: 卡片/标签入场
    "whoosh": ("anoisesrc=color=pink:d=0.45:a=0.8:s=44100",
               "lowpass=f=900,afade=t=in:st=0:d=0.3,afade=t=out:st=0.3:d=0.15,volume=1.5",
               0.45, 0.13),            # 轻「唰」: 转场/箭头扫入
    "ding":   ("aevalsrc=0.4*sin(2*PI*988*t)*exp(-5*t)+0.25*sin(2*PI*1480*t)*exp(-7*t):d=0.7:s=44100",
               "anull", 0.7, 0.12),    # 钟声「叮」: 数字/要点亮相
}


def ensure_sfx(run):
    """合成特效音到 run/assets/sfx/（已存在就跳过, 幂等）。"""
    d = ffmpeg_dir()
    if not d:
        raise SystemExit("找不到 ffmpeg.exe（合成特效音需要）, 检查 D:\\ffmpeg\\bin")
    sfx_dir = os.path.join(run, "assets", "sfx")
    os.makedirs(sfx_dir, exist_ok=True)
    for name, (src, af, _dur, _vol) in SFX_SPECS.items():
        out = os.path.join(sfx_dir, f"{name}.wav")
        if os.path.exists(out):
            continue
        subprocess.run(
            [os.path.join(d, "ffmpeg.exe"), "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", src, "-af", af, "-ac", "1", "-sample_fmt", "s16", out],
            check=True,
        )
    return sfx_dir


SFX_TMPL = """
      <audio
        id="sfx-{i}"
        data-start="{start}"
        data-duration="{dur}"
        data-track-index="{idx}"
        data-track-kind="audio"
        src="assets/sfx/{name}.wav"
        data-volume="{vol}"
      ></audio>
"""


def collect_sfx(run, slots):
    """扫场景 HTML 里的 data-sfx 标注 → 绝对时间音效列表。

    时间 = 场景起点 + 元素 data-start；0.4s 内的多条只留第一条（防机关枪）。
    """
    cues = []
    for sc in slots["scenes"]:
        path = os.path.join(run, "compositions", f"{sc['id']}.html")
        if not os.path.exists(path):
            continue
        s = open(path, encoding="utf-8").read()
        for m in re.finditer(r'<[^>]*?data-sfx="([^"]+)"[^>]*>', s):
            name = m.group(1)
            if name not in SFX_SPECS:
                raise SystemExit(
                    f"{sc['id']}.html: 未知特效音 data-sfx=\"{name}\"（可选: {'/'.join(SFX_SPECS)}）")
            st = re.search(r'data-start="([0-9.]+)"', m.group(0))
            t = round(sc["start"] + (float(st.group(1)) if st else 0.0), 2)
            cues.append({"name": name, "start": t,
                         "dur": SFX_SPECS[name][2], "vol": SFX_SPECS[name][3]})
    cues.sort(key=lambda c: c["start"])
    out = []
    for c in cues:
        if out and c["start"] - out[-1]["start"] < 0.4:
            continue
        out.append(c)
    return out


CAPTION_CSS = """    /* 底部字幕: 按旁白子句分组, 时间戳来自 edge-tts WordBoundary */
    .caption {
      position: absolute;
      bottom: 300px;
      left: 0;
      right: 0;
      display: flex;
      justify-content: center;
      z-index: 60;
    }
    .caption span {
      display: inline-block;
      /* 1000px: 20 字字幕(46px) 一行放得下, 不会掉出一个两字孤行 */
      max-width: 1000px;
      padding: 16px 32px;
      border-radius: 18px;
      /* 不透明深底: 半透明底会被 contrast 检查当成浅底, 白字被判 AA 不通过 */
      background: #141519;
      color: #fff;
      font-family: "YaHeiBold", "YaHei", sans-serif;
      font-size: 46px;
      font-weight: 900;
      line-height: 1.5;
      text-align: center;
      will-change: transform, opacity;
    }
"""


def build_captions(run, subs, slots):
    """生成 compositions/captions.html —— 全片字幕, 一条 track。

    时间用绝对秒（相对全片起点）, 所以字幕合成挂在 index.html 的 0 秒处,
    覆盖整片。停留时间在 tts 阶段已按 craft 规则保证（fit_cues）,
    这里只负责跨场景边界把上一条的结束时间补到下一条的开始。
    """
    cues = []
    for sc in slots["scenes"]:
        for g in subs[sc["id"]]["subs"]:
            cues.append({
                "t": g["t"].rstrip(PUNCT_ALL),
                "s": round(sc["start"] + g["s"], 2),
                "e": round(sc["start"] + g["e"], 2),
            })
    # 首条别贴着 0（HyperFrames: 0s 出现的字幕像是本来就有的）
    if cues:
        cues[0]["s"] = max(cues[0]["s"], 0.12)
    # 上一条留到下一条开始（不留空档, 也不重叠）
    for i in range(len(cues) - 1):
        cues[i]["e"] = max(cues[i]["e"], cues[i + 1]["s"])
    # 最后一条留满 2s（craft 规则: 结尾那句至少 2s）
    if cues:
        cues[-1]["e"] = max(cues[-1]["e"], cues[-1]["s"] + 2.0, slots["total"])

    divs = []
    tweens = []
    for i, c in enumerate(cues, 1):
        cid = f"cg-{i}"
        divs.append(
            f'    <div id="{cid}" class="caption clip caption-group" data-start="{c["s"]}" '
            f'data-duration="{round(c["e"] - c["s"], 2)}" data-track-index="1" '
            f'data-track-kind="captions"><span>{c["t"]}</span></div>'
        )
        tweens.append(
            f'    tl.fromTo("#{cid} span", {{ opacity: 0, y: 16 }}, '
            f'{{ opacity: 1, y: 0, duration: 0.25, ease: "power2.out" }}, {c["s"]});'
        )

    html = f"""<template>
  <style>
    #root {{
      position: absolute;
      inset: 0;
      overflow: hidden;
      pointer-events: none;
    }}
{CAPTION_CSS}  </style>
  <div id="root" data-composition-id="captions" data-width="1080" data-height="1920">
{chr(10).join(divs)}
  </div>
  <script>
    const tl = gsap.timeline({{ paused: true }});

{chr(10).join(tweens)}

    window.__timelines["captions"] = tl;
  </script>
</template>
"""
    open(os.path.join(run, "compositions", "captions.html"), "w",
         encoding="utf-8", newline="\n").write(html)
    return cues


INDEX_TMPL = """<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <script src="assets/vendor/gsap.min.js"></script>
    <style>
      @font-face {{
        font-family: "YaHei";
        src: url("assets/fonts/yahei.woff2") format("woff2"),
             local("Microsoft YaHei"), local("Microsoft YaHei UI");
        font-weight: 400 900;
      }}
      @font-face {{
        font-family: "YaHeiBold";
        src: url("assets/fonts/yahei-bold.woff2") format("woff2"),
             local("Microsoft YaHei Bold"), local("Microsoft YaHei UI Bold");
        font-weight: 700 900;
      }}
      * {{
        margin: 0;
        padding: 0;
        box-sizing: border-box;
      }}
      html,
      body {{
        width: 1080px;
        height: 1920px;
        overflow: hidden;
        background: #e9ecf1;
        font-family: "YaHei", sans-serif;
      }}
      #brand-logo {{
        position: absolute;
        top: 80px;
        left: 50%;
        transform: translateX(-50%);
        width: 210px;
        padding: 8px 14px;
        border-radius: 12px;
        background: #ffffff;
        border: 1px solid rgba(20, 21, 25, 0.12);
        z-index: 50;
      }}
    </style>
  </head>
  <body>
    <!-- 场景槽位跟着配音长度走（配音 +0.4s 余量, 末场多留 {tail}s）: {slot_comment} -->
    <div
      id="root"
      data-composition-id="main"
      data-start="0"
      data-duration="{total}"
      data-width="1080"
      data-height="1920"
      data-fps="30"
    >
      <!-- 品牌水印: 常驻所有场景, 位置与新闻模板一致 (y=80, 210px 宽) -->
      <img id="brand-logo" src="assets/logos/ai_not_cool_logo.png" alt="" />
{hosts}
      <!-- 字幕: 全片一条 captions track, 挂在最后 = 画在最上层 -->
      <div
        id="captions"
        data-composition-id="captions"
        data-composition-src="compositions/captions.html"
        data-start="0"
        data-duration="{total}"
        data-track-index="8"
        data-track-kind="captions"
        data-width="1080"
        data-height="1920"
      ></div>
{voices}
{bgm}{sfx}
    </div>

    <script>
      window.__timelines["main"] = gsap.timeline({{ paused: true }});
    </script>
  </body>
</html>
"""

HOST_TMPL = """
      <div
        id="{sid}"
        data-composition-id="{sid}"
        data-composition-src="compositions/{sid}.html"
        data-start="{start}"
        data-duration="{dur}"
        data-track-index="{idx}"
        data-track-kind="graphics"
        data-width="1080"
        data-height="1920"
      ></div>
"""

VOICE_TMPL = """
      <audio
        id="{vid}"
        data-start="{start}"
        data-duration="{dur}"
        data-track-index="{idx}"
        data-track-kind="audio"
        src="{src}"
      ></audio>
"""

BGM_TMPL = """
      <audio
        id="bgm"
        data-start="0"
        data-duration="{total}"
        data-track-index="90"
        data-track-kind="audio"
        src="{src}"
        data-volume="0.28"
        data-fade-out="2"
      ></audio>
"""


def strip_legacy_scene(path):
    """把场景文件里的旧式字幕 div / 配音 audio / 字幕 CSS / 字幕 tween 抹掉。

    场景文件只应该写画面。字幕统一在 compositions/captions.html, 配音统一挂在
    index.html 上。这个函数是幂等的, 方便反复 build。
    """
    src = open(path, encoding="utf-8").read()
    orig = src
    # 字幕 div
    src = re.sub(r'[ \t]*<div[^>]*class="[^"]*\bsub\b[^"]*"[^>]*>.*?</div>\s*\n?', "", src, flags=re.S)
    # 配音 audio
    src = re.sub(r'[ \t]*<audio\b[^>]*>\s*</audio>\s*\n?', "", src)
    # 字幕 CSS（含紧跟其后的注释块）
    src = re.sub(r'[ \t]*/\* 底部字幕.*?\*/\s*\n', "", src, flags=re.S)
    src = re.sub(r'[ \t]*\.sub\s+span\s*\{[^{}]*\}\s*\n', "", src)
    src = re.sub(r'[ \t]*\.sub\s*\{[^{}]*\}\s*\n', "", src)
    # 字幕 tween
    src = re.sub(r'[ \t]*tl\.(?:fromTo|to|set)\(\s*"#[^"]*-sub\d+[^"]*".*?\);\s*\n', "", src, flags=re.S)
    src = re.sub(r'\n{3,}', "\n\n", src)
    if src != orig:
        open(path, "w", encoding="utf-8", newline="\n").write(src)
    return src


def cmd_build(args):
    run = os.path.abspath(args.run_dir)
    subs = json.load(open(os.path.join(run, "_work", "subs.json"), encoding="utf-8"))
    slots = json.load(open(os.path.join(run, "_work", "slots.json"), encoding="utf-8"))

    for sc in slots["scenes"]:
        path = os.path.join(run, "compositions", f"{sc['id']}.html")
        if not os.path.exists(path):
            raise SystemExit(f"缺场景文件: {path}")
        strip_legacy_scene(path)

    cues = build_captions(run, subs, slots)
    log(f"  captions.html: {len(cues)} 条字幕")

    hosts = "".join(HOST_TMPL.format(sid=s["id"], start=s["start"], dur=s["duration"],
                                     idx=i + 1)
                     for i, s in enumerate(slots["scenes"]))
    voices = "".join(VOICE_TMPL.format(
        vid=f"vo-{s['id']}", src=s["voice"], start=s["start"], dur=s["voice_dur"], idx=9 + i)
        for i, s in enumerate(slots["scenes"]))
    sfx_cues = collect_sfx(run, slots)
    if len(sfx_cues) > SFX_MAX:
        log(f"  sfx: {len(sfx_cues)} 条超上限, 只保留前 {SFX_MAX} 条（特效音是点缀, 不是配乐）")
        sfx_cues = sfx_cues[:SFX_MAX]
    sfx = "".join(SFX_TMPL.format(i=i, **c, idx=80 + i) for i, c in enumerate(sfx_cues))
    if sfx_cues:
        ensure_sfx(run)
        log(f"  sfx: {len(sfx_cues)} 条特效音（{'/'.join(sorted({c['name'] for c in sfx_cues}))}）")
    comment = " | ".join(f"{s['id']} {s['start']}-{round(s['start'] + s['duration'], 2)}"
                         for s in slots["scenes"])
    bgm = BGM_TMPL.format(src=BGM_SRC, total=slots["total"]) if BGM_SRC else ""
    open(os.path.join(run, "index.html"), "w", encoding="utf-8", newline="\n").write(
        INDEX_TMPL.format(hosts=hosts, voices=voices, bgm=bgm, sfx=sfx, total=slots["total"],
                          slot_comment=comment, tail=TAIL))
    log(f"build ok: index.html + captions.html, 总时长 {slots['total']}s")


# ─────────────────────────── verify ───────────────────────────

# ───────────────────── 画面文字 vs 字幕（复述检查） ─────────────────────

# 画面文字里和字幕重合的比例上限（连续 ≥ ECHO_MIN_RUN 个字才算「复述」）。
# 讲解场景严（画面该补充信息，不该重复旁白），首尾场景松（标题卡本来就要重复要点）。
ECHO_LIMIT = {"body": 0.45, "edge": 0.75}
ECHO_MIN_RUN = 3


def _norm_text(t):
    """只留中英文数字，标点/符号/空格全去掉（用来比对字面重合）。"""
    return re.sub(r"[^0-9A-Za-z一-鿿]+", "", t)


def _scene_on_screen_text(path):
    """场景 HTML 里所有可见文字（去掉 script/style/注释/标签），逐段返回。"""
    s = open(path, encoding="utf-8").read()
    s = re.sub(r"<script.*?</script>", " ", s, flags=re.S)
    s = re.sub(r"<style.*?</style>", " ", s, flags=re.S)
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.S)
    s = re.sub(r"<[^>]+>", "\n", s)
    return [t.strip() for t in s.split("\n") if t.strip()]


def _lcs_len(a, b):
    """a、b 的最长公共子串长度（a、b 都很短，暴力即可）。"""
    best = 0
    for i in range(len(a)):
        for j in range(i + best + 1, len(a) + 1):
            if a[i:j] in b:
                best = j - i
            else:
                break
    return best


def _echo_report(run, slots, subs):
    """每个场景：画面文字有多少是字幕的原话。

    返回 [(scene_id, role, rate, [(复读的文字, 重合字数)])]。
    role: 第一个场景 hook、最后一个 outro → "edge"，其余 → "body"。
    """
    out = []
    scenes = slots["scenes"]
    for idx, sc in enumerate(scenes):
        sid = sc["id"]
        role = "edge" if idx in (0, len(scenes) - 1) else "body"
        cap = _norm_text("".join(c["t"] for c in subs.get(sid, {}).get("subs", [])))
        path = os.path.join(run, "compositions", f"{sid}.html")
        if not os.path.exists(path):
            continue
        blocks = [_norm_text(b) for b in _scene_on_screen_text(path)]
        blocks = [b for b in blocks if b]
        if not blocks:
            continue
        total = sum(len(b) for b in blocks)
        echo = 0
        offenders = []
        for b in blocks:
            n = _lcs_len(b, cap)
            if n >= ECHO_MIN_RUN:
                echo += n
                offenders.append((b, n))
        out.append((sid, role, echo / total, offenders))
    return out


def cmd_verify(args):
    run = os.path.abspath(args.run_dir)
    subs = json.load(open(os.path.join(run, "_work", "subs.json"), encoding="utf-8"))
    slots = json.load(open(os.path.join(run, "_work", "slots.json"), encoding="utf-8"))
    problems = []

    seen = set()
    for sc in slots["scenes"]:
        sid = sc["id"]
        if sid in seen:
            problems.append(f"场景 id 重复: {sid}")
        seen.add(sid)
        path = os.path.join(run, "compositions", f"{sid}.html")
        if not os.path.exists(path):
            problems.append(f"缺场景文件 {sid}.html")
            continue
        s = open(path, encoding="utf-8").read()
        if f'data-composition-id="{sid}"' not in s:
            problems.append(f"{sid}.html: data-composition-id 不匹配")
        if f'window.__timelines["{sid}"]' not in s:
            problems.append(f'{sid}.html: 没注册 window.__timelines["{sid}"]')
        if "<audio" in s:
            problems.append(f"{sid}.html: 场景文件不该带 <audio>（配音由场景宿主统一挂）")
        if ".caption" in s or 'class="caption' in s:
            problems.append(f"{sid}.html: 场景文件不该带字幕（字幕在 captions.html）")

    cap_path = os.path.join(run, "compositions", "captions.html")
    if not os.path.exists(cap_path):
        problems.append("缺 compositions/captions.html")
    else:
        c = open(cap_path, encoding="utf-8").read()
        n = len(re.findall(r'id="cg-\d+"', c))
        ntw = len(re.findall(r'tl\.fromTo\("#cg-\d+ span"', c))
        if n == 0:
            problems.append("captions.html: 没有字幕")
        if n != ntw:
            problems.append(f"captions.html: 字幕 div {n} 个, tween {ntw} 个（必须一一对应）")
        if re.search(r'<span>[^<]*[，。？！、；：,.;?!]</span>', c):
            problems.append("captions.html: 字幕末尾还有标点")
        if 'window.__timelines["captions"]' not in c:
            problems.append('captions.html: 没注册 window.__timelines["captions"]')
        # 所有字幕必须在同一条 track 上
        lanes = set(re.findall(r'data-track-index="(\d+)"', c))
        if len(lanes) > 1:
            problems.append(f"captions.html: 字幕分散在 {len(lanes)} 条 track 上, 必须只有一条")
        # 字幕元素 id 必须是 cg-N（HyperFrames 据此豁免 track 密度检查）
        ids = re.findall(r'id="([^"]+)"\s+class="[^"]*caption', c)
        if any(not i.startswith("cg-") for i in ids):
            problems.append("captions.html: 字幕 id 必须用 cg-N 格式")

    idx = open(os.path.join(run, "index.html"), encoding="utf-8").read()
    for sc in slots["scenes"]:
        if f'data-composition-src="compositions/{sc["id"]}.html"' not in idx:
            problems.append(f"index.html 缺场景槽位 {sc['id']}")
        if sc["voice"] not in idx:
            problems.append(f"index.html 缺配音 {sc['voice']}")
    if 'data-composition-src="compositions/captions.html"' not in idx:
        problems.append("index.html 缺字幕合成")
    if f'data-duration="{slots["total"]}"' not in idx:
        problems.append("index.html 总时长与 slots.json 不一致")

    # 画面文字复述字幕 → 问题（画面该补充信息，不该重复旁白）
    for sid, role, rate, offenders in _echo_report(run, slots, subs):
        lim = ECHO_LIMIT[role]
        if rate > lim:
            bad = "、".join(f"「{b}」" for b, _ in offenders[:4])
            problems.append(
                f"{sid}.html: 画面文字有 {rate:.0%} 是字幕原话（上限 {lim:.0%}）"
                f"——字幕已经念过的话别再打一遍，改成数字/术语/对比项等新信息: {bad}")

    if problems:
        log("verify FAIL:")
        for p in problems:
            log("  - " + p)
        raise SystemExit(1)
    log(f"verify ok: {len(slots['scenes'])} 场景, "
        f"{sum(len(v['subs']) for v in subs.values())} 条字幕")


def cmd_subs_preview(args):
    """按字幕切分规则预览每个场景的字幕行（不跑 TTS, 纯文本切分）。

    给 ScriptQA 用: 审稿对象应该是观众实际读到的字幕行, 不是旁白原文。
    注意这里是最初的切分, TTS 之后 fit_cues 可能还会推迟出场或合并小段。
    """
    story = json.load(open(args.storyboard, encoding="utf-8"))
    for sc in story["scenes"]:
        log(f"[{sc['id']}]")
        for g in caption_groups(sc["narration"].strip())[0]:
            log(f"  {g['t']}  ({len(g['t'])}字/{g['w']}词)")


# ─────────────────────────── hf ───────────────────────────

def cmd_hf(args):
    """在 run 目录里跑 hyperframes CLI, 并保证 ffmpeg/ffprobe 能被找到。

    HyperFrames 只认 PATH / HYPERFRAMES_FFMPEG_PATH; 找不到 ffprobe 时
    check 会报「音频无法读取」, 渲染也会挂。
    """
    run = os.path.abspath(args.run_dir)
    env = dict(os.environ)
    d = ffmpeg_dir()
    if d:
        env["PATH"] = d + os.pathsep + env.get("PATH", "")
        env["HYPERFRAMES_FFMPEG_PATH"] = os.path.join(d, "ffmpeg.exe")
        env["HYPERFRAMES_FFPROBE_PATH"] = os.path.join(d, "ffprobe.exe")
    cmd = ["npx.cmd" if os.name == "nt" else "npx", "--yes", "hyperframes@0.9.19"] + args.rest
    log(f"$ {' '.join(cmd)}  (cwd={run})")
    proc = subprocess.run(cmd, cwd=run, env=env)
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)


def write_publish_txt(storyboard_path, dst_dir):
    """从 storyboard 里取发布文案，写成 08_视频号文案.txt（微信短视频标题+描述）。"""
    story = json.load(open(storyboard_path, encoding="utf-8"))
    title = story.get("publish_title", "").strip()[:15]
    desc = story.get("publish_desc", "").strip()[:20]
    if not (title and desc):
        log("  storyboard 缺 publish_title/publish_desc, 跳过发布文案 txt")
        return None
    out = os.path.join(dst_dir, "08_视频号文案.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"标题：{title}\n描述：{desc}\n")
    log(f"  发布文案: {out}")
    return out


def cmd_export(args):
    """把成片导出到桌面的项目文件夹（和 Word 稿同放，命名沿用 07_video.mp4 惯例）。"""
    run = os.path.abspath(args.run_dir)
    dst = os.path.abspath(args.dst_dir)
    os.makedirs(dst, exist_ok=True)
    if args.video:
        src = args.video
    else:
        mp4s = [os.path.join(run, f) for f in os.listdir(run) if f.endswith(".mp4")]
        if not mp4s:
            raise SystemExit(f"run 目录里没有 mp4: {run}")
        src = max(mp4s, key=os.path.getmtime)
    name, i = "07_video.mp4", 2
    while os.path.exists(os.path.join(dst, name)):
        name = f"07_video_v{i}.mp4"
        i += 1
    shutil.copyfile(src, os.path.join(dst, name))
    sb = os.path.join(run, "_work", "storyboard.json")
    if os.path.exists(sb):
        shutil.copyfile(sb, os.path.join(dst, "storyboard.json"))
        write_publish_txt(sb, dst)
    out = os.path.join(dst, name)
    log(f"export ok: {out}")
    return out


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("init", "tts", "build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--run-dir", required=True)
        if name == "tts":
            p.add_argument("--storyboard", required=True)
            p.add_argument("--voice")
            p.add_argument("--rate")
    p = sub.add_parser("subs-preview")
    p.add_argument("--storyboard", required=True)
    p = sub.add_parser("export")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--dst-dir", required=True)
    p.add_argument("--video")
    p = sub.add_parser("hf")
    p.add_argument("--run-dir", required=True)
    p.add_argument("rest", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    {"init": cmd_init, "tts": cmd_tts, "build": cmd_build,
     "verify": cmd_verify, "subs-preview": cmd_subs_preview, "hf": cmd_hf,
     "export": cmd_export}[args.cmd](args)


if __name__ == "__main__":
    main()
