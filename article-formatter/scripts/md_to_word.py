#!/usr/bin/env python3
"""
Convert Markdown articles to Word documents with image insertion and table support.
Supports headings, bold text, lists, images, tables, and basic formatting.
"""

import sys
import argparse
import re
import os
import tempfile
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn


def set_chinese_font(run, font_name='Microsoft YaHei', font_size=12, bold=False):
    """Set Chinese font for a run (default: Microsoft YaHei)."""
    run.font.name = font_name
    run.font.size = Pt(font_size)
    run.font.bold = bold
    run._element.rPr.rFonts.set(qn('w:eastAsia'), font_name)


def parse_table_line(line):
    """Parse a table row from markdown."""
    line = line.strip()
    if line.startswith('|'):
        line = line[1:]
    if line.endswith('|'):
        line = line[:-1]
    
    cells = [cell.strip() for cell in line.split('|')]
    return cells


def is_table_separator(line):
    """Check if line is a table separator."""
    stripped = line.strip()
    if not stripped.startswith('|') or not stripped.endswith('|'):
        return False
    
    content = stripped[1:-1]
    return all(c in '-|: \t' for c in content)


def remove_image_description_section(md_content):
    """
    Remove image description section from the end of article.
    Matches patterns like:
    - **配图说明：** or **配图说明：**
    - ---
    - [[IMG: ...]] descriptions
    - 1. [[IMG: ...]] - description
    """
    lines = md_content.split('\n')
    
    # Find the start of image description section
    image_section_start = -1
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Match various image description headers
        has_header = stripped.startswith('**配图说明') or stripped.startswith('**配图清单')
        is_late_rule = stripped.startswith('---') and i > len(lines) * 0.7  # Horizontal rule near end
        if has_header or is_late_rule:
            # Check if next lines contain IMG placeholders
            for j in range(i+1, min(i+10, len(lines))):
                nxt = lines[j].strip()
                if has_header and ('[[IMG:' in nxt or '配图' in nxt):
                    image_section_start = i
                    break
                # A bare '---' only marks a caption list when the placeholders
                # carry captions ("1. [[IMG: x]]" / "[[IMG: x]] - 描述").
                # Bare placeholders under a heading are real content (图集章节).
                if is_late_rule and (re.match(r'^\d+\.[\s\t]*\[\[IMG:', nxt) or
                                     re.match(r'^\[\[IMG:.*\]\]\s*[-—:：]\s*\S', nxt)):
                    image_section_start = i
                    break
            if image_section_start >= 0:
                break
        # Also detect standalone IMG list at end
        if re.match(r'^\d+\.[\s\t]*\[\[IMG:', stripped) and i > len(lines) * 0.7:
            # Look backwards for the section start
            for k in range(i-1, max(0, i-10), -1):
                if lines[k].strip().startswith('**') or lines[k].strip().startswith('---'):
                    image_section_start = k
                    break
            if image_section_start < 0:
                image_section_start = i
            break
    
    # If found, remove from that point onwards
    if image_section_start >= 0:
        # Keep content before the image section
        return '\n'.join(lines[:image_section_start])
    
    return md_content


def parse_markdown(md_content):
    """Parse markdown content into structured elements."""
    # Remove image description section first
    md_content = remove_image_description_section(md_content)
    
    elements = []
    lines = md_content.split('\n')
    
    i = 0
    first_heading = True
    
    while i < len(lines):
        line = lines[i].strip()

        # Strip legacy template markers (e.g. {{chart:bar:...}}) — no renderer
        # consumes them, so they'd otherwise reach the reader as garbage.
        if '{{' in line:
            line = re.sub(r'\{\{.*?\}\}', '', line).strip()
            if not line:
                i += 1
                continue

        if not line:
            i += 1
            continue
        
        # Skip disclaimer footer
        if line.startswith('*本文基于') or line.startswith('*本文仅供'):
            i += 1
            continue
        
        # Table detection
        if line.startswith('|'):
            table_rows = []
            is_table = False
            j = i
            
            while j < len(lines) and lines[j].strip().startswith('|'):
                if is_table_separator(lines[j]):
                    is_table = True
                table_rows.append(lines[j].strip())
                j += 1
            
            if len(table_rows) >= 2 and is_table:
                headers = None
                rows = []
                
                for row_line in table_rows:
                    if is_table_separator(row_line):
                        continue
                    cells = parse_table_line(row_line)
                    if headers is None:
                        headers = cells
                    else:
                        rows.append(cells)
                
                # Drop TOC-shaped tables (编号 + 标题, 两列), but keep real data
                # tables — a table whose first header is "编号" used to be
                # deleted line by line, taking the whole table with it.
                if headers and len(headers) == 2 and headers[0].strip() in ('编号', '序号', '章节'):
                    i = j
                    continue

                elements.append({
                    'type': 'table',
                    'headers': headers,
                    'rows': rows
                })
                i = j
                continue
        # Image placeholder (support both [[IMG:...]] and **[[IMG:...]]**)
        img_match = re.search(r'\[\[IMG:\s*(.*?)\]\]', line)
        if img_match:
            elements.append({
                'type': 'image_placeholder',
                'description': img_match.group(1)
            })
            i += 1
            continue
        
        # Heading 1 - keep first one (article title)
        if line.startswith('# ') and not line.startswith('## '):
            elements.append({
                'type': 'heading1',
                'content': line[2:].strip()
            })
            i += 1
            continue
        
        # Heading 2
        if line.startswith('## ') and not line.startswith('### '):
            elements.append({
                'type': 'heading2',
                'content': line[3:].strip()
            })
            i += 1
            continue
        
        # Heading 3
        if line.startswith('### '):
            elements.append({
                'type': 'heading3',
                'content': line[4:].strip()
            })
            i += 1
            continue
        
        # Horizontal rule
        if line == '---':
            elements.append({'type': 'hr'})
            i += 1
            continue
        
        # Editor/Reviewer lines (内容编辑丨xxx, 内容审核丨xxx)
        if line.startswith('内容编辑丨') or line.startswith('内容审核丨'):
            elements.append({
                'type': 'editor_line',
                'content': line
            })
            i += 1
            continue
        
        # Blockquote (引用块)
        if line.startswith('>'):
            quote_lines = []
            while i < len(lines) and lines[i].strip().startswith('>'):
                # Remove the > prefix and any leading whitespace
                quote_line = lines[i].strip()[1:].strip()
                if quote_line:  # Skip empty lines within quote
                    quote_lines.append(quote_line)
                i += 1
            if quote_lines:
                elements.append({
                    'type': 'blockquote',
                    'lines': quote_lines
                })
            continue
        
        # List item
        if line.startswith('- ') or line.startswith('* '):
            list_items = []
            while i < len(lines) and (lines[i].strip().startswith('- ') or lines[i].strip().startswith('* ')):
                list_items.append(lines[i].strip()[2:])
                i += 1
            elements.append({
                'type': 'list',
                'items': list_items
            })
            continue
        
        # Regular paragraph
        elements.append({
            'type': 'paragraph',
            'content': line
        })
        i += 1
    
    return elements


def process_inline_formatting(paragraph, text):
    """Process inline formatting."""
    parts = re.split(r'(\*\*.*?\*\*|__.*?__)', text)
    
    for part in parts:
        if part.startswith('**') and part.endswith('**'):
            run = paragraph.add_run(part[2:-2])
            set_chinese_font(run, bold=True)
        elif part.startswith('__') and part.endswith('__'):
            run = paragraph.add_run(part[2:-2])
            set_chinese_font(run, bold=True)
        else:
            if part:
                run = paragraph.add_run(part)
                set_chinese_font(run)


def find_image_file(image_dir, placeholder_index, description=""):
    """Find image file for a placeholder.
    
    Matching logic:
    1. If description contains a path (e.g., "charts/sales.png"), 
       look for it relative to image_dir
    2. If images are named with consistent prefix + index pattern (img01, img02...),
       match by placeholder_index
    3. Otherwise, simply return the N-th image by alphabetical order (including subdirectories)
    
    This allows flexibility - any naming convention will work as long as
    image count matches placeholder count.
    """
    if not image_dir or not os.path.exists(image_dir):
        return None
    
    import glob
    
    # Normalize path separators (handle both / and \)
    description = description.replace('\\', '/')
    
    # Case 1: Description is a path (e.g., "charts/sales.png") or a bare filename
    parts = [p for p in description.strip().split('/') if p] if description else []
    if parts:
        filename = parts[-1]

        # Try the path relative to image_dir, dropping leading segments one by
        # one (the description often repeats the image dir name, e.g.
        # "images_good/ppt_slides/slide_01.png" with image_dir=.../images_good).
        for k in range(len(parts)):
            candidate = os.path.join(image_dir, *parts[k:])
            if os.path.exists(candidate):
                return candidate

        # Fall back to matching the basename anywhere under image_dir
        candidates = glob.glob(os.path.join(image_dir, "**", filename), recursive=True)
        if candidates:
            return candidates[0]

        # Try to find with any extension
        name_without_ext = os.path.splitext(filename)[0]
        candidates = glob.glob(os.path.join(image_dir, "**", name_without_ext + ".*"), recursive=True)
        if candidates:
            return candidates[0]

    # Case 2 & 3: Get all images, sorted alphabetically (including subdirectories)
    all_images = glob.glob(os.path.join(image_dir, "**/*.jpg"), recursive=True) + \
                 glob.glob(os.path.join(image_dir, "**/*.png"), recursive=True) + \
                 glob.glob(os.path.join(image_dir, "**/*.jpeg"), recursive=True) + \
                 glob.glob(os.path.join(image_dir, "**/*.webp"), recursive=True)
    
    if not all_images:
        return None
    
    all_images.sort()
    
    # Simple index-based selection: return the N-th image
    # This works regardless of naming convention (news_001.jpg, baidu_01.jpg, etc.)
    # as long as image count matches placeholder count
    if placeholder_index <= len(all_images):
        return all_images[placeholder_index - 1]
    
    return None


def _docx_safe_image(image_path):
    """Return a path python-docx can embed, converting if needed.

    Files named .jpg are sometimes actually WEBP (common when images come
    from search/download tools); docx cannot embed WEBP, so transcode to PNG.
    Returns (path, temp_path_or_None).
    """
    try:
        from PIL import Image
    except ImportError:
        return image_path, None
    try:
        with Image.open(image_path) as im:
            fmt = im.format
            if fmt in ('JPEG', 'PNG', 'GIF', 'BMP', 'TIFF') and _docx_can_read(image_path):
                return image_path, None
            converted = im.convert('RGB')
    except Exception:
        return image_path, None
    fd, tmp_path = tempfile.mkstemp(suffix='.png')
    os.close(fd)
    converted.save(tmp_path, 'PNG')
    return tmp_path, tmp_path


def _docx_can_read(image_path):
    """True if python-docx's image signature table recognizes the file header.

    JPEGs written by some tools start with an ICC_PROFILE (APP2) segment instead
    of JFIF/Exif, which python-docx rejects with UnrecognizedImageError.
    """
    try:
        with open(image_path, 'rb') as f:
            header = f.read(32)
    except OSError:
        return False
    for offset, sig in ((0, b'\x89PNG\r\n\x1a\n'), (6, b'JFIF'), (6, b'Exif'),
                        (0, b'GIF87a'), (0, b'GIF89a'), (0, b'MM\x00*'), (0, b'II*\x00'),
                        (0, b'BM')):
        if header[offset:offset + len(sig)] == sig:
            return True
    return False


def add_image_to_doc(doc, image_path, description=""):
    """Add an image to the document with rounded corners."""
    temp_path = None
    try:
        image_path, temp_path = _docx_safe_image(image_path)
        paragraph = doc.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER

        run = paragraph.add_run()
        picture = run.add_picture(image_path, width=Inches(5.0))

        # Apply rounded corners to image
        try:
            from docx.oxml import parse_xml
            
            # Access the shape properties
            spPr = picture._inline.graphic.graphicData.pic.spPr
            
            # Create rounded rectangle geometry XML
            rounded_geom = parse_xml(
                r'<a:prstGeom xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" prst="roundRect">'
                r'<a:avLst>'
                r'<a:gd name="adj" fmla="val 5000"/>'
                r'</a:avLst>'
                r'</a:prstGeom>'
            )
            
            # Find and replace the existing geometry element
            # spPr is CT_ShapeProperties which has xPr element
            for child in spPr.getchildren():
                if child.tag.endswith('}xfrm'):
                    # Keep the transform, but we need to work with the geometry
                    pass
            
            # Alternative: Add preset geometry if not exists
            # Check if there's already a prstGeom or custGeom
            has_geom = False
            for child in spPr.getchildren():
                if 'Geom' in child.tag:
                    has_geom = True
                    # Replace it
                    spPr.remove(child)
                    break
            
            if not has_geom:
                # Insert after xfrm if exists
                xfrm_found = False
                for i, child in enumerate(spPr.getchildren()):
                    if child.tag.endswith('}xfrm'):
                        xfrm_found = True
                        # Insert after xfrm
                        spPr.insert(i + 1, rounded_geom)
                        break
                if not xfrm_found:
                    spPr.append(rounded_geom)
            else:
                # Re-add the rounded geometry
                xfrm_found = False
                for i, child in enumerate(spPr.getchildren()):
                    if child.tag.endswith('}xfrm'):
                        xfrm_found = True
                        spPr.insert(i + 1, rounded_geom)
                        break
                if not xfrm_found:
                    spPr.append(rounded_geom)
                    
        except Exception as e:
            # If rounding fails, just continue without it
            print(f"  Note: Could not apply rounded corners: {e}", file=sys.stderr)
        
        return True
    except Exception as e:
        print(f"  Warning: Could not insert image {image_path}: {e}", file=sys.stderr)
        return False
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


def add_table_to_doc(doc, headers, rows):
    """Add a table to the document."""
    try:
        # Create table
        table = doc.add_table(rows=1, cols=len(headers))
        table.style = 'Table Grid'
        
        # Add header row
        header_cells = table.rows[0].cells
        for i, header in enumerate(headers):
            para = header_cells[i].paragraphs[0]
            para.clear()
            process_inline_formatting(para, header)
            # Make header bold
            for paragraph in header_cells[i].paragraphs:
                for run in paragraph.runs:
                    run.font.bold = True
                    set_chinese_font(run, bold=True)

        # Add data rows
        for row_data in rows:
            row_cells = table.add_row().cells
            for i, cell_text in enumerate(row_data):
                if i < len(row_cells):
                    para = row_cells[i].paragraphs[0]
                    para.clear()
                    process_inline_formatting(para, cell_text)
                    # Set font for all runs (keep the bold set by inline formatting)
                    for paragraph in row_cells[i].paragraphs:
                        for run in paragraph.runs:
                            set_chinese_font(run, bold=bool(run.font.bold))
        
        # Add spacing after table
        doc.add_paragraph()
        
        return True
    except Exception as e:
        print(f"  Warning: Could not create table: {e}", file=sys.stderr)
        return False


def add_blockquote_to_doc(doc, lines):
    """Add a blockquote (引用块) to the document with left border styling."""
    try:
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn as ns_qn
        
        # Add left border (thick colored border on left side)
        para = doc.add_paragraph()
        
        # Add left border to paragraph
        pPr = para._p.get_or_add_pPr()
        pBdr = OxmlElement('w:pBdr')
        
        # Left border (thick, colored)
        left = OxmlElement('w:left')
        left.set(qn('w:val'), 'single')
        left.set(qn('w:sz'), '24')  # 2.5pt thickness (24 = 2.5 * 8)
        left.set(qn('w:space'), '12')  # 12pt space from text
        left.set(qn('w:color'), '52C41A')  # Green color
        
        pBdr.append(left)
        pPr.append(pBdr)
        
        # Set paragraph shading (light green background)
        shd = OxmlElement('w:shd')
        shd.set(qn('w:val'), 'clear')
        shd.set(qn('w:color'), 'auto')
        shd.set(qn('w:fill'), 'F6FFED')  # Light green background
        pPr.append(shd)
        
        # Add content with italic style
        full_text = ' | '.join(lines)
        run = para.add_run(full_text)
        set_chinese_font(run, font_size=11)
        run.italic = True
        
        # Add spacing after blockquote
        doc.add_paragraph()
        
        return True
    except Exception as e:
        print(f"  Warning: Could not create blockquote: {e}", file=sys.stderr)
        # Fallback: just add as regular paragraph
        para = doc.add_paragraph()
        for line in lines:
            run = para.add_run(line + '\n')
            set_chinese_font(run, font_size=11)
            run.italic = True
        return False


def create_word_document(elements, output_path, image_dir=None, title=None):
    """Create Word document from parsed elements."""
    doc = Document()
    
    # Set default font to Microsoft YaHei
    style = doc.styles['Normal']
    style.font.name = 'Microsoft YaHei'
    style.font.size = Pt(12)
    style._element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')
    
    image_index = 0
    images_inserted = 0
    images_failed = 0
    tables_created = 0
    blockquotes_created = 0
    
    for element in elements:
        elem_type = element['type']
        
        if elem_type == 'heading1':
            para = doc.add_heading(element['content'], level=1)
            for run in para.runs:
                set_chinese_font(run, font_size=18, bold=True)
        
        elif elem_type == 'heading2':
            # Add empty paragraph before heading
            doc.add_paragraph()
            
            # Create heading with 1 space before and after content (total black background)
            content = f" {element['content']} "
            para = doc.add_heading(content, level=2)
            
            # Center align the heading
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            
            # Style: black background (including spaces), white font, 1.2x font size (14*1.2=16.8), italic
            for run in para.runs:
                set_chinese_font(run, font_size=17, bold=True)
                run.font.color.rgb = RGBColor(255, 255, 255)  # White font
                run.font.highlight_color = 1  # Black background (wdBlack)
                run.font.italic = True  # Italic style
            
            # Add empty paragraph after heading
            doc.add_paragraph()
        
        elif elem_type == 'heading3':
            # Heading 3: bold, slightly larger than body text, black color
            para = doc.add_heading(element['content'], level=3)
            for run in para.runs:
                set_chinese_font(run, font_size=14, bold=True)
                run.font.color.rgb = RGBColor(0, 0, 0)  # Black font color
        
        elif elem_type == 'paragraph':
            para = doc.add_paragraph()
            process_inline_formatting(para, element['content'])
        
        elif elem_type == 'list':
            for item in element['items']:
                para = doc.add_paragraph(style='List Bullet')
                process_inline_formatting(para, item)
        
        elif elem_type == 'blockquote':
            if add_blockquote_to_doc(doc, element['lines']):
                blockquotes_created += 1
        
        elif elem_type == 'table':
            if add_table_to_doc(doc, element['headers'], element['rows']):
                tables_created += 1
        
        elif elem_type == 'image_placeholder':
            image_index += 1
            description = element['description']
            
            if image_dir:
                image_path = find_image_file(image_dir, image_index, description)
                if image_path and os.path.exists(image_path):
                    if add_image_to_doc(doc, image_path, description):
                        images_inserted += 1
                    else:
                        images_failed += 1
                else:
                    para = doc.add_paragraph()
                    run = para.add_run(f"[图片: {description}]")
                    set_chinese_font(run, font_size=10)
                    run.font.color.rgb = RGBColor(128, 128, 128)
                    run.italic = True
                    images_failed += 1
            else:
                para = doc.add_paragraph()
                run = para.add_run(f"[图片: {description}]")
                set_chinese_font(run, font_size=10)
                run.font.color.rgb = RGBColor(128, 128, 128)
                run.italic = True
        
        elif elem_type == 'editor_line':
            # Editor/Reviewer lines: bold, smaller font, single line spacing
            para = doc.add_paragraph()
            para.paragraph_format.line_spacing = 1.0  # Single line spacing
            run = para.add_run(element['content'])
            set_chinese_font(run, font_size=10, bold=True)  # Smaller font (10pt) and bold
        
        elif elem_type == 'hr':
            pass  # Skip horizontal rules
    
    doc.save(output_path)
    
    return {
        'output_path': output_path,
        'images_inserted': images_inserted,
        'images_failed': images_failed,
        'tables_created': tables_created,
        'blockquotes_created': blockquotes_created,
        'total_placeholders': image_index
    }


def convert_markdown_to_word(input_file, output_file=None, image_dir=None, title=None):
    """Convert Markdown file to Word document."""
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            md_content = f.read()
        
        if not output_file:
            output_file = input_file.rsplit('.', 1)[0] + '.docx'
        
        elements = parse_markdown(md_content)
        
        result = create_word_document(elements, output_file, image_dir, title)
        
        return {
            'success': True,
            'output_path': result['output_path'],
            'elements_count': len(elements),
            'images_inserted': result['images_inserted'],
            'images_failed': result['images_failed'],
            'tables_created': result['tables_created'],
            'blockquotes_created': result['blockquotes_created'],
            'total_placeholders': result['total_placeholders']
        }
    
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


def main():
    parser = argparse.ArgumentParser(description='Convert Markdown to Word document with images and tables')
    parser.add_argument('input', help='Input Markdown file path')
    parser.add_argument('-o', '--output', help='Output Word file path (optional)')
    parser.add_argument('-i', '--images', help='Directory containing images (optional)')
    parser.add_argument('-t', '--title', help='Document title (optional)')
    args = parser.parse_args()
    
    result = convert_markdown_to_word(args.input, args.output, args.images, args.title)
    
    if result['success']:
        print(f"✓ Successfully converted to: {result['output_path']}")
        print(f"✓ Processed {result['elements_count']} elements")
        if result['blockquotes_created'] > 0:
            print(f"✓ Blockquotes: {result['blockquotes_created']} created")
        if result['tables_created'] > 0:
            print(f"✓ Tables: {result['tables_created']} created")
        if result['total_placeholders'] > 0:
            print(f"✓ Images: {result['images_inserted']} inserted, {result['images_failed']} not found")
    else:
        print(f"✗ Error: {result['error']}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()