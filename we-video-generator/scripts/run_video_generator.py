#!/usr/bin/env python3


"""


Run wechat video generator with custom content.json and output path.


Used by wechat-article-pipeline to generate videos.


跨平台版本：自动检测 Windows / WSL / Linux 环境。


"""





import sys, os, json, shutil, tempfile, subprocess, re


from pathlib import Path





def detect_environment():


    if sys.platform == 'win32':


        return 'windows'


    try:


        with open('/proc/version') as f:


            if 'WSL' in f.read() or 'microsoft' in f.read().lower():


                return 'wsl'


    except:


        pass


    if os.path.exists('/mnt/c'):


        return 'wsl'


    return 'linux'





ENV = detect_environment()

# 跨平台路径配置 - 优先使用脚本位置，反馈到 hardcoded 路径
SCRIPT_DIR = Path(__file__).parent.resolve()
SKILL_DIR_BASE = SCRIPT_DIR.parent

SKILL_DIR = SKILL_DIR_BASE  # 脚本就在仓库 skill 目录里，必然存在
PYTHON = 'python' if ENV == 'windows' else 'python3'

GENERATOR = SKILL_DIR / 'scripts' / 'wechat_video_generator.py'





def generate_video(content_json, images_dir, output_file):


    if not os.path.exists(content_json):


        return {'success': False, 'error': f'content.json not found: {content_json}'}


    if not os.path.exists(images_dir):
        # 尝试查找 images-all 目录作为后备
        images_all_dir = os.path.join(os.path.dirname(images_dir), 'images-all')
        if os.path.exists(images_all_dir):
            print(f"  [Fallback] images_good not found, using images-all instead")
            images_dir = images_all_dir
        else:
            return {'success': False, 'error': f'images_dir not found: {images_dir}'}





    try:


        with open(content_json, 'r', encoding='utf-8') as f:


            content = json.load(f)


    except Exception as e:


        return {'success': False, 'error': f'Failed to load content.json: {e}'}





    # 获取图片路径
    image_paths = content.get('images', [])

    # WSL 下把 Windows 路径转成 WSL 路径
    if ENV == 'wsl':
        def wsl_path(p):
            p = str(p)
            if re.match(r'^[A-Z]:', p):
                return '/mnt/' + p[0].lower() + p[2:].replace('\\', '/')
            return p
        image_paths = [wsl_path(p) for p in image_paths]

    if len(image_paths) < 3 and os.path.exists(images_dir):
        print(f"  Auto-filling images from: {images_dir}")

        # 视频画面优先用真实新闻图；数据图和整页幻灯片进视频没法看
        cands = []
        for f in sorted(os.listdir(images_dir)):
            if not f.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                continue
            if f.startswith('diagram_'):
                continue
            cands.append((0 if f.lower().startswith('news_') else 1, f))

        for _, f in sorted(cands):
            abs_path = os.path.abspath(os.path.join(images_dir, f))

            image_paths.append(abs_path)

            if len(image_paths) >= 3:
                break





    if len(image_paths) < 3:


        return {'success': False, 'error': f'Need at least 3 images (found {len(image_paths)})'}





    # 复制图片到临时目录


    temp_dir = tempfile.mkdtemp()


    temp_images_dir = os.path.join(temp_dir, 'images')


    os.makedirs(temp_images_dir)





    copied_images = []


    for i, img_path in enumerate(image_paths[:3]):


        src = img_path if os.path.isabs(img_path) else os.path.join(images_dir, img_path)


        if os.path.exists(src):


            dst = os.path.join(temp_images_dir, f'img{i+1:02d}.jpg')


            # Retry copy on file lock (WinError 32) - Windows Defender may hold handles briefly
            for attempt in range(5):
                try:
                    shutil.copy2(src, dst)
                    break
                except OSError as e:
                    if e.winerror == 32 and attempt < 4:
                        import time
                        time.sleep(0.3 * (attempt + 1))
                        continue
                    raise


            copied_images.append(dst)


        else:


            shutil.rmtree(temp_dir, ignore_errors=True)


            return {'success': False, 'error': f'Image not found: {src}'}





    content['images'] = copied_images





    # 写入临时 content.json 到 temp_dir（避免与其他进程冲突）


    temp_content_json = os.path.join(temp_dir, 'content.json')


    try:


        with open(temp_content_json, 'w', encoding='utf-8') as f:


            json.dump(content, f, indent=2, ensure_ascii=False)


    except Exception as e:


        shutil.rmtree(temp_dir, ignore_errors=True)


        return {'success': False, 'error': f'Failed to write temp content.json: {e}'}





    # 创建输出目录
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    # 延迟确保文件系统同步（Windows文件句柄释放可能有时延）
    import time
    time.sleep(0.5)

    try:
        result = subprocess.run(
            [PYTHON, str(GENERATOR), str(temp_content_json), output_file],
            capture_output=True,
            text=True,
            cwd=str(SKILL_DIR),
            timeout=300  # 5分钟超时
        )
        if result.returncode != 0:
            error_detail = result.stderr[:1000] if result.stderr else "No error message"
            print(f"  Video generator failed with code {result.returncode}: {error_detail}")
            return {'success': False, 'error': f'Script failed with code {result.returncode}: {error_detail}'}

        # 首先尝试从 stdout 中提取视频路径
        video_path_from_output = None
        if result.stdout:
            # 匹配 "Video saved: xxx" 格式
            match = re.search(r'Video saved:\s*(.+)', result.stdout)
            if match:
                video_path_from_output = match.group(1).strip()
                if os.path.exists(video_path_from_output):
                    # 如果源和目标相同（generator直接写入目标路径），跳过复制
                    if os.path.abspath(video_path_from_output) == os.path.abspath(output_file):
                        return {'success': True, 'file': output_file}
                    # 复制到目标位置（可能因Windows Defender扫描而WinError 32）
                    for attempt in range(5):
                        try:
                            shutil.copy2(video_path_from_output, output_file)
                            break
                        except OSError as e:
                            if e.winerror == 32 and attempt < 4:
                                import time; time.sleep(0.5 * (attempt + 1))
                                continue
                            raise
                    return {'success': True, 'file': output_file}

        # 检查输出文件
        if os.path.exists(output_file):
            return {'success': True, 'file': output_file}
        else:
            # 输出文件不在预期位置，搜索一下
            search_dirs = [
                SKILL_DIR,                   # 技能目录
                SKILL_DIR_BASE,               # 技能基目录
                SCRIPT_DIR,                  # 脚本目录
                Path.home() / 'Desktop',
            ]
            for d in search_dirs:
                if not d.exists():
                    continue
                for root, dirs, files in os.walk(str(d)):
                    for f in files:
                        if f.endswith('.mp4') and content.get('main_title', '')[:10] in f:
                            found = os.path.join(root, f)
                            for attempt in range(5):
                                try:
                                    shutil.move(found, output_file)
                                    break
                                except OSError as e:
                                    if e.winerror == 32 and attempt < 4:
                                        import time; time.sleep(0.5 * (attempt + 1))
                                        continue
                                    raise
                            return {'success': True, 'file': output_file}
            
            # 最后尝试检查输出目录本身
            output_parent = os.path.dirname(output_file)
            if os.path.exists(output_parent):
                for f in os.listdir(output_parent):
                    if f.endswith('.mp4'):
                        found = os.path.join(output_parent, f)
                        return {'success': True, 'file': found}
            
            return {'success': False, 'error': f'Video not found after generation. stdout: {result.stdout}'}





    except Exception as e:


        return {'success': False, 'error': f'Failed to run generator: {e}'}


    finally:


        try:


            if temp_content_json.exists():


                os.remove(temp_content_json)


            shutil.rmtree(temp_dir, ignore_errors=True)


        except:


            pass








if __name__ == '__main__':


    if len(sys.argv) < 4:


        print("Usage: run_video_generator.py <content_json> <images_dir> <output_file>")


        sys.exit(1)





    content_json = sys.argv[1]


    images_dir = sys.argv[2]


    output_file = sys.argv[3]





    print(f"[{ENV}] Generating video...")


    result = generate_video(content_json, images_dir, output_file)





    if result.get('success'):


        print(f"✓ Video created: {result['file']}")


        sys.exit(0)


    else:


        print(f"✗ Error: {result.get('error')}")


        sys.exit(1)


