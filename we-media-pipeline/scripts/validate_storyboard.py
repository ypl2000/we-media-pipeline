"""分镜脚本硬规则校验闸门（口径：Docs/storyboard-spec.md §3）。

输入是 `06_storyboard.json`：顶层 duration_s / route / scenes[] / facts[]，
每镜 id / role / visual_type / duration_s / narration。本脚本把 R1–R7 变成闸门：
首镜开场、字数预算、数字念法与事实出处/核实、时长路由、画面节奏、结构完整。
R6 同时卡两条：①相邻两镜 visual_type 必须不同；②相邻两镜不能都是「没人」画面
（chart/statement）；此外每连续 3 镜至少 1 镜 event/order。
R2（五问闸门）按约定交给 Review-Storyboard，脚本只报 skip、不判。
纯 Python 3 标准库，无第三方依赖，只读不写。

用法：
  python validate_storyboard.py storyboard.json   # 校验，失败 exit 1
  python validate_storyboard.py --selftest        # 跑内置夹具，通过 exit 0
"""
import argparse
import json
import re
import sys
from pathlib import Path

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
DIGIT_RE = re.compile(r"[0-9０-９]")
LATIN_RE = re.compile(r"[A-Za-z]{2,}")
RULES = ("R1", "R2", "R3", "R4", "R5", "R6", "R7")
SKIPPED_RULES = ("R2",)      # 五问闸门由 Review-Storyboard 负责

MIN_CJK_PER_SHOT = 6        # 每镜口播至少几个汉字
CHARS_PER_SEC = 5.5         # 语速基准：每秒几个汉字（曼波中文实测）
RATE_TOLERANCE = 0.08       # 字数预算 5.5 ±8%，即 5.06–5.94 字/秒
MIN_RATE = CHARS_PER_SEC * (1 - RATE_TOLERANCE)   # 5.06
MAX_RATE = CHARS_PER_SEC * (1 + RATE_TOLERANCE)   # 5.94
SUM_TOLERANCE = 0.3         # 各镜时长之和与顶层 duration_s 的容差（秒）
MIN_SHOTS, MAX_SHOTS = 4, 6
TEMPLATE_MAX_S = 12         # ≤12s 走模板线，>12s（13s 起）一律 EAC，不留灰区
HUMAN_VISUALS = ("event", "order")   # 有人的画面；相邻两镜不能都没有人

# NOTE: Docs §3 仍把 R2（五问闸门）列为硬规则；按负责人决定，五问由 Review-Storyboard
#       复核，本脚本只输出 skip、不计入 PASS/FAIL。口径变更时同步改 Docs 与这里。


def _text(value):
    """把任意字段安全转成字符串，None / 缺失都当空串。"""
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def _clip(text, limit=18):
    """截断长文本，避免错误信息被整句话撑爆。"""
    text = _text(text).replace("\n", " ").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _num(value):
    """数字字段转 float；bool 和字符串都算「不是数字」。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def fmt_num(value):
    """整数省掉小数点，其余保留一位，缺失显示「未知」。"""
    if value is None:
        return "未知"
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.1f}"


def cjk_count(text):
    """数一句话里的汉字个数（只认 \\u4e00-\\u9fff）。"""
    return len(CJK_RE.findall(_text(text)))


def _only_digits_and_punct(text):
    """整句只剩数字和标点（含空白）时返回 True，说明没写成话。"""
    compact = "".join(_text(text).split())
    return bool(compact) and all(ch.isdigit() or not ch.isalnum() for ch in compact)


def _scenes(storyboard):
    """取镜头列表；非 dict 的条目补成空 dict，保持镜号不串位。"""
    raw = storyboard.get("scenes")
    if not isinstance(raw, list):
        return []
    return [scene if isinstance(scene, dict) else {} for scene in raw]


def _label(scene, index):
    """错误信息里的镜号：镜1（hook）这种，优先用 id。"""
    scene_id = _text(scene.get("id")).strip()
    return f"镜{index + 1}（{scene_id}）" if scene_id else f"镜{index + 1}"


def _visual_type(scene):
    """取 visual_type，缺字段就是空串（不参与节奏判断）。"""
    return _text(scene.get("visual_type")).strip()


def check_r1(scenes):
    """R1：首镜第一句是「谁 + 何时 + 发生了什么」，不以数字/百分号开场。"""
    if not scenes:
        return ["没有任何镜头，无法判断首镜"]
    first = scenes[0]
    label = _label(first, 0)
    narration = _text(first.get("narration")).lstrip()
    if not narration:
        return [f"{label}: 首镜 narration 为空，无法判断开场方式"]
    head = narration[0]
    if head.isdigit() or head in ("%", "％"):
        return [
            f"{label}: 首镜 narration 以「{head}」开场（{_clip(narration, 16)}），"
            f"首句先交代谁、何时、发生了什么，数字挪到后文"
        ]
    return []


def check_r2(_scenes):
    """R2：五问闸门，按约定由 Review-Storyboard 复核，脚本不判。"""
    return []


def check_r3(stats):
    """R3：全片字数 / 时长必须落在 5.06–5.94 字/秒（5.5 ±8%）。"""
    duration = stats["duration"]
    if duration is None:
        return ["duration_s 缺失或不是数字，无法核对字数预算"]
    if duration <= 0:
        return [f"duration_s={fmt_num(duration)}，必须大于 0"]
    total, target, low, high = stats["chars"], stats["target"], stats["low"], stats["high"]
    rate = total / duration
    if total < low:
        return [
            f"全片 narration 共 {total} 个汉字，{total}/{fmt_num(duration)}s = {rate:.2f} 字/秒，"
            f"低于 {MIN_RATE:.2f} 下限（目标 {fmt_num(target)} 字，允许 {fmt_num(low)}~{fmt_num(high)}），"
            f"至少再补 {fmt_num(low - total)} 字"
        ]
    if total > high:
        return [
            f"全片 narration 共 {total} 个汉字，{total}/{fmt_num(duration)}s = {rate:.2f} 字/秒，"
            f"高于 {MAX_RATE:.2f} 上限（目标 {fmt_num(target)} 字，允许 {fmt_num(low)}~{fmt_num(high)}），"
            f"删掉 {fmt_num(total - high)} 字"
        ]
    return []


CN_DIGITS = "零一二三四五六七八九"


def _cn_int(number):
    """0–99999999 的整数转中文读法，够覆盖口播里的数字。"""
    if number == 0:
        return "零"
    units = ("", "十", "百", "千")
    big_units = ("", "万", "亿")
    sections = []
    while number > 0:
        sections.append(number % 10000)
        number //= 10000
    parts = []
    for index in range(len(sections) - 1, -1, -1):
        section = sections[index]
        if section == 0:
            if parts and parts[-1] != "零":
                parts.append("零")
            continue
        chunk = ""
        zero_pending = False
        for position in range(3, -1, -1):
            digit = (section // 10 ** position) % 10
            if digit:
                if zero_pending and chunk:
                    chunk += "零"
                chunk += CN_DIGITS[digit] + units[position]
                zero_pending = False
            elif chunk:
                zero_pending = True
        if chunk.startswith("一十"):
            chunk = chunk[1:]
        if index < len(sections) - 1 and section < 1000:
            chunk = "零" + chunk
        parts.append(chunk + big_units[index])
    return "".join(parts).rstrip("零") or "零"


def _cn_reading(token):
    """阿拉伯数字 token 转中文读法：41.3 → 四十一点三。"""
    if "." in token:
        whole, frac = token.split(".", 1)
        return _cn_int(int(whole)) + "点" + "".join(CN_DIGITS[int(d)] for d in frac)
    return _cn_int(int(token))


def _number_forms(token):
    """一个数字可能的旁白写法（阿拉伯原样 + 中文读法 + 「两」读法）。"""
    forms = {token}
    if len(token) >= 2:
        reading = _cn_reading(token)
        forms.add(reading)
        forms.add(re.sub(r"(?<![十百千])二(?=[百千万])", "两", reading))
    return forms


def _fact_used_in_narration(claim, narrations):
    """claim 里的数字（阿拉伯或中文读法）是否已经写进旁白。"""
    for token in re.findall(r"\d+(?:\.\d+)?", claim):
        if any(form in narration for form in _number_forms(token) for narration in narrations):
            return True
    return False
def check_r4(storyboard, scenes):
    """R4：narration 写中文读法（无数字/%/拉丁串）；facts 数字要 http 出处且经过核实。"""
    errors = []
    narrations = []
    for index, scene in enumerate(scenes):
        label = _label(scene, index)
        narration = _text(scene.get("narration"))
        narrations.append(narration)
        bad = []
        match = DIGIT_RE.search(narration)
        if match:
            bad.append(f"数字「{match.group(0)}」")
        if "%" in narration or "％" in narration:
            bad.append("百分号「%」")
        match = LATIN_RE.search(narration)
        if match:
            bad.append(f"英文「{match.group(0)}」")
        if bad:
            errors.append(
                f"{label}: narration 含{'、'.join(bad)}，旁白必须念中文"
                f"（如 41.3% → 百分之四十一点三，AI → 人工智能），英文名/版本号放 visual"
            )
    raw = storyboard.get("facts")
    if raw is None:
        return errors  # facts 是可选字段，没写就不判
    if not isinstance(raw, list):
        errors.append("facts 必须是数组，每项含 claim / source / verified")
        return errors
    for index, fact in enumerate(raw, 1):
        fact = fact if isinstance(fact, dict) else {}
        claim = _text(fact.get("claim"))
        if not DIGIT_RE.search(claim):
            continue  # 没有数字的论断不强制出处
        source = _text(fact.get("source")).strip()
        if not source.startswith(("http://", "https://")):
            errors.append(
                f"facts[{index}]「{_clip(claim, 16)}」含数字，"
                f"但 source 不是 http(s) 链接（现在是「{_clip(source, 24) or '空'}」）"
            )
        if fact.get("verified") is not True and _fact_used_in_narration(claim, narrations):
            errors.append(
                f"facts[{index}]「{_clip(claim, 16)}」verified 不是 true，"
                f"但数字已经写进旁白（fact_unverified）；先核实并标 true，或删掉旁白里的数字"
            )
    return errors


def check_r5(storyboard):
    """R5：duration_s ≤12 → template；>12（13s 起）→ eac，按 12 秒一刀切。"""
    duration = _num(storyboard.get("duration_s"))
    if duration is None:
        return ["duration_s 缺失或不是数字，无法判定时长路由"]
    if duration <= 0:
        return [f"duration_s={fmt_num(duration)}，必须大于 0"]
    route = _text(storyboard.get("route")).strip()
    if duration <= TEMPLATE_MAX_S:
        if route != "template":
            return [
                f"duration_s={fmt_num(duration)}s ≤{TEMPLATE_MAX_S}s，route 应为 template"
                f"（现在是「{route or '空'}」）"
            ]
        return []
    if route != "eac":
        return [
            f"duration_s={fmt_num(duration)}s >{TEMPLATE_MAX_S}s，route 应为 eac"
            f"（13s 起按 12 秒一刀切，不留灰区；现在是「{route or '空'}」）"
        ]
    return []


def check_r6(scenes):
    """R6：①相邻两镜 visual_type 不得相同；②相邻两镜不得都是「没人」画面（chart/statement）。"""
    errors = []
    types = [_visual_type(scene) for scene in scenes]
    for index in range(1, len(scenes)):
        prev_type, cur_type = types[index - 1], types[index]
        if not prev_type or not cur_type:
            continue
        if prev_type == cur_type:
            errors.append(
                f"{_label(scenes[index - 1], index - 1)}→{_label(scenes[index], index)}: "
                f"相邻两镜都是 {prev_type}，相邻镜 visual_type 必须不同"
            )
        elif prev_type not in HUMAN_VISUALS and cur_type not in HUMAN_VISUALS:
            errors.append(
                f"{_label(scenes[index - 1], index - 1)}→{_label(scenes[index], index)}: "
                f"相邻两镜都是「没人」画面（{prev_type}→{cur_type}），至少一镜换成 event/order"
            )
    for index in range(len(scenes) - 2):
        window = types[index:index + 3]
        if all(window) and not any(kind in HUMAN_VISUALS for kind in window):
            errors.append(
                f"{_label(scenes[index], index)}–{_label(scenes[index + 2], index + 2)}: "
                f"连续三镜（{'/'.join(window)}）里没有 event/order，补一镜有人、有动作的"
            )
    return errors


def check_r7(storyboard, scenes):
    """R7：4–6 镜；首 hook 末 outro；id 唯一且前两字母不重复；时长合计 ±0.3s。"""
    errors = []
    if not scenes:
        hint = "（检测到旧字段 shots，请改成 scenes）" if "shots" in storyboard else ""
        return [f"没有任何镜头，至少需要 {MIN_SHOTS} 个{hint}"]
    if not MIN_SHOTS <= len(scenes) <= MAX_SHOTS:
        errors.append(f"共 {len(scenes)} 个镜头，必须在 {MIN_SHOTS}–{MAX_SHOTS} 个之间")

    first_role = _text(scenes[0].get("role")).strip()
    if first_role != "hook":
        errors.append(f"{_label(scenes[0], 0)}: 首镜 role 是「{first_role or '空'}」，必须是 hook")
    last_role = _text(scenes[-1].get("role")).strip()
    if last_role != "outro":
        errors.append(
            f"{_label(scenes[-1], len(scenes) - 1)}: 末镜 role 是「{last_role or '空'}」，必须是 outro"
        )

    seen_ids, seen_prefix = {}, {}
    for index, scene in enumerate(scenes):
        scene_id = _text(scene.get("id")).strip()
        if not scene_id:
            errors.append(f"{_label(scene, index)}: 缺 id（小写英文单词，全片唯一，前两字母不许重复）")
            continue
        if scene_id in seen_ids:
            errors.append(
                f"{_label(scene, index)}: id「{scene_id}」重复（镜{seen_ids[scene_id] + 1} 已用过）"
            )
        else:
            seen_ids[scene_id] = index
        if len(scene_id) < 2:
            errors.append(f"{_label(scene, index)}: id「{scene_id}」不足 2 个字母，无法满足前两字母唯一")
            continue
        prefix = scene_id[:2].lower()
        if prefix in seen_prefix and seen_prefix[prefix] != scene_id:
            errors.append(
                f"{_label(scene, index)}: id「{scene_id}」前两字母「{prefix}」"
                f"与「{seen_prefix[prefix]}」重复"
            )
        else:
            seen_prefix.setdefault(prefix, scene_id)

    duration = _num(storyboard.get("duration_s"))
    total = 0.0
    complete = True
    for index, scene in enumerate(scenes):
        shot_duration = _num(scene.get("duration_s"))
        if shot_duration is None:
            complete = False
            hint = "（旧字段 t 已废弃，改用单镜 duration_s）" if "t" in scene else ""
            errors.append(f"{_label(scene, index)}: 缺 duration_s 或不是数字{hint}")
            continue
        total += shot_duration
    if complete and duration is not None and abs(total - duration) > SUM_TOLERANCE:
        errors.append(
            f"各镜 duration_s 合计 {fmt_num(total)}s，与顶层 duration_s={fmt_num(duration)}s "
            f"差 {fmt_num(abs(total - duration))}s（容差 {SUM_TOLERANCE}s）"
        )
    return errors


def collect_stats(storyboard):
    """统计镜头数、总字数、目标字数与允许区间（R3 的判定依据）。

    总字数按旁白汉字数（CJK）计，与 R2 同口径；标点不占字数预算。
    """
    scenes = _scenes(storyboard)
    chars = sum(cjk_count(scene.get("narration")) for scene in scenes)
    duration = _num(storyboard.get("duration_s"))
    target = duration * CHARS_PER_SEC if duration is not None else None
    low = target * (1 - RATE_TOLERANCE) if target is not None else None
    high = target * (1 + RATE_TOLERANCE) if target is not None else None
    return {"scenes": len(scenes), "chars": chars, "duration": duration,
            "target": target, "low": low, "high": high}


def validate(storyboard):
    """跑全部规则，返回 (results, stats)；纯函数，不改入参。"""
    scenes = _scenes(storyboard)
    stats = collect_stats(storyboard)
    results = {
        "R1": check_r1(scenes),
        "R2": check_r2(scenes),
        "R3": check_r3(stats),
        "R4": check_r4(storyboard, scenes),
        "R5": check_r5(storyboard),
        "R6": check_r6(scenes),
        "R7": check_r7(storyboard, scenes),
    }
    return results, stats


def is_pass(results):
    """所有硬规则都没有错误才算过（R2 是 skip，不算失败）。"""
    return not any(results[rule] for rule in RULES)


def render_report(results, stats):
    """拼出人读的校验报告：结论、逐条规则、统计。"""
    lines = ["PASS" if is_pass(results) else "FAIL"]
    for rule in RULES:
        if rule in SKIPPED_RULES:
            lines.append(
                f"{rule} skip 五问闸门（谁/何时/发生了什么/为什么/所以呢）由 Review-Storyboard 复核，脚本不判"
            )
        elif results[rule]:
            lines.extend(f"{rule} FAIL {error}" for error in results[rule])
        else:
            lines.append(f"{rule} ok")
    lines.append("")
    lines.append(f"镜头数: {stats['scenes']}")
    lines.append(f"总字数: {stats['chars']}")
    if stats["target"] is None:
        lines.append("目标字数: 未知（duration_s 缺失）")
        lines.append("允许区间: 未知")
    else:
        lines.append(f"目标字数: {fmt_num(stats['target'])}（{fmt_num(stats['duration'])}s × {CHARS_PER_SEC}）")
        lines.append(f"允许区间: {fmt_num(stats['low'])} ~ {fmt_num(stats['high'])}（{MIN_RATE:.2f}–{MAX_RATE:.2f} 字/秒）")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# 自测夹具：Docs 示例 + 7 个反例（首镜数字 / 字数不足 / 路由 / 相邻同类 /
# 相邻都没人 / verified:false / 结构+出处）
# --------------------------------------------------------------------------

def _scene(scene_id, role, visual_type, duration_s, narration):
    """快速拼一镜，visual 只写占位说明。"""
    return {"id": scene_id, "role": role, "visual_type": visual_type,
            "duration_s": duration_s, "narration": narration, "visual": "分镜示意"}


def _story(scenes, duration_s=30, route="eac", facts=None):
    """快速拼一份分镜稿。"""
    story = {"title": "自测用分镜", "publish_title": "自测", "publish_desc": "自测",
             "voice": "zh-CN-YunxiNeural", "duration_s": duration_s, "route": route,
             "scenes": scenes}
    if facts is not None:
        story["facts"] = facts
    return story


def _fixture_docs():
    """Docs §2 的 30 秒示例，必须 PASS。"""
    return {
        "schema_version": "1.0",
        "title": "谷歌发布 Gemini 4 Carbon：模型自己动手改页面",
        "publish_title": "谷歌让模型自己动手",
        "publish_desc": "测试员整夜盯的那些点击，它自己点完了",
        "voice": "zh-CN-YunxiNeural",
        "rate": "+0%",
        "duration_s": 30,
        "route": "eac",
        "units_per_sec": 5.5,
        "scenes": [
            {"id": "hook", "role": "hook", "visual_type": "event", "duration_s": 5.6,
             "narration": "昨天下午，谷歌的工程师把一段演示丢进内部测试群，群里安静了整整十秒。",
             "visual": "会议室斜角，桌上摊开两台笔记本电脑；前屏映着一段网页测试录像的缩略图。"
                       "左上角小字『内部测试群 · 昨天 15:40』，画面中央只有一行大字『十秒没人说话』",
             "elements": "内部测试群 · 昨天 15:40 / 十秒没人说话"},
            {"id": "chart", "role": "body", "visual_type": "chart", "duration_s": 5.0,
             "narration": "测试清单上一共三十七个网页任务，它自己一口气跑完了三十六个。",
             "visual": "上方一条进度条，37 格点亮 36 格，右端标注『37 个任务 / 36 个通过』；"
                       "下方一行灰字『剩下的那个卡在银行验证码』",
             "elements": "37 个任务 / 36 个通过 / 卡在验证码"},
            {"id": "order", "role": "body", "visual_type": "order", "duration_s": 5.6,
             "narration": "它干活的方式很简单，先看一眼页面，再点按钮，点错了就退回上一步重来。",
             "visual": "三张流程卡从左到右排开：① 读页面 ② 点按钮 ③ 点错就回退；"
                       "卡片之间画箭头，箭头上一律不写字",
             "elements": "读页面 / 点按钮 / 点错就回退"},
            {"id": "statement", "role": "body", "visual_type": "statement", "duration_s": 4.9,
             "narration": "它敢自己动手，是因为看屏幕和动手在它这里本来就是同一件事。",
             "visual": "左右两块并排：左块写『看』、右块写『点』，中间用一条实线焊在一起；"
                       "下方一行小字『同一件事』",
             "elements": "看 / 点 / 同一件事"},
            {"id": "event", "role": "body", "visual_type": "event", "duration_s": 5.0,
             "narration": "演示到一半，它发现报价页把城市填错了，自己绕回去改掉了那一栏。",
             "visual": "网页表单局部：城市一栏套红框；一条虚线鼠标轨迹从确认按钮绕回这一栏，"
                       "轨迹末端一个光标",
             "elements": "城市 / 填错了 / 绕回去改"},
            {"id": "outro", "role": "outro", "visual_type": "order", "duration_s": 3.9,
             "narration": "所以以后有些软件测试，真的不用人整夜盯着屏幕了。",
             "visual": "一条夜间时间轴：左侧一批手动点击的灰点，右侧同一批点变成自动的亮点；"
                       "底部居中一行『点赞 · 关注』",
             "elements": "手动 / 自动 / 点赞 · 关注"},
        ],
        "facts": [
            {"claim": "37 个网页任务里 36 个一次跑通",
             "source": "https://blog.google/technology/ai/", "verified": True},
            {"claim": "演示全程无人干预，模型自己点完并回退修正",
             "source": "https://blog.google/technology/ai/", "verified": True},
        ],
    }


def _fixture_digit_open():
    """首镜以 41.3% 开场：R1 失败，数字/百分号连带 R4 失败。"""
    return _story([
        _scene("hook", "hook", "event", 7.5,
               "41.3% 的团队今年开始用工具做视频，成本直接砍半，交付周期也短了一半，省下的时间全用来打磨内容。"),
        _scene("chart", "body", "chart", 7.5,
               "他们把选题、脚本、配音和剪辑拆成四条流水线，每条都有人盯，每人只负责其中一段，交付前再统一过一遍。"),
        _scene("order", "body", "order", 7.5,
               "第三步是把成片分发到五个平台，同一个版本不用二次剪辑，省下的时间用来打磨标题。"),
        _scene("outro", "outro", "statement", 7.5,
               "所以流程跑通之后，先请一个人专门把关，再谈全自动也不迟，别急着追求无人值守。"),
    ])


def _fixture_budget_low():
    """5 镜共 86 个汉字 / 30s ≈ 2.87 字/秒，触发 R3。"""
    return _story([
        _scene("hook", "hook", "event", 6, "他们把小团队的片子拆成五个环节，每个环节有人盯。"),
        _scene("chart", "body", "order", 6, "先定选题，再把脚本压短，最后才动手剪。"),
        _scene("order", "body", "chart", 6, "流程跑顺之后，同样时间能多出三条成片。"),
        _scene("statement", "body", "order", 6, "所以别再纠结设备，先把清单贴在墙上。"),
        _scene("outro", "outro", "event", 6, "谁来都能接着做，不用再问一遍流程。"),
    ])


def _fixture_route_mismatch():
    """15s 却写 route=template：R5 失败（13s 起必须 eac）。"""
    return _story([
        _scene("hook", "hook", "event", 3, "团队把片子拆成五个环节，每步有人盯。"),
        _scene("chart", "body", "chart", 3, "先定选题，再把脚本压短，最后才动手。"),
        _scene("order", "body", "order", 3, "流程跑顺以后，同样时间多出三条成片。"),
        _scene("statement", "body", "statement", 3, "所以别纠结设备，先把清单贴在墙上。"),
        _scene("outro", "outro", "event", 3, "谁来都能接着做，不用再问一遍流程。"),
    ], duration_s=15, route="template")


def _fixture_visual_repeat():
    """第 2、3 镜同为 chart，触发 R6（字数仍达标，避免误伤 R3）。"""
    return _story([
        _scene("hook", "hook", "event", 7.5,
               "上周三下午，一家做家电测评的小团队把三小时的素材丢进剪辑台，十分钟就出了初稿，大家都愣住了。"),
        _scene("chart", "body", "chart", 7.5,
               "过去要剪一整天，现在粗剪只占半小时，剩下的时间全花在打磨标题和封面上，返工也少了。"),
        _scene("repeat", "body", "chart", 7.5,
               "他们的做法很土，先让工具把重复的粗剪跑完，人再回头挑重点、改顺序，一条片子省半天。"),
        _scene("order", "outro", "order", 7.5,
               "所以别再问工具会不会取代人，先问自己有没有把流程理顺，再决定要不要买新设备，再动手也不迟。"),
    ])


def _fixture_visual_no_human():
    """第 2、3 镜 chart→statement：相邻两镜都没人，R6 严格版失败（旧版会漏）。"""
    return _story([
        _scene("hook", "hook", "event", 7.5,
               "上周三下午，一家做家电测评的小团队把三小时的素材丢进剪辑台，十分钟就出了初稿，大家都愣住了，谁也没说话。"),
        _scene("chart", "body", "chart", 7.5,
               "过去要剪一整天，现在粗剪只占半小时，剩下的时间全花在打磨标题和封面上，返工也少了。"),
        _scene("repeat", "body", "statement", 7.5,
               "他们的做法很土，先让工具把重复的粗剪跑完，人再回头挑重点、改顺序，一条片子省半天。"),
        _scene("order", "outro", "order", 7.5,
               "所以别再问工具会不会取代人，先问自己有没有把流程理顺，再决定要不要买新设备，再动手也不迟。"),
    ])


def _fixture_fact_unverified():
    """旁白用中文念了 41.3%，对应 fact 却 verified:false，R4 失败。"""
    return _story([
        _scene("hook", "hook", "event", 7.5,
               "百分之四十一点三的团队今年开始用工具做视频，成本直接砍半，交付周期也短了一半，省下的时间全用来打磨内容。"),
        _scene("chart", "body", "chart", 7.5,
               "他们把选题、脚本、配音和剪辑拆成四条流水线，每条都有人盯，每人只负责其中一段，交付前再统一过一遍。"),
        _scene("order", "body", "order", 7.5,
               "第三步是把成片分发到五个平台，同一个版本不用二次剪辑，省下的时间用来打磨标题。"),
        _scene("outro", "outro", "statement", 7.5,
               "所以流程跑通之后，先请一个人专门把关，再谈全自动也不迟，别急着追求无人值守。"),
    ], facts=[
        {"claim": "41.3% 的团队已经用上工具",
         "source": "https://example.com/data", "verified": False},
    ])


def _fixture_structure_and_facts():
    """末镜 role 不是 outro、id 重复、facts 缺 http 出处：R4 + R7 失败。"""
    return _story([
        _scene("hook", "hook", "event", 7.5,
               "上周三下午，一家做家电测评的小团队把三小时的素材丢进剪辑台，十分钟就出了初稿，大家都愣住了，谁也没说话。"),
        _scene("chart", "body", "chart", 7.5,
               "过去要剪一整天，现在粗剪只占半小时，剩下的时间全花在打磨标题和封面上，返工也少了。"),
        _scene("order", "body", "order", 7.5,
               "他们的做法很土，先让工具把重复的粗剪跑完，人再回头挑重点、改顺序，一条片子省半天。"),
        _scene("chart", "body", "statement", 7.5,
               "所以要先把流程理顺，再决定买什么设备，顺序反过来只会多花钱，别急着上设备。"),
    ], facts=[
        {"claim": "41.3% 的团队已经用上工具", "source": "内部估算", "verified": False},
        {"claim": "交付周期缩短一半", "source": "", "verified": False},
    ])


def run_selftest():
    """跑夹具，核对失败规则集合，符合预期才 exit 0。"""
    cases = [
        ("Docs 30 秒示例（必须 PASS）", _fixture_docs(), set()),
        ("首镜数字开场（R1，连带 R4）", _fixture_digit_open(), {"R1", "R4"}),
        ("字数低于 5.06 字/秒（R3）", _fixture_budget_low(), {"R3"}),
        ("13s 起仍写 template（R5）", _fixture_route_mismatch(), {"R5"}),
        ("相邻两镜同为 chart（R6 第①条）", _fixture_visual_repeat(), {"R6"}),
        ("相邻 chart→statement 都没人（R6 第②条）", _fixture_visual_no_human(), {"R6"}),
        ("数字进旁白但 verified:false（R4）", _fixture_fact_unverified(), {"R4"}),
        ("末镜/ id / facts 出处（R4 + R7）", _fixture_structure_and_facts(), {"R4", "R7"}),
    ]
    all_ok = True
    for title, storyboard, expected in cases:
        results, stats = validate(storyboard)
        actual = {rule for rule in RULES if results[rule]}
        ok = actual == expected
        all_ok = all_ok and ok
        print(f"=== {title} ===")
        print(render_report(results, stats))
        print(f"期望失败: {', '.join(sorted(expected)) or '无'}；实际失败: {', '.join(sorted(actual)) or '无'} → {'符合' if ok else '不符合'}")
        print()
    print("自测通过" if all_ok else "自测失败：夹具结果与预期不一致")
    return 0 if all_ok else 1


def enable_utf8_stdio():
    """管道输出时 Python 在 Windows 默认用 GBK，先切 UTF-8，中文才不乱码。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "isatty") and not stream.isatty() and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass


def build_parser():
    """命令行参数：一个位置参数，或 --selftest。"""
    parser = argparse.ArgumentParser(description="校验分镜脚本的七条硬规则（R1–R7）")
    parser.add_argument("storyboard", nargs="?", help="storyboard.json 路径")
    parser.add_argument("--selftest", action="store_true", help="跑内置夹具，打印每条规则结果")
    return parser


def main(argv=None):
    """入口：校验文件或自测；PASS 返回 0，FAIL 返回 1。"""
    enable_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.selftest:
        return run_selftest()
    if not args.storyboard:
        parser.error("缺少 storyboard.json 路径；或加 --selftest 跑内置夹具")
    try:
        data = json.loads(Path(args.storyboard).read_text(encoding="utf-8-sig"))
    except OSError as exc:
        print(f"读不了文件：{exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"JSON 解析失败：{exc}", file=sys.stderr)
        return 2
    if not isinstance(data, dict):
        print("顶层必须是 JSON 对象（含 duration_s / route / scenes）", file=sys.stderr)
        return 2
    results, stats = validate(data)
    print(render_report(results, stats))
    return 0 if is_pass(results) else 1


if __name__ == "__main__":
    sys.exit(main())
