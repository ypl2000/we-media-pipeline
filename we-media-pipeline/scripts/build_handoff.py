#!/usr/bin/env python3
"""从分镜确定性生成 EAC handoff，并校验现有 handoff 是否与分镜一致。

handoff 是派生产物，不是事实源：同一份 06_storyboard.json 永远生成同一份
08_eac_handoff.json（generated_at 除外）。渲染前用 --verify 比对，不一致就
重新生成，禁止手改。

用法:
    python build_handoff.py 06_storyboard.json
    python build_handoff.py 06_storyboard.json -o %TEMP%/08_eac_handoff.json
    python build_handoff.py 06_storyboard.json --verify
    python build_handoff.py --selftest

退出码:
    0  生成成功 / 校验一致 / 自测通过
    1  校验不一致
    2  输入缺失或不合法
"""
import argparse
import hashlib
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HANDOFF_FILENAME = "08_eac_handoff.json"
DEFAULT_ROUTE = "eac"
DEFAULT_VOICE = "mambo-zh"
DEFAULT_RATE = "+0%"

MOTION_BY_VISUAL_TYPE = {
    "event": "zoom-in",
    "order": "pan-right",
    "chart": "zoom-in",
    "statement": "pan-left",
}

TOP_LEVEL_KEYS = (
    "project",
    "engine",
    "route",
    "duration_s",
    "title",
    "publish_title",
    "publish_desc",
    "voice",
    "rate",
    "source",
    "storyboard_sha256",
    "generated_at",
    "clips",
    "vo_script",
    "facts",
    "review",
    "instructions",
)

INSTRUCTIONS = [
    "这是交给 EAC（MCP 工具）的镜头清单，本仓库不执行渲染。",
    "渲染前先用 `python build_handoff.py 06_storyboard.json --verify` 校验本文件，不一致就重新生成，不要手改。",
    "path=pending 的镜头需要先补素材；motion 只用 zoom-in/pan，禁用 zoom-out；caption、narration、vo 必须与分镜逐字一致。",
]

_MISSING = object()


class HandoffError(Exception):
    """输入不合法或运行失败，携带进程退出码。"""

    def __init__(self, message, code=2):
        super().__init__(message)
        self.code = code


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fmt(value):
    if value is _MISSING:
        return "缺失"
    return json.dumps(value, ensure_ascii=False)


def _scene_label(index):
    return f"第 {index} 镜"


def load_storyboard(path):
    """读取分镜原始字节并解析，返回 (raw_bytes, dict)。"""
    path = Path(path).expanduser()
    if not path.exists():
        raise HandoffError(f"找不到分镜文件：{path}")
    if not path.is_file():
        raise HandoffError(f"分镜路径不是文件：{path}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise HandoffError(f"读取分镜失败：{path}（{exc}）") from exc
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HandoffError(f"分镜文件不是 UTF-8 编码：{path}（{exc}）") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HandoffError(
            f"分镜 JSON 不合法：第 {exc.lineno} 行第 {exc.colno} 列，{exc.msg}"
        ) from exc
    if not isinstance(data, dict):
        raise HandoffError("分镜顶层必须是 JSON 对象")
    return raw, data


def resolve_motion(scene, index):
    """取镜头运镜；显式 motion.type 优先，否则按 visual_type 映射。"""
    motion = scene.get("motion")
    motion_type = None
    if motion is not None:
        if not isinstance(motion, dict):
            raise HandoffError(
                f'{_scene_label(index)}的 motion 必须是对象，例如 {{"type": "zoom-in", "amount": 0.06}}'
            )
        value = motion.get("type")
        if isinstance(value, str) and value:
            motion_type = value

    if motion_type == "zoom-out":
        raise HandoffError(
            f'{_scene_label(index)}的 motion.type 是 "zoom-out"，R9 已禁用'
            "（满画幅素材会在镜尾露黑边）；请改成 zoom-in 或 pan-left/pan-right/pan-up/pan-down"
        )
    if motion_type:
        return motion_type

    visual_type = scene.get("visual_type")
    if isinstance(visual_type, str) and visual_type in MOTION_BY_VISUAL_TYPE:
        return MOTION_BY_VISUAL_TYPE[visual_type]
    shown = _fmt(visual_type) if isinstance(visual_type, str) else "缺失"
    raise HandoffError(
        f"{_scene_label(index)}的 motion 未指定，visual_type {shown} 也没有默认运镜；"
        "请补 motion.type，或把 visual_type 改成 event/order/chart/statement"
    )


def _scene_text(scene, key, index):
    value = scene.get(key, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise HandoffError(f"{_scene_label(index)}的 {key} 必须是字符串")
    return value


def build_clips(story):
    """按 scenes 顺序生成 clips，start 从 0 累加并 round 到 3 位小数。"""
    scenes = story.get("scenes")
    if not isinstance(scenes, list):
        raise HandoffError("分镜缺少 scenes 数组（应为镜头对象列表）")

    clips = []
    start = 0.0
    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            raise HandoffError(f"{_scene_label(index)}不是 JSON 对象")
        shot_id = scene.get("id")
        if not isinstance(shot_id, str) or not shot_id:
            raise HandoffError(f'{_scene_label(index)}缺少 id（镜头标识，例如 "hook"）')
        duration = scene.get("duration_s")
        if not _is_number(duration) or duration <= 0:
            raise HandoffError(f"{_scene_label(index)}的 duration_s 必须是大于 0 的数字")
        narration = scene.get("narration")
        if not isinstance(narration, str):
            raise HandoffError(f"{_scene_label(index)}缺少 narration（旁白文本，必须是字符串）")
        visual_type = scene.get("visual_type", "")
        if not isinstance(visual_type, str):
            raise HandoffError(f"{_scene_label(index)}的 visual_type 必须是字符串")

        clips.append(
            {
                "shot_id": shot_id,
                "path": "pending",
                "start": round(start, 3),
                "duration": duration,
                "motion": resolve_motion(scene, index),
                "caption": narration,
                "narration": narration,
                "vo": narration,
                "visual": _scene_text(scene, "visual", index),
                "elements": _scene_text(scene, "elements", index),
                "visual_type": visual_type,
            }
        )
        start += duration
    return clips


def build_handoff(story, raw, storyboard_path, generated_at=None):
    """返回 handoff dict；键顺序固定，generated_at 可注入以做确定性测试。"""
    if not _is_number(story.get("duration_s")) or story["duration_s"] <= 0:
        raise HandoffError("分镜缺少顶层 duration_s（视频总时长，单位秒，必须是大于 0 的数字）")

    clips = build_clips(story)

    title = story.get("title")
    if not isinstance(title, str):
        title = ""
    publish_title = story.get("publish_title")
    if not isinstance(publish_title, str):
        publish_title = ""
    publish_desc = story.get("publish_desc")
    if not isinstance(publish_desc, str):
        publish_desc = ""

    review_value = story.get("review")
    if review_value is None:
        review = {"storyboard_approved": True, "problems": []}
    elif isinstance(review_value, dict):
        problems = review_value.get("problems", [])
        if not isinstance(problems, list):
            raise HandoffError("分镜 review.problems 必须是数组")
        review = {
            "storyboard_approved": review_value.get("storyboard_approved", True),
            "problems": problems,
        }
    else:
        raise HandoffError(
            '分镜顶层 review 必须是对象，例如 {"storyboard_approved": true, "problems": []}'
        )

    facts = story.get("facts", [])
    if facts is None:
        facts = []
    if not isinstance(facts, list):
        raise HandoffError("分镜顶层 facts 必须是数组（按原顺序搬进 handoff）")

    route = story.get("route")
    voice = story.get("voice")
    rate = story.get("rate")

    storyboard_dir = Path(storyboard_path).expanduser().resolve().parent

    doc = {
        "project": title,
        "engine": "eac",
        "route": route if isinstance(route, str) and route else DEFAULT_ROUTE,
        "duration_s": story["duration_s"],
        "title": title,
        "publish_title": publish_title,
        "publish_desc": publish_desc,
        "voice": voice if isinstance(voice, str) and voice else DEFAULT_VOICE,
        "rate": rate if isinstance(rate, str) and rate else DEFAULT_RATE,
        "source": {
            "storyboard": str(Path(storyboard_path).expanduser().resolve()),
            "content": str(storyboard_dir / "06_content.json"),
            "article": str(storyboard_dir / "03_article.md"),
        },
        "storyboard_sha256": hashlib.sha256(raw).hexdigest(),
        "generated_at": generated_at if generated_at is not None else _utc_now(),
        "clips": clips,
        "vo_script": "".join(clip["narration"] for clip in clips),
        "facts": facts,
        "review": review,
        "instructions": list(INSTRUCTIONS),
    }
    return doc


def write_handoff(doc, path):
    """UTF-8 无 BOM、LF、indent=2，键顺序即 dict 插入顺序。"""
    path = Path(path).expanduser()
    if not path.parent.exists():
        raise HandoffError(f"输出目录不存在：{path.parent}")
    text = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    try:
        with path.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    except OSError as exc:
        raise HandoffError(f"写入 handoff 失败：{path}（{exc}）") from exc


def verify(story_path, handoff_path):
    """返回差异列表；空列表表示一致。generated_at 不参与比较。"""
    raw, story = load_storyboard(story_path)
    expected = build_handoff(story, raw, story_path)

    handoff_path = Path(handoff_path).expanduser()
    if not handoff_path.exists():
        return [f"找不到 handoff 文件：{handoff_path}（先运行生成模式）"]
    if not handoff_path.is_file():
        return [f"handoff 路径不是文件：{handoff_path}"]
    try:
        text = handoff_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise HandoffError(f"读取 handoff 失败：{handoff_path}（{exc}）") from exc
    try:
        actual = json.loads(text)
    except json.JSONDecodeError as exc:
        return [f"handoff 不是合法 JSON：第 {exc.lineno} 行第 {exc.colno} 列，{exc.msg}"]
    if not isinstance(actual, dict):
        return ["handoff 顶层必须是 JSON 对象"]

    diffs = []

    actual_sha = actual.get("storyboard_sha256", _MISSING)
    if actual_sha != expected["storyboard_sha256"]:
        diffs.append(
            f"字段 storyboard_sha256 期望 {_fmt(expected['storyboard_sha256'])} "
            f"实际 {_fmt(actual_sha)}（分镜已改动，请重新生成 handoff）"
        )

    expected_clips = expected["clips"]
    actual_clips = actual.get("clips", _MISSING)
    if not isinstance(actual_clips, list):
        diffs.append(
            f"字段 clips 期望 {len(expected_clips)} 个镜头的数组 实际 {_fmt(actual_clips)}"
        )
        actual_clips = []
    elif len(actual_clips) != len(expected_clips):
        diffs.append(
            f"字段 clips 数量期望 {len(expected_clips)} 实际 {len(actual_clips)}"
            "（镜头数必须与 scenes 一致）"
        )

    for index, exp in enumerate(expected_clips, start=1):
        if index > len(actual_clips):
            break
        act = actual_clips[index - 1]
        label = _scene_label(index)
        if not isinstance(act, dict):
            diffs.append(f"{label}：clips 条目不是 JSON 对象，期望 {_fmt(exp['shot_id'])} 的镜头对象")
            continue
        for field in ("motion", "start", "duration", "caption", "narration", "vo"):
            act_value = act.get(field, _MISSING)
            if act_value != exp[field]:
                diffs.append(
                    f"{label}：字段 {field} 期望 {_fmt(exp[field])} 实际 {_fmt(act_value)}"
                )

    return diffs


def _write_json(path, obj):
    with Path(path).open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def _selftest_storyboard():
    return {
        "title": "自测分镜",
        "publish_title": "自测标题",
        "publish_desc": "自测摘要",
        "voice": "mambo-zh",
        "rate": "+0%",
        "duration_s": 9,
        "route": "eac",
        "scenes": [
            {
                "id": "hook",
                "visual_type": "event",
                "duration_s": 3.5,
                "narration": "第一镜旁白。",
                "visual": "画面一",
                "elements": "元素一",
                "motion": {"type": "zoom-in", "amount": 0.05},
            },
            {
                "id": "body",
                "visual_type": "order",
                "duration_s": 3.5,
                "narration": "第二镜旁白。",
                "visual": "画面二",
                "elements": "元素二",
            },
            {
                "id": "outro",
                "visual_type": "statement",
                "duration_s": 1.5,
                "narration": "第三镜旁白。",
                "visual": "画面三",
                "elements": "元素三",
            },
        ],
        "facts": [
            {"claim": "自测事实", "source": "https://example.com", "verified": True}
        ],
    }


def run_selftest():
    checks = []

    def check(name, fn):
        try:
            detail = fn()
            checks.append((name, True, detail or "通过"))
        except Exception as exc:  # 自测要把断言失败收敛成 FAIL，而不是中断
            checks.append((name, False, f"{type(exc).__name__}: {exc}"))

    with tempfile.TemporaryDirectory(prefix="build_handoff_selftest_") as tmp:
        tmp_dir = Path(tmp)
        story_path = tmp_dir / "06_storyboard.json"
        handoff_path = tmp_dir / HANDOFF_FILENAME
        story = _selftest_storyboard()
        _write_json(story_path, story)

        def case_generate_verify():
            raw, loaded = load_storyboard(story_path)
            doc = build_handoff(
                loaded, raw, story_path, generated_at="2026-01-01T00:00:00Z"
            )
            doc_again = build_handoff(
                loaded, raw, story_path, generated_at="2026-01-01T00:00:00Z"
            )
            assert doc == doc_again, "同一输入两次生成结果不一致"
            assert list(doc) == list(TOP_LEVEL_KEYS), f"顶层键顺序不对：{list(doc)}"
            assert [clip["start"] for clip in doc["clips"]] == [0.0, 3.5, 7.0], (
                f"start 累加不对：{[clip['start'] for clip in doc['clips']]}"
            )
            assert doc["vo_script"] == "第一镜旁白。第二镜旁白。第三镜旁白。"
            assert all(
                clip["caption"] == clip["narration"] == clip["vo"]
                for clip in doc["clips"]
            ), "caption/narration/vo 没有逐字一致"
            write_handoff(doc, handoff_path)
            diffs = verify(story_path, handoff_path)
            assert diffs == [], f"生成后校验失败：{diffs}"
            return "生成 + 校验通过"

        def case_tamper():
            actual = json.loads(handoff_path.read_text(encoding="utf-8"))
            actual["clips"][1]["caption"] = actual["clips"][1]["caption"] + "改"
            _write_json(handoff_path, actual)
            diffs = verify(story_path, handoff_path)
            assert diffs, "手改后仍然校验通过"
            assert any(line.startswith("第 2 镜：") for line in diffs), (
                f"差异没有指出第 2 镜：{diffs}"
            )
            return "手改后失败并指出第 2 镜"

        def case_zoom_out():
            bad = json.loads(json.dumps(story))
            bad["scenes"][1]["motion"] = {"type": "zoom-out", "amount": 0.04}
            bad_path = tmp_dir / "bad_storyboard.json"
            _write_json(bad_path, bad)
            raw, loaded = load_storyboard(bad_path)
            try:
                build_handoff(
                    loaded, raw, bad_path, generated_at="2026-01-01T00:00:00Z"
                )
            except HandoffError as exc:
                assert exc.code == 2, f"zoom-out 退出码应为 2，实际 {exc.code}"
                assert "第 2 镜" in str(exc), f"报错没有指明第 2 镜：{exc}"
                assert "zoom-out" in str(exc), f"报错没有提到 zoom-out：{exc}"
                return "zoom-out 被拦截并指明第 2 镜"
            raise AssertionError("zoom-out 没有被拦截")

        check("合法分镜 → 生成 → 校验", case_generate_verify)
        check("手改 handoff 一个字 → 校验失败", case_tamper)
        check("motion=zoom-out → 生成报错", case_zoom_out)

    failed = 0
    for index, (name, passed, detail) in enumerate(checks, start=1):
        print(f"[{index}/{len(checks)}] {'PASS' if passed else 'FAIL'} {name}：{detail}")
        if not passed:
            failed += 1
    if failed:
        print(f"自测失败：{failed} 项未通过")
        return 1
    print("自测全部通过")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="build_handoff.py",
        description="从 06_storyboard.json 确定性生成 / 校验 08_eac_handoff.json",
    )
    parser.add_argument("storyboard", nargs="?", help="分镜文件路径（06_storyboard.json）")
    parser.add_argument(
        "-o",
        "--output",
        help=f"handoff 文件路径（默认与分镜同目录的 {HANDOFF_FILENAME}）",
    )
    parser.add_argument(
        "--verify", action="store_true", help="只校验现有 handoff 与分镜是否一致"
    )
    parser.add_argument("--selftest", action="store_true", help="运行内置夹具自测")
    args = parser.parse_args(argv)

    if args.selftest:
        if args.storyboard or args.output or args.verify:
            print(
                "错误：--selftest 不能与 storyboard、-o 或 --verify 同时使用",
                file=sys.stderr,
            )
            return 2
        return run_selftest()

    if not args.storyboard:
        print(
            "错误：缺少 storyboard 参数（用法：python build_handoff.py <storyboard.json>，"
            "或 python build_handoff.py --selftest）",
            file=sys.stderr,
        )
        return 2

    story_path = Path(args.storyboard).expanduser()
    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else story_path.resolve().parent / HANDOFF_FILENAME
    )

    try:
        if args.verify:
            diffs = verify(story_path, output_path)
            if diffs:
                print(f"校验失败：{output_path} 与分镜不一致")
                for line in diffs:
                    print(f"  {line}")
                return 1
            print(f"校验通过：{output_path} 与分镜一致")
            return 0

        raw, story = load_storyboard(story_path)
        doc = build_handoff(story, raw, story_path)
        write_handoff(doc, output_path)
        print(f"已生成：{output_path}（{len(doc['clips'])} 镜，{doc['duration_s']} 秒）")
        return 0
    except HandoffError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return exc.code
    except OSError as exc:
        print(f"错误：文件读写失败（{exc}）", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
