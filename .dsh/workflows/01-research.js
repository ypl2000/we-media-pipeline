// META: {"name":"01-research","description":"研究线：新闻搜索 → 公众号长文 → AI 审稿（最多 5 轮重写）→ 去 AI 味。产物按 01_/02_/03_ 编号写入输出目录；可对同一输出目录重跑，已存在的产物优先读取复用，缺失才生成。不依赖运行标识或阶段缓存。","phases":[{"title":"Search"},{"title":"Article"},{"title":"Review-Article"},{"title":"DeAI"}]}
//
// ARGS（都可省略，[ ] 内是默认值）：
//   topic        必填，新闻选题；同时用作输出根目录下的项目子目录名
//   output_dir   输出根目录 [null = 未指定，改从 config.json 的 default_output_dir 读]
//   days         搜索结果的时间窗（天） [7]
//   num_results  搜索返回条数 [10]
//   style_topic  参考风格子目录名，读 reference/<style_topic>/style.md [null = reference/style-guide.md]
//   human_review 为 true 时在文章审稿前暂停并返回，等人工确认 [false]
//
// 等价字面量：
// ARGS: {"topic":"","output_dir":null,"days":7,"num_results":10,"style_topic":null,"human_review":false}
//
// 本文件只移植 run-pipeline.yml 的研究线（原第 1–396 行，四个阶段 Search / Article /
// Review-Article / DeAI）。后续阶段（Xiaohei、Illustrate……Publish）不在此文件里。

const MAX_RETRIES = 3
const MAX_REVIEW_ROUNDS = 5

// ─── args 取值：缺省用默认值 ──────────────────────────────────────────────────
const A = args || {}
const toStr = (v, d) => {
  const s = v === undefined || v === null ? '' : String(v).trim()
  return s === '' ? d : s
}
const toNum = (v, d) => {
  const n = Number(v)
  return Number.isFinite(n) && n > 0 ? n : d
}

const TOPIC = toStr(A.topic, '')
if (!TOPIC) throw new Error('缺少必需参数 topic（新闻选题）')
const OUTPUT_DIR = toStr(A.output_dir, '')
const DAYS = toNum(A.days, 7)
const NUM_RESULTS = toNum(A.num_results, 10)
const STYLE_TOPIC = toStr(A.style_topic, '')
const HUMAN_REVIEW = A.human_review === true

function humanReviewRequested(flag) {
  return flag === true
}

// Resolve the project root and the output root, then create the topic directory.
// Root priority: args.output_dir > config.json "default_output_dir".
const setup = await agent(
  `确定项目根目录（仓库根）和本次流水线的输出根目录，并建好目录。

1. 先确定项目根目录，在 pwsh 里运行命令：
   git rev-parse --show-toplevel
   把 stdout 原样记为项目根目录（完整路径）。命令失败（不在 git 仓库里）就返回错误并停止。

2. 如果调用方指定了输出根目录，直接用它：${OUTPUT_DIR || '（未指定）'}
3. 否则在 pwsh 里运行命令（Windows 下用 python，路径含空格要加引号）：
   python "<项目根目录>/shared/config_loader.py" --get default_output_dir
   把 stdout 原样当作输出根目录。
4. 在根目录下用 pwsh 创建子目录 "${TOPIC}" 和 "${TOPIC}/_work"（不存在才建，不要用 rm 删任何东西）。

## 返回格式（JSON）
{ "project_root": "项目根目录完整路径", "output_root": "输出根目录完整路径" }`,
  {
    label: 'setup',
    schema: {
      type: 'object',
      properties: {
        project_root: { type: 'string' },
        output_root: { type: 'string' },
      },
      required: ['project_root', 'output_root'],
    }
  }
)

// 项目根目录由 setup agent 用 git rev-parse 得出，仓库搬家不用改这里
const PROJECT_ROOT = String(setup.project_root || '').trim()
if (!PROJECT_ROOT) throw new Error('未能确定项目根目录（git rev-parse --show-toplevel 失败）')

// guard: setup agent sometimes already appends the topic dir — don't double it
const _root = String(setup.output_root || '').trim().replace(/[\\/]+$/, '')
if (!_root) throw new Error('未能确定输出根目录（output_dir 与 config.json 的 default_output_dir 都为空）')
const OUT = _root.toLowerCase().endsWith(TOPIC.toLowerCase()) ? _root : _root + '\\' + TOPIC
log(`Output root: ${setup.output_root} -> ${OUT}`)

// guard: 产物不许写进代码仓库
const _norm = (p) => String(p).replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
const _projLower = _norm(PROJECT_ROOT)
if (_norm(OUT).startsWith(_projLower + '/') || _norm(OUT) === _projLower) {
  throw new Error(`输出目录不能位于代码仓库内: ${OUT}（仓库: ${PROJECT_ROOT}）`)
}

// ─── Phase 1: Search ──────────────────────────────────────────────────────────

phase('Search')
let searchResult = null

for (let attempt = 1; attempt <= MAX_RETRIES && !searchResult?.success; attempt++) {
  try {
    searchResult = await agent(
      `在 ${OUT} 目录下执行新闻搜索，保存结果到 01_search_results.md。

## 可重跑（重要）
先检查 ${OUT}/01_search_results.md 是否存在且内容非空：
- 已存在且非空 → 读取该文件复用，跳过下面的搜索命令，不要覆盖、不要删；
- 缺失或为空 → 在 pwsh 里运行下面的命令重新生成。

## 任务
调用搜索脚本拿新闻，保存 markdown 格式结果。

**不要自己手写 HTTP 请求去调 Metaso/Tavily** —— 脚本里已经处理好了 provider 选择、
日期过滤和图片 URL 导出，手写会绕过这些逻辑。

## 步骤
1. 在 pwsh 里运行命令（Windows 下用 python，路径含空格要加引号）：
   python "${PROJECT_ROOT}\\news-searcher\\scripts\\search_news.py" "${TOPIC}" -d ${DAYS} -n ${NUM_RESULTS} -f markdown -o "${OUT}\\01_search_results.md"

2. 脚本会写出两个文件：
   - ${OUT}/01_search_results.md（搜索结果）
   - ${OUT}/01_news_images.json（图片 URL 数组，没有就是 []）

3. 读取文件 01_search_results.md 的内容，作为 research_content。

## 脚本的失败语义（重要）
- 脚本会在本地按日期过滤掉超出 DAYS 的旧结果。**Metaso 的 recency_days 参数是失效的**，
  所以过滤是唯一有效的时效保证。
- 近 DAYS 天内不足 3 条时脚本会失败退出，返回 success=false。
  **绝对不许改宽搜索词、减小天数窗口、或拿旧结果凑数。**

## 返回格式（JSON）
{
  "success": boolean,
  "output_dir": "${OUT}",
  "research_file": "完整路径",
  "research_content": "01_search_results.md 文件内容（string）",
  "results_count": number,
  "images_count": number,
  "error": "错误信息（如果有）"
}

如果搜索失败（success=false），抛出错误让流程停止。`,
      {
        label: 'search',
        schema: {
          type: 'object',
          properties: {
            success: { type: 'boolean' },
            output_dir: { type: 'string' },
            research_file: { type: 'string' },
            research_content: { type: 'string' },
            results_count: { type: 'number' },
            images_count: { type: 'number' },
          },
          required: ['success', 'output_dir', 'research_file'],
        }
      }
    )
  } catch (err) {
    if (attempt === MAX_RETRIES) throw err
    log(`Search attempt ${attempt} failed: ${String(err)}`)
  }
}

if (!searchResult?.success) throw new Error('Search failed: ' + (searchResult?.error || 'unknown'))

const stylePath = STYLE_TOPIC
  ? PROJECT_ROOT + '\\reference\\' + STYLE_TOPIC + '\\style.md'
  : PROJECT_ROOT + '\\reference\\style-guide.md'
log(`Search done: ${searchResult.results_count} articles, ${searchResult.images_count} images`)

// ─── Phase 2: Article Generation ─────────────────────────────────────────────

phase('Article')
let articleFile = '', articleContent = ''

for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
  try {
    const r = await agent(
      `读取新闻搜索结果，生成微信公众号文章，保存到 02_raw_article.md。

## 可重跑（重要）
先检查 ${OUT}/02_raw_article.md 是否存在且内容非空：
- 已存在且非空 → 读取文件复用，不要重新生成、不要覆盖；
- 缺失或为空 → 按下面的要求生成并用写入文件的方式保存。

## 输入
- 研究资料: ${searchResult.research_content}（01_search_results.md 全文）
- 风格指南: ${stylePath}

## 文章要求
1. 根据 style-guide 生成，标题必须有悬念或冲突
2. 结构: 标题 → 正文（## 章节）→ ## 写在最后
3. **不需要写任何图片占位符**，图片由后续步骤处理
4. **不要写任何 {{...}} 模板标记**（如 {{chart:...}}），没有渲染器会处理它们
5. 字数 2500-3500 中文字符
6. 对话风格但专业，第一人称视角
7. **正文第一句不能复述标题**：标题是问句时，开篇直接给具体事件/数据/场景，不要把标题的问题再抛一遍

## 输出
写入文件 ${OUT}/02_raw_article.md

## 返回格式（JSON）
{
  "success": boolean,
  "article_file": "完整路径",
  "article_content": "文件完整内容（string）"
}

如果生成失败，抛出错误让流程停止。`,
      {
        label: 'article',
        schema: {
          type: 'object',
          properties: {
            success: { type: 'boolean' },
            article_file: { type: 'string' },
            article_content: { type: 'string' },
          },
          required: ['success', 'article_file'],
        }
      }
    )

    if (r?.success) {
      articleFile = r.article_file
      articleContent = r.article_content
      log(`Article generated: ${articleFile} (${(articleContent || '').length} chars)`)
      break
    } else {
      throw new Error(r.error || 'Article generation failed')
    }
  } catch (err) {
    if (attempt === MAX_RETRIES) throw err
    log(`Article attempt ${attempt} failed: ${String(err)}`)
  }
}

// ─── Review Point 1 ─────────────────────────────────────────────────────────────
phase('Review-Article')
log(`Article ready: ${articleFile} (${(articleContent || '').length} chars)`)

if (humanReviewRequested(HUMAN_REVIEW)) {
  log(`\n========== 人工审查点 ==========`)
  log(`文章: ${articleFile}`)
  log(`开头预览:\n${(articleContent || '').slice(0, 600)}`)
  log(`===============================`)
  log(`workflow 已暂停。确认无误后带 human_review: false 重新运行以继续。`)
  return {
    success: false,
    awaiting: 'article-review',
    output_dir: OUT,
    article_file: articleFile,
    preview: (articleContent || '').slice(0, 1200),
  }
}

for (let rewrite = 1; rewrite <= MAX_REVIEW_ROUNDS; rewrite++) {
  let verdict
  try {
    verdict = await agent(
      `审查这篇文章，判断是否可以直接进入配图和导出环节。

## 待审文章
${articleFile}

## 审查标准（任一不合格就打回）
1. 字数 2500-3500 中文字符，明显不足或超标 → 打回
2. 标题有悬念或冲突 → 打回
3. 有「## 写在最后」→ 缺则打回
4. 正文有 ## 分节，节与节之间不是重复表达 → 打回
5. 事实与搜索结果一致，没有编造的数字、时间、公司名 → 打回
6. 通篇没有 AI 味开场白 → 打回
7. 正文第一句在复述标题（把标题的问句/结论又说一遍）→ 打回

## 返回格式（JSON）
{
  "approved": boolean,
  "issues": ["具体问题1", "具体问题2"],
  "severity": "high" | "medium" | "low"
}

approved=false 时 issues 必须是可直接执行的重写指令。`,
      {
        label: `review-${rewrite}`,
        schema: {
          type: 'object',
          properties: {
            approved: { type: 'boolean' },
            issues: { type: 'array', items: { type: 'string' } },
            severity: { type: 'string' },
          },
          required: ['approved', 'issues'],
        }
      }
    )
  } catch (err) {
    log(`Review round ${rewrite} failed: ${String(err)} — proceeding with current article`)
    break
  }

  if (verdict?.approved) {
    log(`Review passed (round ${rewrite})`)
    break
  }

  log(`Review round ${rewrite} rejected (${verdict?.severity || 'unknown'}): ${(verdict?.issues || ['（未返回具体意见）']).join('; ')}`)
  if (rewrite === MAX_REVIEW_ROUNDS) {
    log(`Review still failing after ${MAX_REVIEW_ROUNDS} rounds — proceeding with current article`)
    break
  }

  let fixed
  try {
    fixed = await agent(
      `按审查意见重写这篇文章，覆盖保存。

## 审查意见（必须逐条修掉）
${(verdict?.issues || ['（未返回具体意见）']).map((issue, i) => `${i + 1}. ${issue}`).join('\n')}

## 原文
${articleFile}

## 约束
- 保留原有的搜索素材和事实，不要编造
- 字数保持 2500-3500 中文字符
- 改完用写入文件的方式覆盖保存原文件

## 返回格式（JSON）
{
  "success": boolean,
  "file": "<完整路径>",
  "content": "改写后的完整文章内容"
}`,
      {
        label: `rewrite-${rewrite}`,
        schema: {
          type: 'object',
          properties: {
            success: { type: 'boolean' },
            file: { type: 'string' },
            content: { type: 'string' },
          },
          required: ['success', 'file', 'content'],
        }
      }
    )
  } catch (err) {
    log(`Rewrite round ${rewrite} failed: ${String(err)} — proceeding with current article`)
    break
  }

  if (fixed?.success) {
    articleFile = fixed.file
    articleContent = fixed.content
    log(`Rewritten: ${articleFile} (${(articleContent || '').length} chars)`)
  }
}

// ─── Phase 3: DeAI ────────────────────────────────────────────────────────────

phase('DeAI')
let deaiFile = '', deaiContent = ''

for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
  try {
    const r = await agent(
      `读取文章，去除 AI 写作模式，保存到 03_article.md。

## 可重跑（重要）
先检查 ${OUT}/03_article.md 是否存在且内容非空：
- 已存在且非空 → 读取文件复用，不要重新生成、不要覆盖；
- 缺失或为空 → 按下面的规则处理并写入文件。

## 输入
- 文章: ${articleFile}
- 输出目录: ${OUT}

## 去AI味规则
1. 删除开头铺垫短语
2. 删除强调套路
3. 替换商业黑话为直白语言
4. 删除所有副词（特别是 -ly 结尾的词）
5. 删除填充短语
6. 避免二元对比结构
7. 避免戏剧性碎片化短句
8. 避免"人们"，用"你"或具体人
9. 避免被动语态
10. 保持 2500+ 中文字符
11. **禁止修改或替换 [[IMG:...]] 占位符**，原样保留。
12. 保留标题不变，正文第一句不得变成标题的复述

## 输出
写入文件 ${OUT}/03_article.md

## 返回格式（JSON）
{
  "success": boolean,
  "file": "完整路径",
  "content": "文件完整内容（string）"
}

如果 LLM API 错误，抛出错误让流程停止。`,
      {
        label: 'deai',
        schema: {
          type: 'object',
          properties: {
            success: { type: 'boolean' },
            file: { type: 'string' },
            content: { type: 'string' },
          },
          required: ['success', 'file'],
        }
      }
    )

    if (r?.success) {
      deaiFile = r.file
      deaiContent = r.content
      log(`DeAI done: ${deaiFile} (${(deaiContent || '').length} chars)`)
      break
    } else {
      throw new Error(r.error || 'DeAI failed')
    }
  } catch (err) {
    if (attempt === MAX_RETRIES) throw err
    log(`DeAI attempt ${attempt} failed: ${String(err)}`)
  }
}

log(`Research line done: ${OUT}`)
return {
  success: true,
  output_dir: OUT,
  project_root: PROJECT_ROOT,
  research_file: String(searchResult.research_file || '').trim() || OUT + '\\01_search_results.md',
  article_file: articleFile,
  deai_file: deaiFile,
  deai_chars: (deaiContent || '').length,
}
