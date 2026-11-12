"""
HTML PPT 生成和截图模块

从文章文件生成 HTML PPT，并使用 Playwright 截图。
支持 LLM 预处理 + 智能布局匹配。
"""

import json
import os
import re
import shutil
import argparse
import sys
import time
from pathlib import Path
from typing import List, Optional

try:
    import httpx
except ImportError:
    httpx = None

# 添加 shared 目录到 path 以获取配置
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "shared"))
from config_loader import get_minimax_api_key, get_config_value

# 品牌名统一从 config.json 的 brand 段读取，脚本里不写死
sys.path.insert(0, str(Path(__file__).parent))
from brand import load_brand

BRAND_NAME = load_brand().get("name", "")


SKILL_DIR = Path(__file__).parent.parent.parent / "html-ppt-skill"
ASSETS_LOCAL_DIR = "html-ppt-assets"  # 本地 assets 目录名
TEMPLATES_DIR = SKILL_DIR / "templates" / "single-page"


def copy_assets_to_output(output_dir: Path) -> bool:
    """将 html-ppt-skill 的 assets 复制到输出目录"""
    assets_src = SKILL_DIR / "assets"
    assets_dst = output_dir / ASSETS_LOCAL_DIR / "assets"
    
    # 如果已存在则跳过
    if assets_dst.exists():
        return True
    
    try:
        # 复制整个 assets 目录
        shutil.copytree(assets_src, assets_dst)
        return True
    except Exception as e:
        print(f"复制 assets 失败: {e}")
        return False


# ========== 通用辅助函数 ==========

def get_field(data: dict, *field_names, default=""):
    """从字典中获取字段值，支持多种字段名变体
    
    Args:
        data: 数据字典
        *field_names: 可能的字段名（按优先级排序）
        default: 默认值
    
    Returns:
        字段值或默认值
    """
    for field in field_names:
        if field in data and data[field]:
            return data[field]
    return default


def get_name_field(item: dict) -> str:
    """从 item 中获取名称字段（支持 name/product 等变体）"""
    return get_field(item, "name", "product", default="")


def get_value_field(item: dict) -> str:
    """从 item 中获取值字段（支持 value/context/highlight 等变体）"""
    return get_field(item, "value", "context", "highlight", default="")


# ========== LLM 预处理相关 ==========

MINIMAX_API_URL = "https://api.minimaxi.com/anthropic"
MINIMAX_MODEL = "MiniMax-M2.7"
# 备用：MiniMax 配额用完时走智谱的 Anthropic 兼容端点
ZAI_API_URL = "https://open.bigmodel.cn/api/anthropic"
ZAI_MODEL = os.environ.get("ZAI_TEXT_MODEL", "glm-4.6")

SYSTEM_PROMPT = """你是一个专业的 PPT 结构设计师。请分析以下文章，生成结构清晰的幻灯片大纲。

**严格约束：**
1. 生成 6-7 个 slides（封面 + 5-6 个内容页），不要目录页，不要感谢页
2. **优先使用 stat、comparison、timeline、process-steps 等丰富布局，bullets 最多 2 页**
3. **内容长度限制（必须遵守）：**
   - bullets 布局：每页最多 4 个要点，每点最多 25 个字符
   - comparison 布局：每边最多 4 个要点，每点最多 30 个字符
   - stat 布局：number 最多 10 个字符，description 最多 40 个字符
   - timeline 布局：每项的 title 最多 20 个字符，description 最多 30 个字符
   - process-steps 布局：每步最多 20 个字符
4. **每个字符串内容必须简短，避免长句子**
5. **绝对不要**在字符串内容中包含 } 或 { 字符
6. 不要使用 Markdown 链接格式 [text](url)
7. 数字要用 stat 布局，不要埋在文字里
8. **禁止空洞内容**：不要生成"功能强大"、"体验优秀"、"非常方便"等泛泛而谈的废话
9. **必须具体**：每个要点都要有具体的数据、案例、方法或细节

**重要：你的输出会被完整读取。如果 JSON 过长，部分内容可能被截断。请生成简洁的内容，确保 JSON 格式正确且完整。**

**反面示例（不要这样写）：**
❌ "微信非常方便" → ✅ "微信支持消息撤回2分钟内"
❌ "公众号内容丰富" → ✅ "公众号超过2亿个，覆盖新闻、娱乐、科技等领域"
❌ "小程序使用便捷" → ✅ "小程序无需下载，扫码即用，已有超过400万个小程序"
❌ "用户体验好" → ✅ "微信日均打开次数超过10次，用户粘性极高"

**布局类型和必需字段（严格按此格式）：**

1. **cover**: `{"title":"标题","subtitle":"副标题"}`
2. **bullets**: `{"section_title":"标题","bullets":["要点1","要点2","要点3","要点4"]}`
3. **stat**: `{"number":"13亿","description":"月活跃用户数，每5人有1人使用"}`
4. **big-quote**: `{"quote":"金句内容"}`
5. **comparison**: `{"left_title":"劣势方","right_title":"优势方","left_items":["劣势1","劣势2","劣势3"],"right_items":["优势1","优势2","优势3"]}`
6. **process-steps**: `{"section_title":"标题","steps":["步骤1","步骤2","步骤3","步骤4"]}`
7. **timeline**: `{"section_title":"标题","items":[{"year":"2024","title":"事件","description":"描述"}]}`

**输出示例（严格遵循此格式）：**
```json
{"title":"文章标题","theme":"minimal-white","slides":[{"type":"cover","title":"标题","subtitle":"副标题"},{"type":"stat","number":"99%","description":"描述文字40字以内"},{"type":"comparison","left_title":"竞品","right_title":"我们","left_items":["劣势1","劣势2","劣势3"],"right_items":["优势1","优势2","优势3"]}]}
```

**重要：comparison 的 left_title 是劣势方，right_title 是优势方！**

请直接输出纯 JSON，不要用 ```json 包裹。"""


def fix_json_output(raw_text: str) -> str:
    """修复 LLM 输出的常见 JSON 问题"""
    text = raw_text.strip()
    
    # 去掉 markdown 代码块包裹（如 ```json ... ```）
    if text.startswith('```'):
        lines = text.split('\n')
        start_idx = 0
        for i, line in enumerate(lines):
            if i > 0 and not line.startswith('```'):
                start_idx = i
                break
        if lines and lines[-1].strip() == '```':
            lines = lines[:-1]
        text = '\n'.join(lines[start_idx:])
    
    # 中文弯引号转单引号（避免转 ASCII 双引号导致 JSON 字符串未转义）
    text = text.replace('\u201c', "'").replace('\u201d', "'")
    text = text.replace('\u300c', "'").replace('\u300d', "'")
    text = text.replace('\u2018', "'").replace('\u2019', "'")
    
    # 查找 JSON 开始位置
    json_start = text.find('{')
    if json_start == -1:
        return text
    
    json_text = text[json_start:]
    
    # 如果已经以 } 结尾，可能是完整的 JSON
    if json_text.rstrip().endswith('}'):
        return json_text
    
    # 通过括号匹配找到结束位置
    depth = 0
    end_pos = 0
    in_string = False
    escape = False
    
    for i, char in enumerate(json_text):
        if escape:
            escape = False
            continue
        if char == '\\':
            escape = True
            continue
        if char == '"' and not escape:
            in_string = not in_string
        if not in_string:
            if char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0:
                    end_pos = i + 1
                    break
    
    if end_pos > 0:
        json_text = json_text[:end_pos]
    
    # 检查截断：JSON 不完整，尝试恢复
    if json_text:
        stripped = json_text.rstrip()
        if stripped:
            last_char = stripped[-1]
            # 判断是否被截断：以字母/数字/中文结尾（字符串中间），或以逗号/冒号结尾（结构中间）
            is_truncated = (
                last_char.isalnum()
                or '\u4e00' <= last_char <= '\u9fff'
            )
            
            if is_truncated:
                # 策略：逐 slide 用括号计数验证完整性，取最后一个完整 slide
                slide_type_patterns = [
                    '{"type":"cover"',
                    '{"type":"toc"',
                    '{"type":"bullets"',
                    '{"type":"stat"',
                    '{"type":"big-quote"',
                    '{"type":"comparison"',
                    '{"type":"timeline"',
                    '{"type":"process-steps"',
                ]
                
                # 收集所有 slide 起始位置
                slide_starts = []
                for pattern in slide_type_patterns:
                    pos = 0
                    while True:
                        pos = json_text.find(pattern, pos)
                        if pos == -1:
                            break
                        slide_starts.append(pos)
                        pos += 1
                
                slide_starts.sort()
                
                # 对每个 slide 起始位置，用括号计数找到其结束位置
                last_complete_end = 0
                for start_pos in slide_starts:
                    depth = 0
                    in_str = False
                    esc = False
                    slide_end = -1
                    for i in range(start_pos, len(json_text)):
                        c = json_text[i]
                        if esc:
                            esc = False
                            continue
                        if c == '\\':
                            esc = True
                            continue
                        if c == '"':
                            in_str = not in_str
                        if not in_str:
                            if c == '{':
                                depth += 1
                            elif c == '}':
                                depth -= 1
                                if depth == 0:
                                    slide_end = i + 1
                                    break
                    if slide_end > 0:
                        last_complete_end = slide_end
                
                if last_complete_end > 0:
                    # 截取到最后一个完整 slide，补全数组和外层对象
                    json_text = json_text[:last_complete_end] + ']}'
                    return json_text
                
                # 尝试更宽松的修复：找到最后一个 "}] 或 "} 结尾的位置
                # 这表示一个 slide 对象的结束
                last_brace_pos = json_text.rfind('"}')
                if last_brace_pos > 0:
                    # 检查这是否是一个完整的 slide 结束
                    potential_end = last_brace_pos + 2
                    # 验证这个位置是否合理（不在字符串中间）
                    prefix = json_text[:last_brace_pos]
                    # 确保前面有完整的 slides 数组
                    if '"slides":[' in prefix or len(prefix) > 50:
                        json_text = json_text[:potential_end] + ']}'
                        return json_text

                # 如果还是无法修复，尝试返回原始文本让后面的 json.loads 尝试解析
                return json_text
    
    return json_text


def generate_ppt_outline(article_file: str, api_key: str = None) -> dict:
    """调用 LLM 将文章转换为结构化 PPT 大纲

    Args:
        article_file: 文章文件路径
        api_key: MiniMax API 密钥（可选，会自动从配置获取）

    Returns:
        outline JSON dict
    """
    # 如果没有传入 api_key，从配置获取
    if not api_key:
        api_key = get_minimax_api_key()
    
    if not api_key:
        raise ValueError("MiniMax API key 未配置，请在 config.json 中配置 minimax_api_key")
    
    # 读取文章内容
    with open(article_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 截取文章前 8000 字符（避免超出 token 限制）
    article_preview = content[:8000]
    
    user_prompt = f"请分析以下文章，生成 PPT 大纲：\n\n{article_preview}"

    # 注意：幻灯片里不插正文配图。正文配图（[[IMG: ...]]）只出现在正文，
    # 重复塞进整页版式里会被压成小图，同一张图在文章里出现两次。

    # 使用 anthropic SDK
    try:
        import anthropic
    except ImportError:
        print("安装 anthropic...")
        import subprocess
        subprocess.run(["pip", "install", "anthropic", "-q"], check=True)
        import anthropic
    
    # 大纲生成 provider 链：主力 MiniMax，配额用完（429）自动换智谱
    providers = [(MINIMAX_API_URL, MINIMAX_MODEL, api_key)]
    zai_key = get_config_value('zai_api_key')
    if zai_key:
        providers.append((ZAI_API_URL, ZAI_MODEL, zai_key))

    message = None
    last_err = None
    for base_url, model, key in providers:
        if not key:
            continue
        client = anthropic.Anthropic(base_url=base_url, api_key=key)
        try:
            # 使用流式模式避免长操作超时
            with client.messages.stream(
                model=model,
                max_tokens=32000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": [{"type": "text", "text": user_prompt}]}],
            ) as stream:
                message = stream.get_final_message()
            break
        except Exception as e:
            last_err = e
            print(f"  [!] 大纲 provider {model} 失败，换下一个: {str(e)[:150]}")
    if message is None:
        raise ValueError(f"所有大纲 provider 都失败: {last_err}")
    
    # 提取文本内容
    raw_text = ""
    for block in message.content:
        if hasattr(block, 'text') and block.text:
            raw_text += block.text
    
    # 修复 JSON 问题
    fixed_json = fix_json_output(raw_text)
    
    # 如果 fix_json_output 返回空字符串，说明 JSON 被截断在字符串中间
    if not fixed_json:
        raise ValueError(f"JSON 在字符串中间被截断，原始输出: {raw_text[:500]}")
    
    try:
        outline = json.loads(fixed_json)
    except json.JSONDecodeError as e:
        # JSON 解析失败，尝试使用已有的部分 JSON
        print(f"  [!] JSON 解析不完整，尝试修复: {e}")
        
        # 尝试找到最后一个完整的 slide 并截断
        try:
            # 策略1: 找到最后一个完整的 slide 对象
            last_complete = raw_text.rfind('"}')
            if last_complete > 0:
                truncated = raw_text[:last_complete + 2] + ']}'
                outline = json.loads(truncated)
                if outline.get('slides') and len(outline['slides']) >= 1:
                    print(f"  [OK] 使用修复后的 JSON ({len(outline.get('slides', []))} slides)")
                    # 验证并补充 cover slide
                    slides = outline.get('slides', [])
                    if not any(s.get('type') == 'cover' for s in slides):
                        # 尝试从 outline 的 title 生成 cover
                        if outline.get('title'):
                            slides.insert(0, {'type': 'cover', 'title': outline.get('title'), 'subtitle': outline.get('subtitle', '')})
                            outline['slides'] = slides
                    return outline
        except:
            pass
        
        # 策略2: 尝试从 raw_text 中提取 JSON 并使用 ast.literal_eval 或正则
        import re
        json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        if json_match:
            try:
                partial_json = json_match.group(0)
                outline = json.loads(partial_json)
                if outline.get('slides') and len(outline['slides']) >= 1:
                    print(f"  [OK] 使用部分 JSON ({len(outline.get('slides', []))} slides)")
                    return outline
            except:
                pass
        
        # 如果 slides 太少或解析失败，使用 fallback
        if len(outline.get('slides', [])) < 3:
            raise ValueError(f"JSON 解析失败且 slides 不足: {e}\n原始输出: {raw_text[:500]}")
        
        raise ValueError(f"JSON 解析失败: {e}\n原始输出: {raw_text[:500]}")
    
    return outline


# ========== 布局选择相关 ==========

def select_layout(slide_data: dict) -> str:
    """根据 slide type 返回对应模板文件名
    
    Args:
        slide_data: slide 数据字典，包含 type 字段
    
    Returns:
        模板文件名
    """
    type_to_layout = {
        "cover": "cover.html",
        "toc": "toc.html",
        "bullets": "bullets.html",
        "quote": "big-quote.html",
        "big-quote": "big-quote.html",
        "stat": "stat-highlight.html",
        "kpi-grid": "kpi-grid.html",
        "comparison": "comparison.html",
        "pros-cons": "pros-cons.html",
        "timeline": "timeline.html",
        "steps": "process-steps.html",
        "process-steps": "process-steps.html",
        "two-column": "two-column.html",
        "three-column": "three-column.html",
        "section-divider": "section-divider.html",
        "thanks": "thanks.html",
    }
    return type_to_layout.get(slide_data.get("type", "bullets"), "bullets.html")


def render_toc_items(sections: List[str]) -> str:
    """生成目录项 HTML"""
    items = []
    for i, section in enumerate(sections):
        num = f"{i+1:02d}"
        items.append(f'<div class="card"><div class="row"><div class="h3 dim2" style="width:56px">{num}</div><div><h4>{section}</h4></div></div></div>')
    return "".join(items)


def render_bullets(bullets: List[str]) -> str:
    """生成 bullets 列表 HTML"""
    items = []
    for b in bullets:
        items.append(f'<li class="card card-accent"><h4>{b}</h4></li>')
    return "\n".join(items)


def generate_slide_html(slide_data: dict, slide_idx: int, total_slides: int, template_dir: Path) -> str:
    """根据 slide 数据生成单个 slide 的 HTML

    Args:
        slide_data: slide 数据字典
        slide_idx: 当前 slide 索引（1-based）
        total_slides: 总 slide 数
        template_dir: 模板目录路径

    Returns:
        slide HTML 片段
    """
    slide_type = slide_data.get("type", "bullets")
    template_file = template_dir / select_layout(slide_data)
    
    if not template_file.exists():
        # fallback 到 bullets 模板
        template_file = template_dir / "bullets.html"
    
    with open(template_file, 'r', encoding='utf-8') as f:
        template = f.read()
    
    # 提取 body 内的 section
    section_match = re.search(r'<section[^>]*>.*?</section>', template, re.DOTALL)
    if section_match:
        section_html = section_match.group(0)
    else:
        return ""
    
    # 替换占位符
    if slide_type == "cover":
        section_html = re.sub(r'\{\{title\}\}', slide_data.get("title", ""), section_html)
        section_html = re.sub(r'\{\{subtitle\}\}', slide_data.get("subtitle", ""), section_html)
        # 替换原有的静态内容
        section_html = re.sub(r'<h1[^>]*>.*?</h1>', f'<h1 class="h1 anim-fade-up" data-anim="fade-up">{slide_data.get("title", "")}</h1>', section_html, flags=re.DOTALL)
        section_html = re.sub(r'<p class="lede">.*?</p>', f'<p class="lede">{slide_data.get("subtitle", "")}</p>', section_html, flags=re.DOTALL)
    
    elif slide_type == "toc":
        sections = slide_data.get("sections", [])
        sections_html = ""
        for i, section in enumerate(sections):
            num = f"{i+1:02d}"
            sections_html += f'<div class="card"><div class="row"><div class="h3 dim2" style="width:56px">{num}</div><div><h4>{section}</h4></div></div></div>'
        # 替换 grid 容器内的内容
        # 匹配从 grid 开始到 deck-footer 之前的所有内容
        grid_pattern = r'<div class="grid g2 mt-l anim-stagger-list"[^>]*>(?:(?!<div class="deck-footer").)*</div>\s*(?=<div class="deck-footer")'
        replacement = f'<div class="grid g2 mt-l anim-stagger-list" data-anim-target>{sections_html}</div>'
        section_html = re.sub(grid_pattern, replacement, section_html, flags=re.DOTALL)
        # 移除模板自带的 lede 内容（如果有）
        section_html = re.sub(r'<p class="lede"[^>]*>.*?</p>', '', section_html, flags=re.DOTALL)
    
    elif slide_type in ("bullets", "steps"):
        section_title = slide_data.get("section_title", slide_data.get("title", ""))
        bullets_html = render_bullets(slide_data.get("bullets", []))
        
        # 替换标题
        h2_match = re.search(r'<h2[^>]*>.*?</h2>', section_html, re.DOTALL)
        if h2_match:
            section_html = section_html.replace(h2_match.group(0), f'<h2 class="h2">{section_title}</h2>')
        
        # 移除模板自带的 lede 内容
        section_html = re.sub(r'<p class="lede[^"]*">[^<]*</p>', '', section_html)
        
        # 替换 bullets
        ul_pattern = r'<ul[^>]*>.*?</ul>'
        ul_replacement = f'<ul class="grid g1 anim-stagger-list" style="list-style:none;padding:0;margin:0;gap:14px" data-anim-target>\n{bullets_html}\n</ul>'
        section_html = re.sub(ul_pattern, ul_replacement, section_html, flags=re.DOTALL)
    
    elif slide_type == "process-steps":
        section_title = slide_data.get("section_title", slide_data.get("title", ""))
        
        # 替换标题
        h2_match = re.search(r'<h2[^>]*>.*?</h2>', section_html, re.DOTALL)
        if h2_match:
            section_html = section_html.replace(h2_match.group(0), f'<h2 class="h2">{section_title}</h2>')
        
        # 移除模板自带的 lede 内容
        section_html = re.sub(r'<p class="lede[^"]*">[^<]*</p>', '', section_html)
        
        # 处理 steps
        steps = slide_data.get("steps", [])
        steps_html = ""
        for i, step in enumerate(steps):
            if isinstance(step, dict):
                title = step.get("label", step.get("title", step.get("name", "")))
                desc = step.get("desc", step.get("description", ""))
                tag = step.get("tag", "")
            else:
                title = step
                desc = ""
                tag = ""
            tag_html = f'<span class="tag">{tag}</span>' if tag else ""
            steps_html += f'<div class="step"><div class="num">{i+1}</div><h4>{title}</h4><p>{desc}</p>{tag_html}</div>'
        # 替换整个 steps 容器
        steps_pattern = r'<div class="steps[^"]*"[^>]*>.*?</div>\s*(?=<div class="deck-footer"|</section>)'
        replacement = f'<div class="steps anim-stagger-list" data-anim-target>{steps_html}</div>'
        section_html = re.sub(steps_pattern, replacement, section_html, flags=re.DOTALL)
    
    elif slide_type in ("big-quote", "quote"):
        quote = slide_data.get("quote", slide_data.get("content", ""))
        author = slide_data.get("author", "")
        blockquote_pattern = r'<blockquote[^>]*>.*?</blockquote>'
        replacement = f'<blockquote class="serif anim-fade-up" data-anim="fade-up" style="font-size:56px;line-height:1.25;margin:-40px 0 24px;font-style:italic;font-weight:600">{quote}</blockquote>'
        section_html = re.sub(blockquote_pattern, replacement, section_html, flags=re.DOTALL)
        # 替换或移除 author
        author_pattern = r'<p class="dim"[^>]*>—.*?</p>'
        if author:
            replacement = f'<p class="dim" style="font-size:20px;letter-spacing:.08em">— {author}</p>'
            section_html = re.sub(author_pattern, replacement, section_html, flags=re.DOTALL)
        else:
            # 如果没有 author，移除占位符
            section_html = re.sub(author_pattern, '', section_html, flags=re.DOTALL)
    
    elif slide_type == "stat":
        number = slide_data.get("number", "0")
        description = slide_data.get("description", "")
        # 处理带单位的数字（如 "$34亿"、"13亿"、"99%"）
        import re as re_module
        num_match = re_module.search(r'^(\D*)(\d+)(\D*)$', str(number))
        if num_match:
            prefix = num_match.group(1)  # 前缀（如 "$"）
            digits = num_match.group(2)   # 数字部分（如 "34"）
            suffix = num_match.group(3)   # 后缀（如 "亿"）
            # 替换 counter 数字，保持前缀
            counter_pattern = r'<span class="counter[^"]*"[^>]*>.*?</span>'
            replacement = f'{prefix}<span class="counter gradient-text" data-to="{digits}">{digits}</span>'
            section_html = re.sub(counter_pattern, replacement, section_html, flags=re.DOTALL)
            # 移除模板自带的 % 后缀，替换为实际后缀
            unit_pattern = r'<span class="gradient-text">%</span>'
            if suffix:
                section_html = re.sub(unit_pattern, f'<span class="gradient-text">{suffix}</span>', section_html)
            else:
                section_html = re.sub(unit_pattern, '', section_html)
        else:
            # 无法解析，移除 counter 动画
            counter_pattern = r'<span class="counter[^"]*"[^>]*>.*?</span>'
            replacement = f'<span class="gradient-text">{number}</span>'
            section_html = re.sub(counter_pattern, replacement, section_html, flags=re.DOTALL)
            # 移除模板自带的 % 后缀
            section_html = re.sub(r'<span class="gradient-text">%</span>', '', section_html)
        # 替换描述
        h3_pattern = r'<h3[^>]*>.*?</h3>'
        section_html = re.sub(h3_pattern, f'<h3 class="mt-s">{description}</h3>', section_html, flags=re.DOTALL)
        # 替换模板自带的 lede 内容（如果有的话）
        lede_pattern = r'<p class="lede"[^>]*>.*?</p>'
        section_html = re.sub(lede_pattern, '', section_html, flags=re.DOTALL)
    
    elif slide_type == "thanks":
        cta = slide_data.get("cta", "感谢阅读")
        lede_pattern = r'<p class="lede"[^>]*>.*?</p>'
        replacement = f'<p class="lede" style="margin:18px auto 0">{cta}</p>'
        section_html = re.sub(lede_pattern, replacement, section_html, flags=re.DOTALL)
    
    elif slide_type == "comparison":
        # 对比布局 (模板是 "过去 vs 现在" 格式)
        title = slide_data.get("title", "对比分析")
        
        # 支持多种格式：
        # 1. left_title/left_items/right_title/right_items (字符串列表)
        # 2. left_title/left_bullets/right_title/right_bullets
        # 3. items: [{name, value, highlight}] - 产品对比格式
        
        items = slide_data.get("items", [])
        left_items = []
        right_items = []
        left_title = slide_data.get("left_title", "竞品")
        right_title = slide_data.get("right_title", "Kimi")
        features = []
        
        if items:
            # items 格式：第一个是 Kimi（高亮产品），其他是竞品
            # 优先使用 highlight 布尔值来判断
            kimi_item = None
            other_items = []
            for item in items:
                if item.get("highlight") == True:
                    kimi_item = item
                elif item.get("highlight") == False:
                    other_items.append(item)
            
            # 如果没有找到 highlight 字段，默认第一个是 Kimi，其余是竞品
            if kimi_item is None and items:
                kimi_item = items[0]
                other_items = items[1:]
            
            # 模板结构：bad-side(📉) 在左边（劣势），good-side(📈) 在右边（优势）
            # 所以竞品放左边（劣势），Kimi 放右边（优势）
            for item in other_items:
                name = get_name_field(item)
                value = get_value_field(item)
                left_items.append(f"{name}: {value}" if value else name)
            
            if kimi_item:
                name = get_name_field(kimi_item) or "Kimi"
                value = get_value_field(kimi_item)
                right_items.append(f"{name}: {value}" if value else name)
        else:
            # 非 items 格式
            # 模板结构：bad-side(📉) 在左边（劣势），good-side(📈) 在右边（优势）
            # LLM 的 left_title 是劣势方，right_title 是优势方
            # 所以保持原始分配，不需要交换
            left_items = slide_data.get("left_items", slide_data.get("left_bullets", []))
            right_items = slide_data.get("right_items", slide_data.get("right_bullets", []))
            left_title = slide_data.get("left_title", "左侧")
            right_title = slide_data.get("right_title", "右侧")
        
        # 替换标题
        section_html = re.sub(r'<h2[^>]*>.*?</h2>', f'<h2 class="h2">{title}</h2>', section_html, flags=re.DOTALL)
        
        # 替换左边标题和内容（bad-side = 劣势）
        section_html = re.sub(r'<h3>📉[^<]*</h3>', f'<h3>📉 {left_title}</h3>', section_html)
        left_html = "".join([f'<li>{b}</li>' for b in left_items]) if left_items else '<li>暂无数据</li>'
        section_html = re.sub(r'<ul>\s*</ul>', f'<ul>{left_html}</ul>', section_html)
        section_html = re.sub(r'<ul>\s*<li>每次都要重新做封面.*?</ul>', f'<ul>{left_html}</ul>', section_html, flags=re.DOTALL)
        
        # 替换右边标题和内容（good-side = 优势）
        section_html = re.sub(r'<h3>📈[^<]*</h3>', f'<h3>📈 {right_title}</h3>', section_html)
        if features:
            right_html = "".join([f'<li>{f}</li>' for f in features])
        else:
            right_html = "".join([f'<li>{b}</li>' for b in right_items]) if right_items else '<li>暂无数据</li>'
        section_html = re.sub(r'<ul>\s*</ul>', f'<ul>{right_html}</ul>', section_html)
        section_html = re.sub(r'<ul>\s*<li>复制模板.*?</ul>', f'<ul>{right_html}</ul>', section_html, flags=re.DOTALL)
    
    elif slide_type == "timeline":
        # 时间线布局
        section_title = slide_data.get("section_title", slide_data.get("title", ""))
        
        # 替换标题
        h2_match = re.search(r'<h2[^>]*>.*?</h2>', section_html, re.DOTALL)
        if h2_match:
            section_html = section_html.replace(h2_match.group(0), f'<h2 class="h2">{section_title}</h2>')
        
        items = slide_data.get("items", [])
        items_html = ""
        for i, item in enumerate(items):
            year = item.get("year", item.get("date", ""))
            title = item.get("title", "")
            desc = item.get("description", "")
            items_html += f'<div class="item"><div class="year">{year}</div><div class="dot"></div><h4>{title}</h4><p>{desc}</p></div>'
        # 替换整个 timeline 容器内的 row 内容
        timeline_pattern = r'<div class="row anim-stagger-list[^"]*"[^>]*>.*?</div>\s*</div>'
        replacement = f'<div class="row anim-stagger-list" data-anim-target>{items_html}</div>'
        section_html = re.sub(timeline_pattern, replacement, section_html, flags=re.DOTALL)
    
    elif slide_type == "two-column":
        # 两栏布局
        left_content = slide_data.get("left", "")
        right_content = slide_data.get("right", "")
        section_html = re.sub(r'<div class="grid[^"]*">.*?</div>', f'<div class="grid g2"><div>{left_content}</div><div>{right_content}</div></div>', section_html, flags=re.DOTALL)
    
    elif slide_type == "kpi-grid":
        # KPI 网格布局
        title = slide_data.get("title", "关键指标")
        kpis = slide_data.get("kpis", [])
        # 生成 KPI 卡片 HTML
        kpis_html = ""
        for kpi in kpis:
            label = kpi.get("label", "")
            value = kpi.get("value", "")
            delta = kpi.get("delta", "")
            # 根据 delta 内容决定颜色样式
            if delta.startswith("↑"):
                delta_style = "color:var(--good)"
            elif delta.startswith("↓"):
                delta_style = "color:var(--bad)"
            else:
                delta_style = "color:var(--warn)"
            kpis_html += f'<div class="card"><p class="eyebrow">{label}</p><div style="font-size:56px;font-weight:800">{value}</div><p class="dim" style="{delta_style}">{delta}</p></div>'
        # 如果没有 KPI 数据，使用占位符
        if not kpis_html:
            kpis_html = '<div class="card"><p class="eyebrow">指标1</p><div style="font-size:56px;font-weight:800">0</div><p class="dim">暂无数据</p></div>' * 4
        # 替换标题和 KPI 网格
        section_html = re.sub(r'<h2[^>]*>.*?</h2>', f'<h2 class="h2">{title}</h2>', section_html, flags=re.DOTALL)
        section_html = re.sub(r'<div class="grid g4[^"]*>.*?</div>', f'<div class="grid g4 mt-l">{kpis_html}</div>', section_html, flags=re.DOTALL)
    
    elif slide_type == "pros-cons":
        # 优缺点布局
        title = slide_data.get("title", "分析")
        pros = slide_data.get("pros", [])
        cons = slide_data.get("cons", [])
        # 生成优缺点列表 HTML
        pros_html = "".join([f'<li>{p}</li>' for p in pros])
        cons_html = "".join([f'<li>{c}</li>' for c in cons])
        # 替换标题
        section_html = re.sub(r'<h2[^>]*>.*?</h2>', f'<h2 class="h2">{title}</h2>', section_html, flags=re.DOTALL)
        # 替换优点列表
        section_html = re.sub(r'<ul><li>零构建.*?</ul>', f'<ul>{pros_html}</ul>', section_html, flags=re.DOTALL)
        # 替换缺点列表
        section_html = re.sub(r'<ul><li>协作不像.*?</ul>', f'<ul>{cons_html}</ul>', section_html, flags=re.DOTALL)
    
    elif slide_type == "section-divider":
        # 章节分隔页布局
        number = slide_data.get("number", "01")
        title = slide_data.get("title", "")
        subtitle = slide_data.get("subtitle", "")
        section_html = re.sub(r'<p class="kicker[^"]*>[^<]*</p>', f'<p class="kicker">Section · {number}</p>', section_html)
        section_html = re.sub(r'<h1[^>]*>.*?</h1>', f'<h1 class="h1" style="font-size:112px">{title}</h1>', section_html, flags=re.DOTALL)
        section_html = re.sub(r'<p class="lede"[^>]*>.*?</p>', f'<p class="lede" style="margin:0 auto">{subtitle}</p>', section_html, flags=re.DOTALL)
    
    elif slide_type == "three-column":
        # 三栏布局
        title = slide_data.get("title", "")
        columns = slide_data.get("columns", [])
        columns_html = ""
        for col in columns:
            icon = col.get("icon", "📌")
            col_title = col.get("title", "")
            desc = col.get("description", "")
            columns_html += f'<div class="card"><div style="font-size:40px">{icon}</div><h4 class="mt-s">{col_title}</h4><p class="dim">{desc}</p></div>'
        section_html = re.sub(r'<h2[^>]*>.*?</h2>', f'<h2 class="h2">{title}</h2>', section_html, flags=re.DOTALL)
        section_html = re.sub(r'<div class="grid g3[^"]*>.*?</div>', f'<div class="grid g3 mt-l anim-stagger-list">{columns_html}</div>', section_html, flags=re.DOTALL)
    
    # 更新页码
    if slide_idx > 0:
        section_html = re.sub(
            r'data-current="\d+"',
            f'data-current="{slide_idx}"',
            section_html
        )
        section_html = re.sub(
            r'data-total="\d+"',
            f'data-total="{total_slides}"',
            section_html
        )
    
    return section_html


def generate_html_ppt_from_outline(outline: dict, output_dir: str, theme: str = "xiaohongshu-white") -> str:
    """基于大纲生成多布局 HTML PPT
    
    Args:
        outline: PPT 大纲 dict
        output_dir: 输出目录
        theme: 主题名称
    
    Returns:
        生成的 HTML 文件路径
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # 复制 assets 到输出目录
    copy_assets_to_output(output_path)
    
    slides = outline.get("slides", [])
    # 封面必须是第一页，PPT 截图 slide_01.png 才是封面图
    if slides and slides[0].get("type") != "cover":
        slides.insert(0, {"type": "cover", "title": outline.get("title", "HTML PPT"),
                          "subtitle": outline.get("subtitle", "")})
    outline["slides"] = slides
    total_slides = len(slides)
    
    # 收集所有 slide 的 HTML（幻灯片不插正文配图）
    slides_html = []
    for i, slide_data in enumerate(slides):
        slide_idx = i + 1
        slide_html = generate_slide_html(slide_data, slide_idx, total_slides, TEMPLATES_DIR)
        if slide_html:
            slides_html.append(slide_html)
    
    # 使用本地 assets 路径
    local_assets = f"./{ASSETS_LOCAL_DIR}/assets"
    title = outline.get("title", "HTML PPT")
    outline_theme = outline.get("theme", theme)
    
    html_content = f'''<!DOCTYPE html>
<html lang="zh-CN" data-theme="{outline_theme}">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · HTML PPT</title>
<link rel="stylesheet" href="{local_assets}/fonts.css">
<link rel="stylesheet" href="{local_assets}/base.css">
<link rel="stylesheet" id="theme-link" href="{local_assets}/themes/{outline_theme}.css">
<link rel="stylesheet" href="{local_assets}/animations/animations.css">
</head>
<body data-themes="{outline_theme},minimal-white,editorial-serif,soft-pastel" data-theme-base="{local_assets}/themes/">
<div class="deck">
{"".join(slides_html)}
</div>
<script src="{local_assets}/runtime.js"></script>
</body></html>'''
    
    output_file = output_path / "04_ppt.html"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    # 保存大纲到 JSON
    outline_file = output_path / "04_ppt_outline.json"
    with open(outline_file, 'w', encoding='utf-8') as f:
        json.dump(outline, f, ensure_ascii=False, indent=2)
    
    return str(output_file)


# ========== 原有 fallback 函数 ==========

def parse_article(article_file: str) -> dict:
    """解析文章文件，提取标题和章节结构"""
    with open(article_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    lines = content.split('\n')
    
    title = ""
    sections = []
    current_section = None
    current_content = []
    
    for line in lines:
        if line.startswith('# '):
            if title:
                if current_section:
                    current_section['content'] = '\n'.join(current_content).strip()
                    sections.append(current_section)
            title = line[2:].strip()
            current_section = None
            current_content = []
        elif line.startswith('## '):
            if current_section:
                current_section['content'] = '\n'.join(current_content).strip()
                sections.append(current_section)
            current_section = {
                'title': line[3:].strip(),
                'content': ''
            }
            current_content = []
        else:
            current_content.append(line)
    
    if current_section:
        current_section['content'] = '\n'.join(current_content).strip()
        sections.append(current_section)
    
    return {
        'title': title,
        'sections': sections,
        'raw_content': content
    }


def extract_bullets(text: str) -> List[str]:
    """从文本中提取 bullet points"""
    bullets = []
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # 过滤 Markdown 链接
        line = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', line)
        # 过滤 URL
        line = re.sub(r'https?://\S+', '', line)
        if line.startswith('- ') or line.startswith('* '):
            bullets.append(line[2:].strip())
        elif line.startswith('1. ') or line.startswith('2. ') or line.startswith('3. '):
            match = re.match(r'^\d+\.\s+(.+)$', line)
            if match:
                bullets.append(match.group(1))
        elif line.startswith('【') or line.startswith('『'):
            bullets.append(line.strip())
        elif len(line) > 5 and len(line) < 200 and re.search(r'[。！？；.,!?;]$', line):
            # 要求是完整句子（有句末标点），且长度合适
            bullets.append(line)
    return bullets[:6]


def generate_cover_slide(title: str, total_slides: int) -> str:
    """生成封面幻灯片 HTML"""
    return f'''
  <section class="slide" data-title="封面">
    <p class="kicker">Article</p>
    <h1 class="h1 anim-fade-up" data-anim="fade-up">{title}</h1>
    <div class="deck-footer"><span class="dim2">{BRAND_NAME}</span><span class="slide-number" data-current="1" data-total="{total_slides}"></span></div>
  </section>'''


def generate_toc_slide(sections: List[dict], current_idx: int, total_slides: int) -> str:
    """生成目录幻灯片 HTML"""
    items_html = []
    for i, section in enumerate(sections[:5]):
        items_html.append(f'''
      <div class="card"><div class="row"><div class="h3 dim2" style="width:56px">{i+1:02d}</div><div><h4>{section['title']}</h4></div></div></div>''')
    
    return f'''
  <section class="slide" data-title="目录">
    <p class="eyebrow">Contents · 目录</p>
    <h2 class="h2">内容概览</h2>
    <div class="grid g2 mt-l anim-stagger-list" data-anim-target>
      {"".join(items_html)}
    </div>
    <div class="deck-footer"><span class="dim2">目录</span><span class="slide-number" data-current="{current_idx}" data-total="{total_slides}"></span></div>
  </section>'''


def generate_content_slide(section: dict, slide_idx: int, total_slides: int) -> str:
    """生成内容幻灯片 HTML"""
    bullets = extract_bullets(section['content'])
    title = section['title']
    
    if not bullets:
        bullets = [section['content'][:100] + "..." if len(section['content']) > 100 else section['content']]
    
    bullets_html = '\n'.join([
        f'<li class="card card-accent"><h4>{b}</h4></li>' for b in bullets
    ])
    
    return f'''
  <section class="slide" data-title="{title}">
    <p class="kicker">Section</p>
    <h2 class="h2">{title}</h2>
    <ul class="grid g1 anim-stagger-list" style="list-style:none;padding:0;margin:0;gap:14px" data-anim-target>
      {bullets_html}
    </ul>
    <div class="deck-footer"><span class="dim2">{title}</span><span class="slide-number" data-current="{slide_idx}" data-total="{total_slides}"></span></div>
  </section>'''


def generate_thanks_slide(slide_idx: int, total_slides: int) -> str:
    """生成感谢幻灯片 HTML"""
    return f'''
  <section class="slide center tc" data-title="感谢">
    <h1 class="h1" style="font-size:160px;line-height:1"><span class="gradient-text">Thanks</span></h1>
    <p class="lede">感谢阅读</p>
    <div class="deck-footer"><span class="dim2">{BRAND_NAME}</span><span class="slide-number" data-current="{slide_idx}" data-total="{total_slides}"></span></div>
  </section>'''


def generate_html_ppt(article_file: str, output_dir: str, theme: str = "xiaohongshu-white", api_key: str = None) -> str:
    """
    生成 HTML PPT（新版：先 LLM 生成大纲，再生成 PPT）
    
    Args:
        article_file: 文章文件路径
        output_dir: 输出目录
        theme: 主题名称（默认 xiaohongshu-white）
        api_key: MiniMax API 密钥（可选）
    
    Returns:
        生成的 HTML 文件路径
    """
    # 如果没有 api_key，从 config.json 兜底取 MiniMax key；再没有才走简单解析
    if not api_key:
        try:
            api_key = get_minimax_api_key()
        except Exception:
            api_key = None
    if not api_key:
        return _generate_html_ppt_fallback(article_file, output_dir, theme)

    try:
        # 调用 LLM 生成大纲
        outline = generate_ppt_outline(article_file, api_key)
        # 按文章小节顺序重排幻灯片：页序跟着文章走，插回正文时才对得上
        reorder_slides_by_article(outline, article_file)
        # 基于大纲生成 PPT
        html_file = generate_html_ppt_from_outline(outline, output_dir, theme)
        return html_file
    except Exception as e:
        print(f"LLM 生成失败，使用 fallback: {e}")
        return _generate_html_ppt_fallback(article_file, output_dir, theme)


def _generate_html_ppt_fallback(article_file: str, output_dir: str, theme: str = "xiaohongshu-white") -> str:
    """原有 fallback 实现：读取文章文件，解析结构，生成 HTML PPT"""
    article_path = Path(article_file)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # 复制 assets 到输出目录（使用本地相对路径）
    copy_assets_to_output(output_path)
    
    article_data = parse_article(article_file)
    title = article_data['title']
    sections = article_data['sections']
    
    # 计算总幻灯片数
    # 封面 + 目录 + 各章节 + 感谢页
    num_sections = len(sections)
    if num_sections > 5:
        num_sections = 5  # 限制最多 5 个章节
    total_slides = 2 + num_sections + 1  # 封面 + 目录 + 章节 + 感谢
    
    slides_html = []
    
    # Slide 1: 封面
    slides_html.append(generate_cover_slide(title, total_slides))
    
    # Slide 2: 目录
    slides_html.append(generate_toc_slide(sections, 2, total_slides))
    
    # Slides 3-N: 各章节内容
    for i, section in enumerate(sections[:5]):
        slide_idx = i + 3
        slides_html.append(generate_content_slide(section, slide_idx, total_slides))
    
    # 最后一页: 感谢页
    slides_html.append(generate_thanks_slide(total_slides, total_slides))
    
    # 使用本地 assets 路径
    local_assets = f"./{ASSETS_LOCAL_DIR}/assets"
    html_content = f'''<!DOCTYPE html>
<html lang="zh-CN" data-theme="{theme}">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · HTML PPT</title>
<link rel="stylesheet" href="{local_assets}/fonts.css">
<link rel="stylesheet" href="{local_assets}/base.css">
<link rel="stylesheet" id="theme-link" href="{local_assets}/themes/{theme}.css">
<link rel="stylesheet" href="{local_assets}/animations/animations.css">
</head>
<body data-themes="{theme},minimal-white,editorial-serif,soft-pastel" data-theme-base="{local_assets}/themes/">
<div class="deck">
{"".join(slides_html)}
</div>
<script src="{local_assets}/runtime.js"></script>
</body></html>'''
    
    output_file = output_path / f"{article_path.stem}_ppt.html"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    return str(output_file)


def capture_slides_as_images(html_file: str, output_dir: str, max_slides: int = 6) -> List[str]:
    """
    使用 Playwright 截图 HTML PPT 的每一页。
    
    Args:
        html_file: HTML 文件路径
        output_dir: 截图输出目录
        max_slides: 最大截图数量（默认 6）
    
    Returns:
        截图文件路径列表
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("请安装 playwright: pip install playwright && playwright install chromium")
        return []
    
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    screenshot_files = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        
        try:
            # 先看总页数
            page.goto(f"file://{html_file}", timeout=60000, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            total = len(page.query_selector_all(".slide"))

            # 用 runtime.js 的 preview 模式（?preview=N）逐页截图。
            # 不要在同一个 deck 里切 is-active：所有 slide 是绝对定位叠在一起的，
            # 截元素框拿到的是叠层混合图，配图会被压在别的 slide 底下画不出来。
            for i in range(min(total, max_slides)):
                page.goto(f"file://{html_file}?preview={i + 1}", timeout=60000, wait_until="networkidle")
                page.wait_for_timeout(900)  # 等入场动画结束

                slide = page.query_selector(".slide.is-active")
                if not slide:
                    continue

                filename = output_path / f"slide_{i+1:02d}.png"
                slide.screenshot(path=str(filename))
                screenshot_files.append(str(filename))

        except Exception as e:
            print(f"截图过程中出错: {e}")
        finally:
            browser.close()
    
    return screenshot_files


PPT_SLIDE_IMG_RE = re.compile(r"ppt_slides[/\\]slide_\d+\.png")
PPT_SECTION_RE = re.compile(r"^##\s*PPT\s*幻灯片\s*$")
# 这些小节不放幻灯片：结论段和图集段插整页截图会打断阅读
PPT_SKIP_SECTION_RE = re.compile(r"写在最后|新闻配图|PPT\s*幻灯片")


def _slide_text(slide: dict) -> str:
    """把一页 slide 的所有文案拼成一个字符串，用于和小节正文比对"""
    parts = []
    for k, v in slide.items():
        if k in ("type", "image"):
            continue
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, list):
            for it in v:
                if isinstance(it, str):
                    parts.append(it)
                elif isinstance(it, dict):
                    parts.extend(str(x) for x in it.values() if isinstance(x, str))
        elif isinstance(v, dict):
            parts.extend(str(x) for x in v.values() if isinstance(x, str))
    return " ".join(parts)


def _bigrams(text: str) -> set:
    s = re.sub(r"[^一-鿿A-Za-z0-9]", "", text)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _match_sections(slides: List[dict], lines: List[str]) -> List[int]:
    """给每页 slide 找最贴切的小节

    返回每页 slide 对应的小节序号（keep 列表下标，-1 表示没有可放的小节）。
    用 2 字词组重合度打分：slide 的文案和哪个小节正文共享的词最多，就放哪节。
    """
    heads = [k for k, l in enumerate(lines) if l.startswith("## ")]
    keep = [h for h in heads if not PPT_SKIP_SECTION_RE.search(lines[h])]
    if not keep:
        return [-1] * len(slides)

    # 每节的正文 = 标题 + 到下一个 ## 之前
    section_text = {}
    for h in keep:
        nxt = next((x for x in heads if x > h), len(lines))
        section_text[h] = "\n".join(lines[h:nxt])
    grams = {h: _bigrams(section_text[h]) for h in keep}

    out = []
    for slide in slides:
        sg = _bigrams(_slide_text(slide))
        scores = [(len(sg & grams[h]), i) for i, h in enumerate(keep)]
        best_score, best_idx = max(scores)
        out.append(best_idx if best_score else -1)
    return out


def reorder_slides_by_article(outline: dict, article_file: str) -> dict:
    """把大纲里的内容页按文章小节顺序重排，并记下每页属于第几节（_section）

    LLM 给的大纲顺序不一定跟文章一致（可能先讲数据再讲定义）。
    重排后页序 = 文章顺序，插回正文时每页都落在它对应的小节后面。
    """
    slides = outline.get("slides", [])
    if len(slides) < 2:
        return outline
    try:
        lines = Path(article_file).read_text(encoding="utf-8").splitlines()
    except OSError:
        return outline

    cover, rest = slides[0], slides[1:]
    matches = _match_sections(rest, lines)
    order = sorted(range(len(rest)), key=lambda i: (matches[i] if matches[i] >= 0 else 10**6, i))
    for new_i, old_i in enumerate(order):
        rest[old_i]["_section"] = matches[old_i]
    outline["slides"] = [cover] + [rest[i] for i in order]
    return outline


def place_ppt_images(article_path: str, slide_files: List[str], outline_slides: List[dict] = None) -> dict:
    """把 PPT 截图插进文章对应小节。

    封面图插到正文最前（H1 标题之后）；其余每页按文案关键词匹配到最贴切的小节，
    插在该小节末尾（读者读完这节再看这节的图示）。
    幻灯片本身不插正文配图 —— 同一张图在正文和整页版式里出现两次会被压成小图。

    幂等：重跑时先清掉旧的 PPT 占位符和旧段落，不会重复插入。

    Args:
        article_path: 文章 md 路径
        slide_files: 截图文件列表（顺序即页序）
        outline_slides: 大纲里的 slide 列表，用于按文案匹配小节
    """
    art = Path(article_path)
    if not art.exists() or not slide_files:
        return {"cover": "", "placed": 0}

    raw = art.read_bytes()
    nl = "\r\n" if b"\r\n" in raw else "\n"  # 保持原文换行风格
    lines = raw.decode("utf-8").replace("\r\n", "\n").splitlines()
    base = art.parent

    def rel(p):
        try:
            return os.path.relpath(Path(p).resolve(), base.resolve()).replace("\\", "/")
        except ValueError:
            return str(p).replace("\\", "/")

    # 清掉旧的「## PPT 幻灯片」段和旧的 PPT 占位符
    kept = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if PPT_SECTION_RE.match(line.strip()):
            i += 1
            while i < len(lines) and not lines[i].startswith("## "):
                i += 1
            continue
        if "[[IMG:" in line and PPT_SLIDE_IMG_RE.search(line):
            i += 1
            continue
        kept.append(line)
        i += 1
    lines = kept

    cover = rel(slide_files[0])
    rest = [rel(s) for s in slide_files[1:]]

    # 封面：紧跟 H1 标题，作为正文第一张图
    h1 = next((k for k, l in enumerate(lines) if l.startswith("# ")), None)
    head = lines[:h1 + 1] if h1 is not None else []
    tail = lines[h1 + 1:] if h1 is not None else lines
    while tail and not tail[0].strip():
        tail.pop(0)
    lines = head + ["", f"[[IMG: {cover}]]", ""] + tail

    # 按小节锚定：每页 slide 匹配到最贴切的小节，插在该小节末尾
    heads = [k for k, l in enumerate(lines) if l.startswith("## ")]
    keep = [h for h in heads if not PPT_SKIP_SECTION_RE.search(lines[h])]

    def section_end(h):
        nxt = next((x for x in heads if x > h), None)
        return (nxt - 1) if nxt is not None else (len(lines) - 1)

    anchor_after = {}   # 行号 -> [占位符]
    for idx, path in enumerate(rest):
        sec = None
        if outline_slides and idx + 1 < len(outline_slides):
            s = outline_slides[idx + 1].get("_section")
            if isinstance(s, int) and 0 <= s < len(keep):
                sec = s
        if sec is None:  # 没有匹配结果就顺延
            sec = min(idx, len(keep) - 1) if keep else None
        h = keep[sec] if sec is not None else None
        anchor_after.setdefault(section_end(h) if h is not None else len(lines) - 1, []).append(path)

    placed_inline = len(rest)

    if placed_inline:
        # 重新拼装：锚点行之后插占位符
        out = []
        for k, l in enumerate(lines):
            out.append(l)
            for p in anchor_after.get(k, []):
                out += ["", f"[[IMG: {p}]]"]
        lines = out
    elif rest:
        # 实在锚不上，退回文末集中放
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", "## PPT 幻灯片", ""]
        for r in rest:
            lines += [f"[[IMG: {r}]]", ""]
        while lines and not lines[-1].strip():
            lines.pop()

    art.write_bytes((nl.join(lines) + nl).encode("utf-8"))
    return {"cover": cover, "placed": len(slide_files), "inline": placed_inline}


def main():
    """命令行接口"""
    parser = argparse.ArgumentParser(
        description="HTML PPT 生成和截图工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python html_ppt_chart.py article.md output_dir --theme xiaohongshu-white --slides 6
  python html_ppt_chart.py article.md output_dir --api-key YOUR_KEY --slides 9
        """
    )
    
    parser.add_argument('article_file', nargs='?', help='文章文件路径 (Markdown)')
    parser.add_argument('output_dir', nargs='?', help='输出目录路径')
    parser.add_argument('--theme', '-t', default='xiaohongshu-white', help='主题名称 (默认: xiaohongshu-white)')
    parser.add_argument('--slides', '-s', type=int, default=6, help='最大截图数量 (默认: 6)')
    parser.add_argument('--screenshot-only', action='store_true', help='只截图，不生成 PPT')
    parser.add_argument('--html-file', help='指定已生成的 HTML 文件进行截图')
    parser.add_argument('--slides-dir', help='截图输出目录（默认与 output_dir 相同，目录不存在会自动创建）')
    parser.add_argument('--api-key', '-k', help='MiniMax API 密钥 (用于 LLM 预处理)')

    args = parser.parse_args()

    if args.html_file:
        html_file = args.html_file
        if not args.output_dir:
            output_dir = str(Path(html_file).parent)
        else:
            output_dir = args.output_dir
    elif args.article_file and args.output_dir:
        t0 = time.time()
        html_file = generate_html_ppt(args.article_file, args.output_dir, args.theme, args.api_key)
        print(f"✓ PPT 已生成: {html_file}")

        if args.screenshot_only:
            print("跳过截图 (--screenshot-only)")
        else:
            slides_dir = args.slides_dir or args.output_dir
            print(f"正在截图 (最多 {args.slides} 张) -> {slides_dir}...")
            screenshots = capture_slides_as_images(html_file, slides_dir, args.slides)
            print(f"✓ 截图已保存: {len(screenshots)} 张")
            for sf in screenshots:
                print(f"  - {sf}")
            if not screenshots:
                print("[!] 没有截图成功，未写入占位符")
            else:
                # 从大纲里取每页的文案，用来把幻灯片锚到最贴切的小节。
                # 大纲只在本轮 LLM 路径成功时才有效（mtime 晚于生成开始时间），
                # fallback 时留着旧大纲会把占位符锚到过期的位置。
                outline_slides = []
                outline_file = Path(args.output_dir or Path(html_file).parent) / "04_ppt_outline.json"
                if outline_file.exists() and outline_file.stat().st_mtime >= t0:
                    try:
                        outline = json.loads(outline_file.read_text(encoding="utf-8"))
                        outline_slides = outline.get("slides", [])
                    except (OSError, ValueError):
                        outline_slides = []
                res = place_ppt_images(args.article_file, screenshots, outline_slides)
                print(f"✓ 占位符已写入: 封面 {res['cover']} 在正文最前，"
                      f"其余 {res['placed'] - 1} 页中 {res.get('inline', 0)} 页插在对应段落")
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
