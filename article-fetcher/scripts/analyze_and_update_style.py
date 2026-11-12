#!/usr/bin/env python3



"""



Analyze article style and update style.md + index.json.



Handles both text content and image position analysis.



"""







import sys
from pathlib import Path

import os



import json



import re



import argparse



from datetime import datetime







STYLE_SECTIONS = ['标题', '开篇', '句式', '词汇', '结尾', '结构', '配图位置', '教程类型', '排版格式', '特色']








def load_index_json(topic_dir):



    idx_path = os.path.join(topic_dir, 'index.json')



    if os.path.exists(idx_path):



        with open(idx_path, 'r', encoding='utf-8') as f:



            return json.load(f)



    return {'topic': topic_dir.split('/')[-1], 'updated_at': '', 'articles': []}











def save_index_json(topic_dir, index_data):



    idx_path = os.path.join(topic_dir, 'index.json')



    with open(idx_path, 'w', encoding='utf-8') as f:



        json.dump(index_data, f, ensure_ascii=False, indent=2)











def load_style_md(topic_dir):



    style_path = os.path.join(topic_dir, 'style.md')



    if os.path.exists(style_path):



        with open(style_path, 'r', encoding='utf-8') as f:



            return f.read()



    return ''











def parse_style_md(content):



    sections = {s: [] for s in STYLE_SECTIONS}



    if not content.strip():



        return sections



    current = None



    for line in content.split('\n'):



        line = line.strip()



        if not line:



            continue



        if line.startswith('## '):



            current = line[3:].strip()



        elif line.startswith('- ') and current:



            sections.setdefault(current, []).append(line[2:].strip())



    return sections











def update_style_md(topic_dir, new_findings):



    sections = {s: [] for s in STYLE_SECTIONS}



    existing = load_style_md(topic_dir)



    if existing:



        sections = parse_style_md(existing)



    # 单篇特有值：每篇都不同，追加会堆积矛盾。同组的旧值替换掉，不同组互不影响。
    volatile_groups = {

        '全文约': 'count_body',

        '标题长度约': 'count_title',

        '配图约': 'count_img',

        '配图位置分布': 'count_img',

        '配图以': 'img_type',

        '配图类型': 'img_type',

        '使用单一强调色': 'color_main',

        '重点色': 'color_key',

        '大字号用于章节标题': 'font_size',

    }

    def volatile_group(bullet):

        bl = bullet.lower()

        if bl.startswith('使用') and re.match(r'^使用\d+种强调色', bullet):

            return 'color_main'

        for prefix, group in volatile_groups.items():

            if bl.startswith(prefix.lower()):

                return group

        return None

    for section, new_points in new_findings.items():

        if section not in sections:

            sections[section] = []

        for p in new_points:

            group = volatile_group(p)

            if group:

                sections[section] = [x for x in sections[section]

                                     if volatile_group(x) != group]

            existing_lower = [x.lower() for x in sections[section]]

            if p.lower() not in existing_lower:

                sections[section].append(p)

    lines = ['# ' + os.path.basename(os.path.normpath(topic_dir)) + ' 写作风格指南']



    for section in STYLE_SECTIONS:



        if sections[section]:



            lines.append('\n## ' + section)



            for p in sections[section]:



                lines.append('- ' + p)



    style_path = os.path.join(topic_dir, 'style.md')



    with open(style_path, 'w', encoding='utf-8') as f:



        f.write('\n'.join(lines))



    return sections











def update_index_json(topic_dir, topic, title, url):



    index = load_index_json(topic_dir)



    index['updated_at'] = datetime.now().strftime('%Y-%m-%d')



    index['topic'] = topic



    if any(a['url'] == url for a in index['articles']):



        return index



    index['articles'].append({



        'title': title,



        'url': url,



        'saved_at': datetime.now().strftime('%Y-%m-%d')



    })



    save_index_json(topic_dir, index)



    return index











def strip_html(content):



    text = content



    text = re.sub(r'<script[^>]*>[\s\S]*?</script>', '', text, flags=re.IGNORECASE)



    text = re.sub(r'<style[^>]*>[\s\S]*?</style>', '', text, flags=re.IGNORECASE)



    text = re.sub(r'<noscript[^>]*>[\s\S]*?</noscript>', '', text, flags=re.IGNORECASE)



    block_tags = ['</p>', '</div>', '</li>', '<br>', '<br/>', '<br />',



                  '</h1>', '</h2>', '</h3>', '</h4>', '</tr>', '</section>', '</article>']



    for tag in block_tags:



        text = text.replace(tag, '\n')



    text = re.sub(r'<[^>]+>', ' ', text)



    text = re.sub(r' +', ' ', text)



    return text.strip()











def analyze_images(images_json_path, paragraphs):



    findings = []



    if not os.path.exists(images_json_path):



        return findings







    with open(images_json_path, 'r', encoding='utf-8') as f:



        images = json.load(f)







    if not images:



        return findings







    total = len(images)



    findings.append(f'配图约{total}张')







    para_count = len(paragraphs)







    if para_count > 0 and total > 0:



        ratio = total / para_count



        if ratio >= 0.5:



            findings.append('配图密度高，几乎每段一张图')



        elif ratio >= 0.3:



            findings.append('配图密度中等，每2-3段配一张图')



        elif ratio >= 0.15:



            findings.append('配图密度适中，每5-7段配一张图')



        else:



            findings.append('配图稀疏，长段落配一张图')







    contexts_before = [img['context_before'] for img in images if img['context_before']]



    contexts_after = [img['context_after'] for img in images if img['context_after']]







    heading_keywords = ['一', '二', '三', '四', '五', '六', '首先', '其次', '最后',



                        '总结', '前言', '背景', '步骤', 'Step', '第', '章']



    after_heading = sum(1 for ctx in contexts_after



                        if any(kw in ctx[:30] for kw in heading_keywords))



    if after_heading > total * 0.4:



        findings.append('配图常位于小标题之后，起分割章节作用')







    mid_position = sum(1 for i, img in enumerate(images)



                       if 0.2 < (i / max(total - 1, 1)) < 0.8)



    if mid_position > total * 0.5:



        findings.append('配图分布在文章中后段，丰富视觉体验')







    tech_words = ['代码', '截图', '界面', '示例', '效果', '图', '表', '数据',



                  '步骤', 'Prompt', '操作', '功能', '系统']



    has_tech_context = sum(



        1 for img in images



        if any(w in (img.get('context_before', '') + img.get('context_after', ''))



               for w in tech_words)



    )



    if has_tech_context > total * 0.5:



        findings.append('配图以技术截图/界面图为主，说明型配图')



    else:



        findings.append('配图以场景/人物/素材图为主，情感型配图')







    return findings

def named_color(c, color_map):

    """统一颜色名称：灰色统一归为灰色(xxx)，其余原样保留。"""

    if c in color_map:

        return color_map[c]

    m = re.match(r'rgb\((\d+),\s*(\d+),\s*(\d+)\)', c)

    if m and m.group(1) == m.group(2) == m.group(3):

        return f'灰色({c})'

    return c


def analyze_formatting(content):
    """Analyze rich text formatting from HTML: bold, color, font-size."""
    import html as html_module

    # Decode HTML entities and hex escapes used by WeChat (e.g. \x22 -> ")
    decoded = html_module.unescape(content)
    decoded = decoded.replace('\x22', chr(34)).replace('\x3e', '>').replace('\x3c', '<').replace('\x27', "'")

    findings = []

    bold_pattern = re.compile(r'style="[^"]*font-weight:\s*bold[^"]*"[^>]*>([^<]+)<')
    color_pattern = re.compile(r'style="[^"]*color:\s*(rgb\([^)]+\)|#[0-9a-fA-F]{3,6})[^"]*"[^>]*>([^<]+)<')
    big_font_pattern = re.compile(r'style="[^"]*font-size:\s*(\d+)px[^"]*"[^>]*>([^<]+)<')

    bold_texts = [m.group(1).strip() for m in bold_pattern.finditer(decoded)]
    color_texts = [(m.group(1).strip(), m.group(2).strip()) for m in color_pattern.finditer(decoded)]
    big_font_items = [(int(m.group(1)), m.group(2).strip()) for m in big_font_pattern.finditer(decoded)]

    if bold_texts:
        if len(bold_texts) >= 5:
            findings.append('频繁使用加粗强调重点词句')
        short_bolds = [t for t in bold_texts if len(t) < 15]
        if short_bolds:
            findings.append('加粗多用于短词组/关键词，非整句加粗')
        if any(len(t) > 20 for t in bold_texts):
            findings.append('偶尔也有整句加粗强调')

    if color_texts:
        unique_colors = set(c[0] for c in color_texts)
        color_map = {
            'rgb(255, 104, 39)': '橙色',
            'rgb(218, 76, 76)': '红色',
            'rgb(76, 175, 80)': '绿色',
            'rgb(33, 150, 243)': '蓝色',
            'rgb(171, 25, 66)': '深红色',
            'rgb(123, 12, 0)': '深红棕色',
            'rgb(178, 178, 178)': '灰色',
        }
        if len(unique_colors) == 1:
            findings.append(f"使用单一强调色：{named_color(list(unique_colors)[0], color_map)}")
        elif len(unique_colors) > 1:
            findings.append(f"使用{len(unique_colors)}种强调色")
        for c, t in color_texts[:10]:
            named = named_color(c, color_map)
            if len(t) < 15:
                findings.append(f"重点色{named}用于小标签/章节编号（如\"{t}\"）")

    big_font_filtered = [(sz, t) for sz, t in big_font_items if sz >= 28]
    if big_font_filtered:
        findings.append(f"大字号用于章节标题/编号（最大{big_font_filtered[0][0]}px）")

    if ('font-weight: bold' in decoded or 'font-weight:700' in decoded) and findings:
        findings.append('正文加粗用于重点强调')

    return findings

def analyze_style(content, title, images_json_path=None):

    findings = {s: [] for s in STYLE_SECTIONS}



    text = strip_html(content)



    paragraphs = [p.strip() for p in text.split('\n') if p.strip()]







    title_chars = len(title)



    findings['标题'].append('标题长度约' + str(title_chars) + '字')



    if any(c in title for c in '？？！！'):



        findings['标题'].append('使用疑问句引发好奇')



    if any(c.isdigit() for c in title):



        findings['标题'].append('使用数字吸引注意力')



    if any(w in title for w in ['突发', '重磅', '刚刚', '终于', '震惊']):



        findings['标题'].append('使用情绪词/热点词')



    if '—' in title or '–' in title or '-' in title:



        findings['标题'].append('使用转折符号制造反差')







    if paragraphs:



        first = paragraphs[0]



        fl = len(first)



        if fl < 50:



            findings['开篇'].append('短句开头，快速切入')



        elif fl > 100:



            findings['开篇'].append('长段落开篇，渲染气氛')



        quote_chars = ['「', '"', '"', ''', ''']



        if any(first.startswith(ch) for ch in quote_chars):



            findings['开篇'].append('引用他人话语开篇')



        time_words = ['今天', '最近', '近日', '日前', '这个月', '上周', '昨天']



        if any(w in first for w in time_words):



            findings['开篇'].append('以时间节点切入')







    short_paras = sum(1 for p in paragraphs if len(p) < 50)



    long_paras = sum(1 for p in paragraphs if len(p) > 100)



    if short_paras > long_paras:



        findings['句式'].append('以短句为主，节奏紧凑')



    elif long_paras > short_paras:



        findings['句式'].append('以长句为主，论述深入')



    if text.count('\n\n') > 5:



        findings['句式'].append('善用空行分段制造节奏感')







    formal_words = ['表明', '显示', '研究', '数据', '分析', '发现', '基于']



    casual_words = ['其实', '就是', '比方说', '大家', '我们']



    formal_count = sum(1 for w in formal_words for p in paragraphs if w in p)



    casual_count = sum(1 for w in casual_words for p in paragraphs if w in p)



    if formal_count > casual_count:



        findings['词汇'].append('使用专业术语/正式表达')



    elif casual_count > formal_count:



        findings['词汇'].append('使用口语化表达，亲切易懂')







    if paragraphs:



        last = paragraphs[-1]



        if len(last) < 30:



            findings['结尾'].append('短句结尾，干脆有力')



        action_words = ['一起', '赶紧', '现在', '立即', '马上']



        if any(w in last for w in action_words):



            findings['结尾'].append('使用行动号召')



        if not any(last.endswith(c) for c in ['。', '！', '？']):



            findings['结尾'].append('金句/留白式结尾')







    findings['结构'].append('全文约' + str(len(paragraphs)) + '个段落')



    if len(paragraphs) > 10:



        findings['结构'].append('长文结构，论述充分')



    if len(paragraphs) < 6:



        findings['结构'].append('短文结构，简洁有力')



    if '：' in text and '"' in text:



        findings['结构'].append('使用对话/引用增强可读性')







    if images_json_path:



        img_findings = analyze_images(images_json_path, paragraphs)



        findings['配图位置'].extend(img_findings)
        findings['排版格式'] = analyze_formatting(content)








    findings = {k: v for k, v in findings.items() if v}



    return findings











def main():



    parser = argparse.ArgumentParser(description='Analyze article style')



    parser.add_argument('topic', help='Topic name')



    parser.add_argument('title', help='Article title')



    parser.add_argument('url', help='Article URL')



    parser.add_argument('--content-file', dest='content_file', default=None,
                        help='Path to content file (HTML/TXT). If omitted, reads from stdin.')



    parser.add_argument('--images', dest='images_json', default=None,
                        help='Path to images JSON file')
    
    parser.add_argument('--output-dir', '-o', dest='output_dir', default=None,
                        help='Output directory for reference files. Default: skill references folder')

    args = parser.parse_args()







    topic = args.topic



    title = args.title



    url = args.url



    content = ''



    images_json_path = args.images_json







    if args.content_file:



        with open(args.content_file, 'r', encoding='utf-8') as f:



            content = f.read()



    else:



        content = sys.stdin.read()







    if not content.strip():



        print("Warning: empty content, skipping analysis", file=sys.stderr)



        sys.exit(0)







    script_dir = os.path.dirname(os.path.abspath(__file__))
    skill_dir = os.path.dirname(script_dir)
    project_root = os.path.join(skill_dir, '..')
    default_reference_dir = os.path.join(project_root, 'reference')
    
    if args.output_dir:
        output_path = Path(args.output_dir).resolve()
        if str(output_path).endswith('reference') or str(output_path).endswith('reference' + os.sep):
            project_reference_dir = str(output_path)
        else:
            project_reference_dir = os.path.join(args.output_dir, 'reference')
        topic_dir = os.path.join(project_reference_dir, topic)
    else:
        topic_dir = os.path.join(default_reference_dir, topic)

    os.makedirs(topic_dir, exist_ok=True)







    findings = analyze_style(content, title, images_json_path)



    update_style_md(topic_dir, findings)



    update_index_json(topic_dir, topic, title, url)



    print('Topic:', topic)



    print('Article:', title)



    print('Style findings:')



    for section, points in findings.items():



        print(f'  - [{section}] {len(points)} points')



    print('Updated:', topic_dir + '/style.md')



    print('Updated:', topic_dir + '/index.json')











if __name__ == '__main__':



    main()



