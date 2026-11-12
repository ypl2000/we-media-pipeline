---
name: image-searcher
description: 图片搜索技能。优先使用百度图片搜索（支持中文），同时也集成了 Pexels API 作为备选方案。支持中文搜索，能搜到名人、品牌、国内内容等 Pexels 搜不到的图片。注意：百度搜索使用爬虫技术，仅用于个人学习/研究。
triggers:
  - "百度搜图"
  - "搜索图片"
  - "下载图片"
---

# 图片搜索

**支持双引擎**：优先百度搜索，备选 Pexels API。

使用百度搜索爬取图片，支持中文关键词搜索。

**⚠️ 重要提示**：
- 此技能使用爬虫技术，非官方 API
- 仅用于个人学习/研究
- 请注意版权和法律法规
- 控制请求频率，避免被封 IP

---

## 当使用此时

- 需要搜索中文内容（名人、品牌、国内新闻等）
- Pexels/Unsplash 等图库搜不到相关内容
- 需要更本地化的图片资源
- 个人学习/研究用途

---

## 快速开始

### 基本用法

```bash
# 搜索并下载图片
python scripts/search_baidu.py "马斯克"

# 指定输出目录
python scripts/search_baidu.py "豆包 AI" -o ./my-images

# 指定下载数量
python scripts/search_baidu.py "游戏鼠标" -n 10

# 指定文件名前缀
python scripts/search_baidu.py "特斯拉" -p "tesla"

# 完整示例
python scripts/search_baidu.py "人工智能" -o ./ai-images -n 8 -p "ai"
```

### Python 调用

```python
from scripts.search_baidu import search_and_download

result = search_and_download(
    query="豆包 AI",
    output_dir="./images",
    max_results=6,
    prefix="doubao"
)

if result['success']:
    print(f"下载了 {len(result['downloaded'])} 张图片")
    for img in result['downloaded']:
        print(f"  - {img['path']}")
        print(f"    来源：{img['source']}")
else:
    print(f"失败：{result['error']}")
```

---

## 功能特点

### 搜索能力

- **中文搜索**：完美支持中文关键词
- **名人照片**：能搜到马斯克、雷军等名人
- **品牌产品**：豆包、iPhone、特斯拉等
- **国内内容**：百度图库的本地化优势
- **质量排序**：自动筛选高质量图片，优先官方/品牌来源

### 质量优化策略

| 优化项 | 处理方式 |
|--------|---------|
| 图片质量 | 自动添加「高清」「官方」等关键词搜索 |
| 来源筛选 | 优先官方、品牌、发布会等来源 |
| 时效性 | 优先近两年（当前年份和去年）的图片 |
| 低质过滤 | 过滤表情包、搞笑图、素材图等 |
| 尺寸筛选 | 优先大尺寸图片 |

### 下载功能

- **批量下载**：一次下载多张图片
- **自定义命名**：支持前缀和序号
- **自动目录**：自动创建输出文件夹
- **进度显示**：实时显示下载进度和质量评分

---

## 输出格式

### 搜索结果

```python
{
    'success': True,
    'downloaded': [
        {
            'path': './images/img_01.jpg',
            'url': 'https://...',
            'title': '图片标题',
            'source': '来源网站'
        },
        ...
    ],
    'failed': ['failed_url1', ...],
    'total_found': 15
}
```

### 文件命名

```
# 默认前缀
img_01.jpg
img_02.jpg
img_03.jpg

# 自定义前缀 "doubao"
doubao_01.jpg
doubao_02.jpg
```

---

## 脚本参考

### `scripts/search_baidu.py`

**用途**：百度搜索并下载图片

**依赖**：
```bash
pip install requests beautifulsoup4
```

**参数**：
- `query` (必需): 搜索关键词
- `-o, --output`: 输出目录（默认：./baidu_images）
- `-n, --num`: 下载数量（默认：6）
- `-p, --prefix`: 文件名前缀（默认：img）

**返回**：
```python
{
    'success': True/False,
    'downloaded': [...],
    'failed': [...],
    'error': '错误信息'  # 仅当失败时
}
```

---

## 核心函数

### `search_baidu_images(query, max_results, timeout)`

搜索图片，返回列表。

```python
from scripts.search_baidu import search_baidu_images

images = search_baidu_images("马斯克", max_results=10)
for img in images:
    print(f"URL: {img['url']}")
    print(f"标题：{img['title']}")
    print(f"来源：{img['source']}")
```

### `download_image(image_info, output_dir, filename)`

下载单张图片。

```python
from scripts.search_baidu import download_image

image_info = {
    'url': 'https://...',
    'large_url': 'https://...',
    'title': '图片标题'
}

path = download_image(image_info, './images', 'my_image.jpg')
```

### `search_and_download(query, output_dir, max_results, prefix)`

一站式搜索 + 下载。

```python
from scripts.search_baidu import search_and_download

result = search_and_download(
    query="豆包",
    output_dir="./images",
    max_results=6,
    prefix="doubao"
)
```

---

## 反爬处理

百度图片有反爬措施，脚本已内置应对：

| 反爬措施 | 应对方案 |
|---------|---------|
| User-Agent 检测 | 使用真实浏览器 UA |
| Referer 检测 | 添加正确 Referer |
| 请求频率限制 | 建议单次≤20 张 |
| IP 封禁 | 控制请求频率 |

**建议**：
- 单次请求不超过 20 张
- 多次请求间隔 1-2 秒
- 不要高频连续请求

---

## 限制

- 非官方 API，百度可能改页面结构
- 图片版权归属原作者/网站
- 商业用途需获得授权
- 可能触发反爬机制

---

## 法律风险提示

**⚠️ 重要**：

1. **版权**：下载的图片版权归属原作者或来源网站
2. **商业用途**：商用需获得授权
3. **个人隐私**：不得用于侵犯隐私
4. **违法违规**：不得用于违法目的

**建议使用场景**：
- ✅ 个人学习/研究
- ✅ 内部测试
- ✅ 教育用途

**不建议使用场景**：
- ❌ 商业出版
- ❌ 公开传播
- ❌ 侵犯版权

---

## 故障排除

### 未找到图片

```
✗ 失败：未找到图片
```

**解决**：
- 检查关键词是否正确
- 尝试更通用的关键词
- 换其他搜索引擎

### 下载失败

```
[1/6] 图片标题...
  ✗ 失败
```

**解决**：
- 检查网络连接
- 图片链接可能已失效
- 尝试其他图片

### 请求被拒绝

```
百度反爬检测：请求被拒绝
```

**解决**：
- 降低请求频率
- 等待一段时间后重试
- 检查 User-Agent 设置

---

## ⚠️ 已知问题与修复

### 1. 图片写到 `/images_good/` 而不是指定目录

**现象**：命令行 `-o "$PROJECT/images_good"` 指定了输出目录，脚本也打印了 `输出目录：/mnt/c/.../images_good`，但文件实际写到了 `/images_good/`（WSL 根目录），项目目录显示为空。

**根因**：两种可能：
- WSL 下 `$PROJECT` 变量在 cd+python 执行链中展开失败，脚本在错误 cwd 运行（当前工作目录恰好是 `/`）
- `shutil.move` 跨文件系统（temp 文件在 `/tmp`，目标在 `/mnt/c/...`）时行为异常

**现象（WSL 特例）**：`ls` 能看到文件，但 Python `os.path.exists()` 返回 False，且 `cd` 到项目目录后 `ls` 显示为空——这是 WSL 文件系统隔离造成的"幽灵文件"：文件存在于 WSL 根目录的独立挂载点，Windows 路径 `/mnt/c/...` 下的目录看不到也访问不了。

**诊断方法**：
```bash
ls -la /images_good/          # 查看 WSL 根目录是否有残留文件
ls -la /mnt/c/.../images_good/  # 查看项目目录是否真的有文件
```

**修复**：在项目目录内执行 python，不要跨目录 cd+python 链式调用：
```bash
cd "$PROJECT" && python3 "$SKILL/search_baidu.py" "关键词" -o "images_good" -n 3 -p "prefix"
```
或者直接用 Python import 调用：
```python
import sys; sys.path.insert(0, '/path/to/skills/image-searcher/scripts')
from search_baidu import search_and_download
result = search_and_download(query="Google I/O 2026", output_dir="/path/to/project/images_good", max_results=6, prefix="io")
```

### 2. GOOD_TARGET 建议≤10，避免超时（重要！）

**现象**：pipeline 配图下载时，`GOOD_TARGET = 30` 上限导致百度图片爬虫遍历大量低质量结果，单次运行超时（600s）中断，但实际已积累 ≥3 张可用图片。

**根因**：百度返回结果中约 30-40% 满足 800×600 分辨率要求。`GOOD_TARGET=30` 意味着需要遍历约 75-100 张原始结果才能凑够 30 张合格图片，耗时过长。

**调用方**：Claude workflow `.claude/workflows/run-pipeline.yml` 的 ImageDownload phase 直接调 `search_baidu.search_and_download(max_results=3)`，一次拿 3 张。保持小批量，别在这里追求 30 张。

**或者**：在下载超时时手动补救 —— 超时通常已经积累了几张可用图片，直接拿去做 Word：

```bash
# 生成 Word（确认 images_good 已积累足够图片）
python3 article-formatter/scripts/md_to_word.py   "{项目}/03_article.md"   -i "{项目}/images_good"   -o "{项目}/05_标题.docx"
```

### 3. 下载成功率低（0/2 或 1/3）

**常见原因**：
- 百度反爬（验证码页面）→ 降低请求频率，分批下载
- 图片 URL 已失效（百度图库链接有时效性）
- 分辨率过滤过严（默认 800×600）

**临时解决**：修改 `download_image` 的 `min_width=800, min_height=600` 为 `400, 300` 以接受更多图片。

### 3. Python `os.path.exists()` 显示文件不存在，但 `ls` 能看到

**这是 WSL 文件系统隔离问题**，不是脚本 bug。见上方"幽灵文件"说明。

---

## 与 Pexels 对比

| 特性 | 百度搜图 | Pexels |
|------|---------|--------|
| 中文搜索 | ✅ 优秀 | ❌ 差 |
| 名人照片 | ✅ 有 | ❌ 无 |
| 品牌产品 | ✅ 有 | ⚠️ 少 |
| 版权清晰 | ❌ 需注意 | ✅ 免费商用 |
| 稳定性 | ⚠️ 中等 | ✅ 高 |
| API 类型 | 爬虫 | 官方 API |

**建议**：
- 优先使用 Pexels（版权清晰）
- 百度搜图作为补充（Pexels 搜不到时）

---

## 未来改进

- [ ] 支持更多搜索引擎（Bing、Google）
- [ ] 图片去重功能
- [ ] 自动压缩/优化
- [ ] 批量搜索多个关键词
- [ ] 图片元数据保存

---

## 依赖安装

```bash
pip install requests beautifulsoup4
```

或：

```bash
pip install -r requirements.txt
```
