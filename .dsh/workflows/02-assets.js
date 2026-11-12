// META: {"name":"02-assets","description":"We-media-pipeline 素材线：Xiaohei 小黑配图 → Illustrate 通用配图 → Diagram 数据图 → PPT 截图 → 新闻配图下载 → Word 导出。产物全部写到输出根，同一输出目录可重跑，已有产物优先复用、缺失才生成。","phases":[{"title":"Xiaohei"},{"title":"Illustrate"},{"title":"Diagram"},{"title":"PPT"},{"title":"ImageDownload"},{"title":"Word"}]}
//
// 移植自 .claude/workflows/run-pipeline.yml 第 397–847 行（phase Xiaohei / Illustrate / Diagram / PPT / ImageDownload / Word）。
// 改写：工具名中性化（读取文件 / 写入文件 / 在 pwsh 里运行命令），去掉 Claude Code 的断点续跑与缓存机制，
// 改为对同一 OUT 可重跑（已有产物复用、缺失才生成）；产物目录、文件名、编号、返回字段与 PPT 封面规则保持不变。

// ARGS: {"topic":"","output_dir":"","article":""}
// topic: 本次项目名（必填，用作 <输出根>/<topic> 子目录）
// output_dir: 输出根目录；留空则取 config.json 的 default_output_dir
// article: 待配图的文章 Markdown；留空默认 <输出根>/03_article.md

const ARGS = args || {}
const TOPIC = String(ARGS.topic || '').trim()
if (!TOPIC) throw new Error('缺少 args.topic（本次项目名）')
const MAX_RETRIES = 3

// Resolve the project root and the output root, then make sure the topic directory exists.
// Root priority: args.output_dir > config.json "default_output_dir".
const setup = await agent(
  `确定项目根目录（仓库根）和本次流水线的输出根目录，建好目录，并确认待配图的文章文件。只做这些，不改任何内容。

1. 先确定项目根目录，在仓库里用 pwsh 运行：
   git rev-parse --show-toplevel
   把 stdout 原样记为项目根目录（完整路径）。命令失败（不在 git 仓库里）就返回 ok=false 并说明原因。

2. 如果调用方指定了输出根目录，直接用它：${ARGS.output_dir || '（未指定）'}
3. 否则运行（Windows 下用 python，路径含空格要加引号）：
   python "<项目根目录>/shared/config_loader.py" --get default_output_dir
   把 stdout 原样当作输出根目录。
4. 在根目录下创建子目录 "${TOPIC}" 和 "${TOPIC}/_work"（不存在才建，不要用 rm）。

5. 确认文章文件存在（用读取文件的方式探测；不要改它）：
   调用方指定的文章：${ARGS.article || '（未指定）'}
   未指定就用默认 <输出根目录>/03_article.md
   两者都不存在时返回 ok=false，并在 error 里写明期望的完整路径。

## 返回格式（JSON）
{ "ok": boolean, "project_root": "项目根目录完整路径", "output_root": "输出根目录完整路径", "article": "文章完整路径", "error": "错误信息（如果有）" }`,
  {
    schema: {
      type: 'object',
      properties: {
        ok: { type: 'boolean' },
        project_root: { type: 'string' },
        output_root: { type: 'string' },
        article: { type: 'string' },
        error: { type: 'string' },
      },
      required: ['ok', 'project_root', 'output_root'],
    },
    label: 'resolve-paths',
  }
)

// 项目根目录由 setup agent 用 git rev-parse 得出，仓库搬家不用改这里
const PROJECT_ROOT = String(setup.project_root || '').trim()
if (!PROJECT_ROOT) throw new Error('未能确定项目目录（git rev-parse --show-toplevel 失败）')

// guard: setup agent sometimes already appends the topic dir — don't double it
const _root = String(setup.output_root || '').trim().replace(/[\\/]+$/, '')
if (!_root) throw new Error('未能确定输出根目录' + (setup.error ? `：${setup.error}` : ''))
const OUT = _root.toLowerCase().endsWith(TOPIC.toLowerCase()) ? _root : _root + '\\' + TOPIC
log(`Output root: ${setup.output_root} -> ${OUT}`)

// guard: 产物不许写进代码仓库
const _norm = (p) => String(p).replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
const _projLower = _norm(PROJECT_ROOT)
if (_norm(OUT).startsWith(_projLower + '/') || _norm(OUT) === _projLower) {
  throw new Error(`输出目录不能位于代码仓库内: ${OUT}（仓库: ${PROJECT_ROOT}）`)
}

// 统一成正斜杠，Windows 的 python/脚本都能吃，提示词里也不用为反斜杠转义
const toPosix = (p) => String(p).replace(/\\/g, '/')
const stripTrail = (p) => String(p).replace(/[\\/]+$/, '')
const OUT_P = toPosix(OUT)
const ROOT_P = toPosix(PROJECT_ROOT)

// 产物路径（契约，不要改）
// article 取值顺序：args.article（相对路径按 OUT 解析）> setup 探测到的文章 > <OUT>/03_article.md
const _isAbsPath = (p) => /^[A-Za-z]:\//.test(p) || p.startsWith('//')
const _argArticle = toPosix(String(ARGS.article || '').trim())
const _setupArticle = toPosix(String(setup.article || '').trim())
const _resolveArticle = (p) => (_isAbsPath(p) ? p : `${OUT_P}/${p.replace(/^\.\//, '')}`)
const ARTICLE = _argArticle
  ? _resolveArticle(_argArticle)
  : _isAbsPath(_setupArticle)
    ? _setupArticle
    : `${OUT_P}/03_article.md`
const IMAGES_ALL = `${OUT_P}/images-all`
const IMAGES_GOOD = `${OUT_P}/images_good`
const WORK = `${OUT_P}/_work`
const PPT_DIR = `${IMAGES_GOOD}/ppt_slides`
const WORD_FILE = `${OUT_P}/05_文章标题.docx`

log(`Article: ${ARTICLE}`)
// 文章是后面每个阶段的前提，不存在就直接报错，不要带着空文章往下跑
if (setup.ok === false) throw new Error(`文章文件不存在或路径准备失败：${setup.error || ARTICLE}`)

// 可重跑约定，拼进每个阶段提示词
const REUSE = `## 可重跑（同一输出目录会多次运行，必须遵守）
- 先检查本阶段已有产物：**合格就复用，不要重新生成**；只补缺失或不合格的部分。
- 已有文件不要删除、不要用 rm；不要覆盖人工改过的产物。
- 返回结果里如实报告复用了哪些文件（reused 字段）。`

// ─── Phase: Xiaohei ──────────────────────────────────────────────────────────

phase('Xiaohei')
let xiaoheiResult = null

for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
  try {
    xiaoheiResult = await agent(
      `生成小黑风格定制配图（Ian xiaohei illustration），把图片路径写进 Markdown。

## 输入
- 文章: ${ARTICLE}
- 图片输出目录: ${IMAGES_GOOD}

${REUSE}
- 先看 ${IMAGES_GOOD} 下已有的 xiaohei_*.png：对应的认知点已经画过、且文章里占位符还在位，就复用那几张，只为缺的认知点补画。

## 步骤
1. 读取文件 ${ARTICLE}，分析文章，找到 4-6 个最适合用视觉表达的关键认知点
   （不要平均分段，只挑最值得配图的认知锚点；已复用的图对应的认知点不要重复挑）
2. 为每张图写**一句**英文 scene 描述（**不超过 200 字符**），只说主角在干什么、周围有什么。
   不要写风格、不要写"不要画文字"——脚本自带固定风格模板和禁字条款，你写了反而会把 prompt 撑长画歪。
3. **给每张图选一个主角（character），别让每张图都是同一个**。可选：
   line_person（火柴小人）、cat（猫）、robot（机器人）、dot（小点）、none（不要角色）。
   一篇 4-6 张图里至少用 2-3 种不同角色；scene 里的称呼要和 character 一致
   （character=cat 就写 "the cat"，不要写 "the blob"）。
4. 为每张图挑 2-4 个中文标注词（**日常常用词**，逗号分隔），后期由脚本叠到画面上。
5. 把所有图写成一个 JSON 文件（例如 ${WORK}/xiaohei_prompts.json），格式：
   [{"scene": "the cat pushes a cart along a line with four stations", "character": "cat", "labels": "写剧本,出画面", "out": "${IMAGES_GOOD}/xiaohei_01.png"}, ...]
   用写入文件的方式保存这个 JSON。
6. **画图 + 叠中文标注 + 自动检查，一条命令画完（脚本内部并发），不要自己手写 HTTP 请求**，
   在 pwsh 里运行命令：
   python "${ROOT_P}/we-media-pipeline/scripts/gen_image.py" --prompts-file "<上面那个 json 的路径>" --verify
   脚本会自己检查每张图（有没有偷偷写字、画面画的对不对），不合格的重画一遍。
7. **如果输出的 JSON 里 "failed" 数组不为空**：读每张图的 reason，把那几张的 scene 描述改得更具体更直白
   （例如把 "the cat works on AI drama" 改成 "the cat carries a stack of scripts toward a big screen"），
   改完只对这几张重跑一次脚本。最多重跑一次，还不行就用这版，别无限重试。
8. **最重要的一步**：读取文件 ${ARTICLE}，在文章中「最合适」的位置插入图片占位符：
   - 不是追加到末尾，而是找到与这张图最相关的段落位置
   - 写入一行: [[IMG: images_good/xiaohei_01.png]]
   - 如果生成多张，每张找各自的位置写一行
   - 已有占位符保留，不要重复插入
9. 用写入文件的方式覆盖保存 ${ARTICLE}

## 硬约束（实测出来的，不照做就会画歪或写错字）
- **scene 描述不超过 200 字符**，一句话说清主角在干什么，不堆砌修饰词。
- **画面里不会有任何文字**。中文标注是脚本后期用程序叠上去的，模型写汉字必有错字。
- 标注词 **最多 4 个**，每个 **2-4 个字**，用 **逗号分隔**（如: 写剧本,出画面,发布）
- 标注词必须是**日常常用词**，避开生僻字和行业术语（模型写不对「配音」「工业化」这类词）

## Shot list（不需要单独文件，直接把 placement 信息落到 Markdown 里）

## 返回格式（JSON）
{
  "success": boolean,
  "shot_count": number,
  "image_files": ["完整路径列表"],
  "placed_count": number,  // 实际写入 Markdown 的占位符数量
  "reused": ["复用的已有图片路径"],
  "error": "错误信息（如果有）"
}

如果 API key 不存在或生成失败，success=false 但不阻止流程继续。`,
      {
        schema: {
          type: 'object',
          properties: {
            success: { type: 'boolean' },
            shot_count: { type: 'number' },
            image_files: { type: 'array', items: { type: 'string' } },
            placed_count: { type: 'number' },
            reused: { type: 'array', items: { type: 'string' } },
            error: { type: 'string' },
          },
          required: ['success'],
        },
        label: 'xiaohei',
        phase: 'Xiaohei',
      }
    )

    if (xiaoheiResult?.success) {
      log(`Xiaohei done: ${xiaoheiResult.shot_count} images, ${xiaoheiResult.placed_count} placeholders written to markdown`)
    } else {
      log(`Xiaohei failed: ${xiaoheiResult?.error || 'unknown'} — continuing`)
    }
    break
  } catch (err) {
    if (attempt === MAX_RETRIES) {
      log(`Xiaohei failed after ${MAX_RETRIES} attempts: ${String(err)}`)
      break
    }
    log(`Xiaohei attempt ${attempt} failed: ${String(err)}`)
  }
}

// ─── Phase: Illustrate ───────────────────────────────────────────────────────

phase('Illustrate')
let illustrateResult = null

for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
  try {
    illustrateResult = await agent(
      `给文章补 2-3 张**通用风格**配图（跟小黑配图互补，不要重复同一个认知点），把图片路径写进 Markdown。

## 输入
- 文章: ${ARTICLE}
- 图片输出目录: ${IMAGES_GOOD}

${REUSE}
- 先看 ${IMAGES_GOOD} 下已有的 illu_*.png：已经画过、且文章里占位符还在位，就复用那几张，只为缺的段落补画。

## 可选风格（每张图选一个，同一篇文章里不要连着用同一个风格）
notion / warm / minimal / blueprint / watercolor / flat / editorial
（xiaohei 是小黑那一步用的，这里不要用）

## 步骤
1. 读取文件 ${ARTICLE}，挑 2-3 个**适合画成图解、对比、流程或概念图**的段落
   （小黑那步画的是「小黑在干嘛」，这里要画「结构、关系、对比」，两边的认知点不要重复）
2. 每张图：选一个风格 + 写**一句**英文 scene 描述（**不超过 200 字符**）+ 2-4 个中文标注词
   - scene 只说画面里有什么东西、怎么排布，别写风格本身（脚本会套模板）
   - 标注词用**日常常用词**，逗号分隔，中文标注是脚本后期贴上去的
3. 把所有图写成一个 JSON 文件 ${WORK}/illustrate_prompts.json，格式：
   [{"scene": "a three step pipeline diagram, arrows from left to right", "labels": "投喂,生成,审核", "style": "blueprint", "out": "${IMAGES_GOOD}/illu_01.png"}, ...]
   用写入文件的方式保存这个 JSON。
4. **画图 + 叠中文标注 + 自动检查，一条命令画完（脚本内部并发），不要自己手写 HTTP 请求**，
   在 pwsh 里运行命令：
   python "${ROOT_P}/we-media-pipeline/scripts/gen_image.py" --prompts-file "${WORK}/illustrate_prompts.json" --verify
5. **如果输出的 JSON 里 "failed" 数组不为空**：读每张图的 reason，把那几张的 scene 改得更具体更直白，
   只对这几张重跑一次脚本。最多重跑一次，还不行就用这版，别无限重试。
6. 读取文件 ${ARTICLE}，在文章中「最合适」的位置插入图片占位符：
   - 写入一行: [[IMG: images_good/illu_01.png]]
   - 每张图找各自最相关的段落位置插入，不要全堆在末尾，不要重复插入已有的占位符
7. 用写入文件的方式覆盖保存 ${ARTICLE}

## 硬约束
- **scene 描述不超过 200 字符**，一句话说清画面内容和布局，不堆砌修饰词。
- 标注词 **最多 4 个**，每个 **2-4 个字**，**逗号分隔**，必须是日常常用词。
- 临时文件只放 ${WORK}/，**不要用 rm -rf**（非交互模式下会永远卡住）。

## 返回格式（JSON）
{
  "success": boolean,
  "shot_count": number,
  "image_files": ["完整路径列表"],
  "placed_count": number,
  "reused": ["复用的已有图片路径"],
  "error": "错误信息（如果有）"
}

画图失败不要阻止流程继续，success=false 即可。`,
      {
        schema: {
          type: 'object',
          properties: {
            success: { type: 'boolean' },
            shot_count: { type: 'number' },
            image_files: { type: 'array', items: { type: 'string' } },
            placed_count: { type: 'number' },
            reused: { type: 'array', items: { type: 'string' } },
            error: { type: 'string' },
          },
          required: ['success'],
        },
        label: 'illustrate',
        phase: 'Illustrate',
      }
    )

    if (illustrateResult?.success) {
      log(`Illustrate done: ${illustrateResult.shot_count} images, ${illustrateResult.placed_count} placeholders written to markdown`)
    } else {
      log(`Illustrate failed: ${illustrateResult?.error || 'unknown'} — continuing`)
    }
    break
  } catch (err) {
    if (attempt === MAX_RETRIES) {
      log(`Illustrate failed after ${MAX_RETRIES} attempts: ${String(err)}`)
      break
    }
    log(`Illustrate attempt ${attempt} failed: ${String(err)}`)
  }
}

// ─── Phase: Diagram ──────────────────────────────────────────────────────────

phase('Diagram')
let diagramFiles = []

for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
  try {
    const r = await agent(
      `给文章补 1-2 张**数据图**：含具体数字的对比、拆解、漏斗或时间线。手写 HTML+SVG 再导出 PNG，
中文和数字 100% 准确。前面的配图阶段（xiaohei / illu）画不出数字，PPT 幻灯片是整页版式，
这个阶段专做正文里的精确数据图。

## 输入
- 文章: ${ARTICLE}
- 图片输出目录: ${IMAGES_GOOD}
- 技能目录: ${ROOT_P}/.claude/skills/diagram-design

${REUSE}
- 先看 ${WORK}/ 下已有的 diagram_*.html 和 ${IMAGES_GOOD}/diagram_*.png：
  已经导出、且文章里占位符还在位，就复用，不要重画；只有缺图或不合格的才补。
- 已有的 HTML 可以直接拿来改文案再用，但数字必须重新对照文章原文核对。

## 什么时候画
只画**读者需要一眼看懂**的数字关系：谁大谁小、从多少变到多少、一笔账怎么拆开、从上到下漏掉多少。
纯概念、纯情绪的段落不要画（前面阶段已经覆盖）。

## 步骤
1. 读取文件 ${ARTICLE}，挑 1-2 个**含具体数字、且 xiaohei / illu 没覆盖**的段落。
   - 一张图只讲一件事。想讲两件事就画两张。
   - 如果整篇都没有值得画的数据，直接返回 success=true、image_files=[]，不要硬凑。
2. 每张图：
   a. 定类型：横向条形对比 / 三节点流程 / 漏斗 / 时间线 / 嵌套结构（比例）/ 瀑布图（加减拆解）
   b. 复制 ${ROOT_P}/.claude/skills/diagram-design/assets/examples/ 里最接近的一张
      （bar-dense / bar-flow-wx / timeline / nested），改里面的文案和数字
   c. 详细规范见 ${ROOT_P}/.claude/skills/diagram-design/references/wechat-spec.md
      （先读取它），要点：
      - **viewBox 宽必须是 1080**，导出 PNG 宽 1080
      - **汉字不小于 40px**（= 手机端 12.6 CSS px），标题 60px，关键数字 48-56px
      - 数据元素 ≤ 4 个，文本节点 ≤ 10 个
      - 字体栈 'Microsoft YaHei', 'PingFang SC', 'Noto Sans SC', sans-serif
      - 配色 paper #f5f5f5 / ink #2d3142 / muted #4f5d75 / accent #bf4520
      - **标题必须写在 SVG 里**（export_png.py 只截 svg 元素）
   d. 用写入文件的方式保存 HTML 到 ${WORK}/diagram_01.html
3. 校验（两个脚本都要跑，输出必须都是 clean；有错就改 HTML 再跑，最多改 2 次）：
   在 pwsh 里运行命令：
   python "${ROOT_P}/.claude/skills/diagram-design/scripts/self_check.py" "${WORK}/diagram_01.html"
   python "${ROOT_P}/.claude/skills/diagram-design/scripts/check_layout.py" "${WORK}/diagram_01.html" --min-han 40
4. 导出 PNG（scale=1），在 pwsh 里运行命令：
   python "${ROOT_P}/.claude/skills/diagram-design/scripts/export_png.py" "${WORK}/diagram_01.html" "${IMAGES_GOOD}/diagram_01.png" 1
5. 读取文件 ${ARTICLE}，在**最相关的那一段**插入一行（不要堆到文末，不要重复插入）：
   [[IMG: images_good/diagram_01.png]]

## 硬约束
- 图里出现的每个数字都必须来自文章原文，**不许自己推算、换算或补充背景知识**
- **不许为了塞内容而缩字号**——删内容、删节点
- 不要动 xiaohei_*.png / illu_*.png / ppt_slides 的占位符，也不要删它们
- 临时文件只放 ${WORK}/，**不要用 rm -rf**（非交互模式下会永远卡住）

## 返回格式（JSON）
{
  "success": boolean,
  "image_files": ["完整路径列表"],
  "placed_count": number,
  "reused": ["复用的已有图片路径"],
  "error": "错误信息（如果有）"
}

画图失败不要阻止流程继续，success=false 即可。`,
      {
        schema: {
          type: 'object',
          properties: {
            success: { type: 'boolean' },
            image_files: { type: 'array', items: { type: 'string' } },
            placed_count: { type: 'number' },
            reused: { type: 'array', items: { type: 'string' } },
            error: { type: 'string' },
          },
          required: ['success'],
        },
        label: 'diagram',
        phase: 'Diagram',
      }
    )

    if (r?.success) {
      diagramFiles = r.image_files || []
      log(`Diagram done: ${diagramFiles.length} data figures, ${r.placed_count || 0} placeholders written to markdown`)
    } else {
      log(`Diagram failed: ${r?.error || 'unknown'} — continuing`)
    }
    break
  } catch (err) {
    if (attempt === MAX_RETRIES) {
      log(`Diagram failed after ${MAX_RETRIES} attempts: ${String(err)}`)
      break
    }
    log(`Diagram attempt ${attempt} failed: ${String(err)}`)
  }
}

// ─── Phase: PPT ──────────────────────────────────────────────────────────────

phase('PPT')
let pptDir = ''

for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
  try {
    const r = await agent(
      `从文章生成 HTML PPT 并截图，然后把截图路径写进 Markdown。

## 输入
- 文章: ${ARTICLE}
- 输出目录: ${OUT_P}
- 幻灯片目录: ${PPT_DIR}

${REUSE}
- 先检查 ${PPT_DIR} 下已有的 slide_*.png 和 ${ARTICLE} 里已有的 [[IMG: images_good/ppt_slides/slide_NN.png]] 占位符：
  张数一致、封面 slide_01 的占位符在正文最前（H1 标题之后），就直接复用现有结果返回，
  **不要重跑脚本**（重跑会重写占位符造成重复）。

## 步骤
1. 需要生成时，在 pwsh 里运行 Python 脚本生成 HTML PPT 并截图
   （**必须带 --slides-dir**，否则截图会落在 ${OUT_P} 根目录，和下面的占位符路径对不上；
   目录脚本自己会建，不用手动 mkdir）:
   python "${ROOT_P}/we-media-pipeline/scripts/html_ppt_chart.py" "${ARTICLE}" "${OUT_P}" --theme xiaohongshu-white --slides 6 --slides-dir "${PPT_DIR}"
2. 截图保存在 ${PPT_DIR}/slide_*.png
3. **占位符脚本已经写好了**：封面（slide_01）放在正文最前（H1 标题之后），
   其余幻灯片按内容插到对应段落——带配图的页插在它用到的那张文章插图后面，
   没配图的页插在下一个有配图的页之前（保持页序）。**不要再手动写占位符**（会重复）。
4. 校验：读取文件 ${ARTICLE}，确认 slide_01 的占位符在标题之后、其余幻灯片分散在正文各段落里
   （不再集中堆在文末），数量等于截图张数。如果一张都没截到，报错让流程停止。

## 封面规则（保留）
slide_01.png 就是公众号封面（images_good/ppt_slides/slide_01.png），不要删、不要改名、不要换图的顺序。

## 返回格式（JSON）
{
  "success": boolean,
  "slide_count": number,
  "slide_files": ["完整路径列表"],
  "placed_count": number,
  "reused": boolean,
  "error": "错误信息（如果有）"
}

如果脚本执行失败，抛出错误让流程停止。`,
      {
        schema: {
          type: 'object',
          properties: {
            success: { type: 'boolean' },
            slide_count: { type: 'number' },
            slide_files: { type: 'array', items: { type: 'string' } },
            placed_count: { type: 'number' },
            reused: { type: 'boolean' },
            error: { type: 'string' },
          },
          required: ['success'],
        },
        label: 'ppt',
        phase: 'PPT',
      }
    )

    if (r?.success) {
      pptDir = r.slide_files?.length ? r.slide_files[0].replace(/\\/g, '/').replace(/[^\/]+$/, '') : PPT_DIR
      log(`PPT done: ${r.slide_count} slides, ${r.placed_count} placeholders written to markdown`)
      break
    } else {
      throw new Error(r?.error || 'PPT generation failed')
    }
  } catch (err) {
    if (attempt === MAX_RETRIES) throw err
    log(`PPT attempt ${attempt} failed: ${String(err)}`)
  }
}

// ─── Phase: Image Download ───────────────────────────────────────────────────

phase('ImageDownload')
let imagesGoodDir = ''

for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
  try {
    const r = await agent(
      `下载新闻配图，填入文章的 [[IMG: ...]] 占位符。

## 输入
- 文章: ${ARTICLE}
- 搜索结果: ${OUT_P}/01_search_results.md
- 输出目录: ${OUT_P}

${REUSE}
- **已下载就跳过**：先检查 ${IMAGES_GOOD} 下是否已有 news_*.png，且 ${ARTICLE} 末尾「## 新闻配图」段的占位符已经全部填成图片文件名。
  两者都满足就直接返回 success=true、downloaded_count=0、good_count=已有张数、filled_count=已有张数、remain_count=0，
  在 reused=true 里说明跳过原因，**不要再跑下载脚本**。

## 步骤
1. 需要下载时，在 pwsh 里运行脚本（一条命令搞定下载、尺寸过滤、相关性判断、写占位符）：
   python "${ROOT_P}/we-media-pipeline/scripts/collect_news_images.py" --results-md "${OUT_P}/01_search_results.md" --topic "${TOPIC}" --out-dir "${IMAGES_GOOD}" --pool-dir "${IMAGES_ALL}" --article "${ARTICLE}"

   脚本做的事：取每篇搜索结果的主图（搜索结果本身是按相关性排的，主图自然贴题）
   → 丢掉 logo/头像/品牌装饰图 → 只留宽>=800 且高>=600
   → 写进 images_good/news_NNN.* → 覆盖文章末尾「## 新闻配图」段的占位符。

2. **不要自己手写下载脚本，也不要去下载 01_news_images.json 里的图**——
   那是搜索接口吐的整页图片列表，混着 logo、头像和别的稿子的图，直接用会出一堆无关配图。

3. **不要动文章里已有的 Xiaohēi、通用配图和 PPT 的占位符**，脚本只改「## 新闻配图」段。

## 硬规矩（照做，否则这一步会把整个流程卡死）
- **临时文件一律放在 ${WORK}/ 里**，不要在 ${OUT_P} 之外（比如 E:\\tmp 之类）建临时目录。
- **不要执行 rm -rf / rm -p 之类的删除命令**，非交互模式下这类命令会永远卡住。

## Baidu 图片搜索
路径: ${ROOT_P}/image-searcher/scripts/search_baidu.py
import search_baidu，然后调用 search_and_download(query=关键词, output_dir=images_good_dir, max_results=3, prefix="baidu_01")

## 返回格式（JSON）
{
  "success": boolean,
  "images_good_dir": "完整路径",
  "downloaded_count": number,
  "good_count": number,
  "filled_count": number,    // 成功填入的占位符数量
  "remain_count": number,    // 仍为文字描述的占位符数量
  "reused": boolean,
  "error": "错误信息（如果有）"
}`,
      {
        schema: {
          type: 'object',
          properties: {
            success: { type: 'boolean' },
            images_good_dir: { type: 'string' },
            downloaded_count: { type: 'number' },
            good_count: { type: 'number' },
            filled_count: { type: 'number' },
            remain_count: { type: 'number' },
            reused: { type: 'boolean' },
            error: { type: 'string' },
          },
          required: ['success'],
        },
        label: 'image-download',
        phase: 'ImageDownload',
      }
    )

    if (r?.success) {
      imagesGoodDir = r.images_good_dir || IMAGES_GOOD
      log(`ImageDownload done: ${r.good_count || 0} images, ${r.filled_count || 0} placeholders filled, ${r.remain_count || 0} remain`)
      break
    } else {
      throw new Error(r?.error || 'ImageDownload failed')
    }
  } catch (err) {
    if (attempt === MAX_RETRIES) throw err
    log(`ImageDownload attempt ${attempt} failed: ${String(err)}`)
  }
}

// ─── Phase: Word Export ──────────────────────────────────────────────────────

phase('Word')
let wordFile = ''

for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
  try {
    const r = await agent(
      `将 Markdown 转换为 Word 文档。

## 输入
- 文章: ${ARTICLE}
- 图片目录: ${imagesGoodDir || IMAGES_GOOD}
- 输出目录: ${OUT_P}

${REUSE}
- 先看 ${WORD_FILE} 是否已存在：存在且比 ${ARTICLE} 新、图片都已嵌入，就直接复用并返回该路径，不要重复转换。

## 步骤
1. 读取文件 ${ARTICLE}，提取文章标题（第一行 # 后面的内容）
2. 需要重新生成时，在 pwsh 里运行脚本:
   python "${ROOT_P}/article-formatter/scripts/md_to_word.py" "${ARTICLE}" -o "${WORD_FILE}" -i "${imagesGoodDir || IMAGES_GOOD}"
   （脚本会处理所有 [[IMG: ...]] 占位符：
    - 文件路径格式（images_good/xxx.png）→ 直接插图
    - 中文描述格式 → 在图片目录里查找匹配文件，找不到就跳过）
3. 返回 docx 文件路径

## 返回格式（JSON）
{
  "success": boolean,
  "file": "完整路径",
  "reused": boolean,
  "error": "错误信息（如果有）"
}

如果脚本执行失败，抛出错误让流程停止。`,
      {
        schema: {
          type: 'object',
          properties: {
            success: { type: 'boolean' },
            file: { type: 'string' },
            reused: { type: 'boolean' },
            error: { type: 'string' },
          },
          required: ['success'],
        },
        label: 'word',
        phase: 'Word',
      }
    )

    if (r?.success) {
      wordFile = r.file || ''
      log(`Word done: ${wordFile}`)
      break
    } else {
      throw new Error(r?.error || 'Word export failed')
    }
  } catch (err) {
    if (attempt === MAX_RETRIES) throw err
    log(`Word attempt ${attempt} failed: ${String(err)}`)
  }
}

// ─── 产出汇总 ────────────────────────────────────────────────────────────────

return {
  topic: TOPIC,
  project_root: stripTrail(toPosix(PROJECT_ROOT)),
  output_root: OUT_P,
  article: ARTICLE,
  images_good_dir: stripTrail(toPosix(imagesGoodDir || IMAGES_GOOD)),
  images_all_dir: IMAGES_ALL,
  work_dir: WORK,
  diagram_files: (diagramFiles || []).map(toPosix),
  ppt_dir: stripTrail(toPosix(pptDir || PPT_DIR)),
  ppt_cover: `${stripTrail(toPosix(pptDir || PPT_DIR))}/slide_01.png`,
  word_file: toPosix(wordFile || WORD_FILE),
  xiaohei: xiaoheiResult ? { success: !!xiaoheiResult.success, shot_count: xiaoheiResult.shot_count || 0 } : null,
  illustrate: illustrateResult ? { success: !!illustrateResult.success, shot_count: illustrateResult.shot_count || 0 } : null,
}
