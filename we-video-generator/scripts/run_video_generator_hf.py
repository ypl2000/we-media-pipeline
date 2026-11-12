#!/usr/bin/env python3
"""
HyperFrames 版视频生成器 —— 与 run_video_generator.py 同签名，可互换。

    from run_video_generator_hf import generate_video
    generate_video(content_json, images_dir, output_file)

用 we-video-generator/hyperframes/ 里的 HTML composition 渲染，
不再逐帧画 PIL。需要 Node（npx）和 ffmpeg。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent / "hyperframes"
HYPERFRAMES_CLI = "hyperframes@0.9.19"

FFMPEG_CANDIDATES = [
    r"D:\ffmpeg\bin",
    r"C:\ffmpeg\bin",
    r"C:\ffmpeg\ffmpeg-8.1.1-essentials_build\bin",
]


def _find_ffmpeg_dir():
    for d in FFMPEG_CANDIDATES:
        if os.path.exists(os.path.join(d, "ffmpeg.exe")):
            return d
    exe = shutil.which("ffmpeg")
    return str(Path(exe).parent) if exe else None


def _stage_images(content, images_dir):
    """把 content.json 里的 3 张图复制成 scene1/2/3，返回变量用的相对路径。"""
    images = list(content.get("images") or [])
    if not images:
        # 没写 images 就按数字序取 images_dir 前 3 张
        files = sorted(
            f for f in os.listdir(images_dir)
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
        )
        images = [os.path.join(images_dir, f) for f in files[:3]]
    if not images:
        raise RuntimeError(f"没有可用图片: {images_dir}")
    while len(images) < 3:
        images.append(images[-1])

    staged = []
    for i, src in enumerate(images[:3], 1):
        if not os.path.exists(src):
            raise RuntimeError(f"图片不存在: {src}")
        ext = os.path.splitext(src)[1].lower() or ".png"
        dst_rel = f"assets/media/scene{i}{ext}"
        staged.append((src, dst_rel))
    return staged


def generate_video(content_json, images_dir, output_file):
    if not os.path.exists(content_json):
        return {"success": False, "error": f"content.json not found: {content_json}"}
    if not os.path.isdir(images_dir):
        return {"success": False, "error": f"images_dir not found: {images_dir}"}

    ffmpeg_dir = _find_ffmpeg_dir()
    if not ffmpeg_dir:
        return {"success": False, "error": "ffmpeg not found"}

    with open(content_json, "r", encoding="utf-8") as f:
        content = json.load(f)

    texts = list(content.get("text_sections") or [])
    while len(texts) < 3:
        texts.append("")
    if not content.get("main_title"):
        return {"success": False, "error": "content.json 缺少 main_title"}

    workdir = Path(tempfile.mkdtemp(prefix="hf_video_"))
    try:
        # 复制工程到临时目录，避免并发运行互相踩 assets/media
        proj = workdir / "project"
        shutil.copytree(
            PROJECT_DIR,
            proj,
            ignore=shutil.ignore_patterns(".hyperframes", "renders", "node_modules", "_vars.json"),
        )
        staged = _stage_images(content, images_dir)
        for src, dst_rel in staged:
            shutil.copy2(src, proj / dst_rel)

        variables = {
            "main_title": content.get("main_title", ""),
            "sub_title": content.get("sub_title", ""),
            "text_1": texts[0],
            "text_2": texts[1],
            "text_3": texts[2],
            "img_1": staged[0][1],
            "img_2": staged[1][1],
            "img_3": staged[2][1],
        }
        vars_file = workdir / "vars.json"
        vars_file.write_text(json.dumps(variables, ensure_ascii=False), encoding="utf-8")

        env = dict(os.environ)
        env["PATH"] = ffmpeg_dir + os.pathsep + env.get("PATH", "")

        npx = shutil.which("npx") or shutil.which("npx.cmd") or "npx"
        cmd = [
            npx, "--yes", HYPERFRAMES_CLI, "render", str(proj),
            "--variables-file", str(vars_file),
            "-o", str(Path(output_file).resolve()),
            "--crf", "0",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env=env, cwd=str(proj))
        if proc.returncode != 0 or not os.path.exists(output_file):
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-15:]
            return {"success": False, "error": "hyperframes render failed:\n" + "\n".join(tail)}
        return {"success": True, "file": str(Path(output_file).resolve())}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("usage: run_video_generator_hf.py <content.json> <images_dir> <output.mp4>")
        sys.exit(2)
    print(json.dumps(generate_video(sys.argv[1], sys.argv[2], sys.argv[3]), ensure_ascii=False))
