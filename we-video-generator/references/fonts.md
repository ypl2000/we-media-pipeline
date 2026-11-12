# 字体配置

## 字体文件

| 用途 | Windows | WSL/Linux |
|------|---------|-----------|
| 主标题 Bold | `C:/Windows/Fonts/msyhbd.ttc` | `/mnt/c/Windows/Fonts/msyhbd.ttc` |
| 副标题 Bold | 同上 | 同上 |
| 正文 Bold | 同上 | 同上 |
| 正文 Regular | `C:/Windows/Fonts/msyh.ttc` | `/mnt/c/Windows/Fonts/msyh.ttc` |

## 识别当前环境

```python
import platform, os
ENV = 'Windows' if platform.system() == 'Windows' else ('WSL' if '/mnt/c' in os.getcwd() else 'Linux')
```

## 渲染参数与字体粗细的关系

- `bold=True` → Bold 字体文件，视觉重量比 Regular 重约 4%
- `stroke_width>0` → 描边通过 9 次文字叠加实现（双重循环），同色描边会产生模糊/重影
- 副标题有背景色块（`#FFD700` 金色）提供对比，无需描边加粗
- 主标题在深色/白色背景上需要描边（`stroke_width=4`）增强可读性

## 调试技巧

检查实际加载的字体路径：
```python
from PIL import ImageFont
font = ImageFont.truetype('C:/Windows/Fonts/msyhbd.ttc', 48)
print(font.path)  # 或 font.name
```
