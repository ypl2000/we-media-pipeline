// META: {"name":"03-video","description":"We-media-pipeline 视频线：06_content.json 摘要 → 机器校验 → 06_storyboard.json 分镜（R1–R9 由 validate_storyboard.py 实跑把关，最多 2 轮重写）→ 只给旁白的五问闸门 → 时长路由（<=12s 跑本地模板渲染，>12s 只写 08_eac_handoff.json 不渲染）。","phases":[{"title":"Summarize"},{"title":"Review-Summary"},{"title":"Storyboard"},{"title":"Review-Storyboard"},{"title":"Video"}]}
// ARGS: {"topic":"必填，产物子目录名","duration":30,"video_engine":"hf","human_review":false,"output_dir":"","project_root":"","article":"","voice":"mambo-zh","content_file":"","storyboard_file":""}
//
// 本文件是 .claude/workflows/run-pipeline.yml 第 848–1661 行（Summarize / Review-Summary /
// Storyboard / Review-Storyboard / Video 五段）的 DSH 移植。规则与契约以
// Docs/storyboard-spec.md 的 R1–R9 为准，此处不改口径：
//   - 06_content.json 三段结构与标题字数限制（main_title ≤10、sub_title ≤12、每段 30–60 汉字）
//   - 分镜硬规则：首镜 hook 且不以数字开头、4–6 镜、相邻 visual_type 不同且相邻不得都没人、
//     字数预算 5.5 字/秒 ±8%、Σ duration_s = 顶层 duration_s（±0.3）、上屏单行 ≤24 汉字、禁 zoom-out
//   - Review-Storyboard 只把 narration 交给 critic，五问齐了才放行，最多 2 轮重写
//   - Video 的时长路由：<=12s 调 we-video-generator/scripts/run_video_generator_hf.py；
//     >12s 只产出 08_eac_handoff.json，绝不假装渲染过
//
// 相对原版的改动（刻意为之）：
//   1. 工具名中性化：原稿里点名某个读写工具、点名 shell 的措辞，统一改成
//      「读取文件 / 写入文件 / 在 pwsh 里运行命令」。
//   2. 去掉 run-id 续跑与阶段缓存：改成「先读盘，已有且合规就复用」，重跑安全、结果可预期。
//   3. 原文只在 JS 里复刻了一份校验逻辑，脚本自己从不执行校验器。本版补上机器闸门：
//      每次 agent 写完 06_storyboard.json，都由一个 agent 在 pwsh 里真的跑一次
//      `python we-media-pipeline/scripts/validate_storyboard.py <json>`，PASS 才往下走，
//      FAIL 就把校验器的失败行原样交给重写 agent（最多 2 轮）。
//      workflow 运行时没有本地 exec 能力，所以「跑命令」这一步委托给带工具的 agent，
//      但闸门判定只看它回传的退出码与校验器原始输出，不看 JS 里那份启发式复刻。
//   4. handoff 不再由 workflow 手写 JSON：改成在 pwsh 里依次跑
//      `python we-media-pipeline/scripts/build_handoff.py <分镜>` 生成、再加 `--verify` 校验，
//      最后回读确认 clips 数量 / 末镜 start+duration / storyboard_sha256。
//      运镜映射、clip 拼装、哈希比对只存在于脚本里，workflow 不保留第二份实现。

const A = args || {}

const TOPIC = String(A.topic || '').trim() || 'untitled'
const DURATION = Number(A.duration) > 0 ? Math.round(Number(A.duration)) : 30
const VIDEO_ENGINE = String(A.video_engine || 'hf').trim().toLowerCase() === 'legacy' ? 'legacy' : 'hf'
const HUMAN_REVIEW = A.human_review === true
const VOICE = String(A.voice || '').trim() || 'mambo-zh'
const MAX_RETRIES = 3

// 分镜硬规则常量（口径：Docs/storyboard-spec.md §3）
const VO_CHARS_PER_SEC = 5.5
const STORYBOARD_TARGET_CHARS = Math.round(DURATION * VO_CHARS_PER_SEC)
// 5.5 字/秒 ±8% → [5.06, 5.94] 字/秒
const STORYBOARD_CHAR_FLOOR = Math.round(STORYBOARD_TARGET_CHARS * 0.92)
const STORYBOARD_CHAR_CEIL = Math.round(STORYBOARD_TARGET_CHARS * 1.08)
// <=12s 走模板线，>12s（13s 起）走 EAC，按 12 秒一刀切，不留灰区
const STORYBOARD_ROUTE = DURATION <= 12 ? 'template' : 'eac'
// 机器闸门打回后最多再重写几轮
const STORYBOARD_MAX_REWRITES = 2

const _cnCount = (s) => (String(s || '').match(/[\u4e00-\u9fff]/g) || []).length
// 视频号标题/描述按「汉字算 1、数字和英文各算半个」折算长度
const _weightedLen = (s) => [...String(s || '')].reduce((n, ch) => {
  if (/[\u4e00-\u9fff]/.test(ch)) return n + 1
  if (/\s/.test(ch)) return n
  return n + 0.5
}, 0)
const _short = (s, n = 36) => {
  const t = String(s || '').replace(/\s+/g, ' ').trim()
  const chars = [...t]
  return chars.length > n ? chars.slice(0, n).join('') + '…' : t
}
const _norm = (p) => String(p).replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()

// ─── 0. 路径解析（原稿第 30–73 行）──────────────────────────────────────────
//
// 项目根目录用 git rev-parse --show-toplevel 拿，输出根目录用 config_loader 的
// default_output_dir；两者都能从 args 直接给，给了就不再问 agent（重跑更快也更可预期）。

const _resolvePaths = async () => {
  const givenProject = String(A.project_root || '').trim()
  const givenOut = String(A.output_dir || '').trim()
  if (givenProject && givenOut) {
    log(`路径来自 args：project_root=${givenProject}，output_dir=${givenOut}`)
    return { project_root: givenProject, output_root: givenOut }
  }
  const r = await agent(
    `确定项目根目录（仓库根）和本次流水线的输出根目录，并建好目录。

1. 先确定项目根目录，在 pwsh 里运行（工作目录设成仓库根或其任意子目录）：
   git rev-parse --show-toplevel
   把 stdout 原样记为项目根目录（完整路径）。命令失败（不在 git 仓库里）就返回错误并停止。
   本次调用方已指定的项目根目录：${givenProject || '（未指定）'}
2. 本次调用方已指定的输出根目录：${givenOut || '（未指定）'}
3. 没指定输出根目录就运行（路径含空格要加引号）：
   python "<项目根目录>/shared/config_loader.py" --get default_output_dir
   把 stdout 原样当作输出根目录。
4. 在输出根目录下创建子目录 "${TOPIC}" 和 "${TOPIC}\\_work"（不存在才建，不要用 rm）。

## 返回格式（JSON）
{ "project_root": "项目根目录完整路径", "output_root": "输出根目录完整路径" }`,
    {
      schema: {
        type: 'object',
        properties: {
          project_root: { type: 'string' },
          output_root: { type: 'string' },
        },
        required: ['project_root', 'output_root'],
      },
      label: '解析项目路径',
      phase: 'Summarize',
    }
  )
  return {
    project_root: String(givenProject || r?.project_root || '').trim(),
    output_root: String(givenOut || r?.output_root || '').trim(),
  }
}

const _paths = await _resolvePaths()
const PROJECT_ROOT = String(_paths.project_root || '').trim()
if (!PROJECT_ROOT) throw new Error('未能确定项目根目录（git rev-parse --show-toplevel 失败）')

// guard: setup agent 有时已经把 topic 目录拼在 output_root 后面 —— 别拼两遍
const _root = String(_paths.output_root || '').trim().replace(/[\\/]+$/, '')
if (!_root) throw new Error('未能确定输出根目录（output_dir 与 config.json 的 default_output_dir 都为空）')
const OUT = _root.toLowerCase().endsWith(TOPIC.toLowerCase()) ? _root : _root + '\\' + TOPIC
log(`Output root: ${_root} -> ${OUT}`)

// guard: 产物不许写进代码仓库
const _projLower = _norm(PROJECT_ROOT)
if (_norm(OUT).startsWith(_projLower + '/') || _norm(OUT) === _projLower) {
  throw new Error(`输出目录不能位于代码仓库内: ${OUT}（仓库: ${PROJECT_ROOT}）`)
}

const VALIDATOR = `${PROJECT_ROOT}\\we-media-pipeline\\scripts\\validate_storyboard.py`
// handoff 的生成与校验同一份实现，workflow 只调它，不在 JS 里另写一份
const BUILD_HANDOFF = `${PROJECT_ROOT}\\we-media-pipeline\\scripts\\build_handoff.py`
const CONTENT_FILE = String(A.content_file || '').trim() || `${OUT}\\06_content.json`
const STORYBOARD_FILE = String(A.storyboard_file || '').trim() || `${OUT}\\06_storyboard.json`
// 文章在上一段（Xiaohei/DeAI）产出，固定叫 03_article.md；可用 args.article 覆盖
const deaiFile = String(A.article || '').trim() || `${OUT}\\03_article.md`
const EAC_HANDOFF_FILE = `${OUT}\\08_eac_handoff.json`

log(`项目根: ${PROJECT_ROOT}`)
log(`文章: ${deaiFile}`)
log(`分镜目标时长: ${DURATION}s，路由: ${STORYBOARD_ROUTE}，旁白预算: ${STORYBOARD_CHAR_FLOOR}-${STORYBOARD_CHAR_CEIL} 汉字`)

// ─── 0.1 只读探针：可重跑靠它，不靠 run-id 缓存 ─────────────────────────────

const _probeJson = async (file, what, phaseName) => {
  try {
    const r = await agent(
      `只读检查一个 JSON 文件：存在且是合法 JSON 就原样返回解析结果。

## 文件
${file}

## 规则
- 读取该文件；不存在、读不了、或不是合法 JSON → exists=false，不要创建、不要修改。
- 返回的 json 必须原样来自文件：不要补字段、不要改写、不要用你自己的理解重写内容。
- 文件顶层不是 JSON 对象也算 exists=false。

## 返回格式（JSON）
{ "exists": boolean, "json": object }`,
      {
        schema: {
          type: 'object',
          properties: {
            exists: { type: 'boolean' },
            json: { type: 'object' },
          },
          required: ['exists'],
        },
        label: `读取 ${what}`,
        phase: phaseName,
      }
    )
    if (r?.exists && r.json && typeof r.json === 'object') return r.json
  } catch (err) {
    log(`读取 ${file} 失败（按不存在处理）：${String(err)}`)
  }
  return null
}

// ─── 0.2 机器闸门：真的跑一次 validate_storyboard.py ────────────────────────
//
// 返回 { pass, exitCode, failLines, raw }。pass 只看校验器的退出码与首行，
// JS 里那份 checkStoryboard() 只用来补充提示，不参与放行判定。

const _runStoryboardValidator = async (file) => {
  const cmd = `python "${VALIDATOR}" "${file}"`
  let r = null
  try {
    r = await agent(
      `在 pwsh 里运行下面这一条命令，把结果原样回传。只跑这一条，不要改文件、不要跳步骤、不要用别的方式校验。

## 命令
${cmd}

## 规则
- 用 pwsh 执行；工作目录用仓库根目录（脚本只读，不写任何文件）。
- 把 stdout、stderr 与退出码原样回传，一个字符都不要改写或总结。
- 退出码 0 表示 PASS，非 0 表示 FAIL（脚本本身就是这个约定）。
- 不要因为看到 FAIL 就自己去修 ${file}：修稿是下一步重写 agent 的事。

## 返回格式（JSON）
{ "exit_code": number, "stdout": "原样 stdout", "stderr": "原样 stderr" }`,
      {
        schema: {
          type: 'object',
          properties: {
            exit_code: { type: 'number' },
            stdout: { type: 'string' },
            stderr: { type: 'string' },
          },
          required: ['exit_code', 'stdout'],
        },
        label: 'validate_storyboard.py',
        phase: 'Storyboard',
      }
    )
  } catch (err) {
    log(`机器校验执行失败（${_short(String(err), 60)}）—— 这一轮按未通过处理`)
    return { pass: false, exitCode: null, failLines: [`机器校验没能跑起来：${_short(String(err), 120)}`], raw: '' }
  }

  const raw = String(r?.stdout || '')
  const exitCode = typeof r?.exit_code === 'number' ? r.exit_code : null
  const lines = raw.split(/\r?\n/).map((s) => s.trim()).filter(Boolean)
  const first = lines[0] || ''
  // PASS/FAIL 既要退出码对，也要首行是 PASS：任一对不上都不放行
  const pass = exitCode === 0 && /^PASS\b/i.test(first)
  // 首行的「FAIL」只是总标记，真正要改的是后面那些「R3 FAIL ...」行
  const failLines = lines
    .filter((s, idx) => !(idx === 0 && /^(PASS|FAIL)\b/i.test(s)))
    .filter((s) => /\bFAIL\b/.test(s))
  if (String(r?.stderr || '').trim()) log(`校验器 stderr: ${_short(String(r.stderr), 200)}`)
  if (!failLines.length && !pass) failLines.push(`校验器没有给出 PASS（exit=${exitCode}，首行「${_short(first, 80)}」）`)
  return { pass, exitCode, failLines, raw: `${raw}\n${String(r?.stderr || '')}` }
}

// ─── 0.3 JS 侧预检（保留原稿契约，仅用于提前给出可读的修改提示）────────────

const _checkContent = (data) => {
  const problems = []
  if (!data || typeof data !== 'object') return ['content.json 不是 JSON 对象']
  const sections = Array.isArray(data.text_sections) ? data.text_sections : []
  if (!String(data.main_title || '').trim()) problems.push('main_title 为空')
  if ([...(data.main_title || '')].length > 10) problems.push('main_title 超过 10 字')
  if ([...(data.sub_title || '')].length > 12) problems.push('sub_title 超过 12 字')
  if (sections.length !== 3) problems.push(`text_sections 应为 3 段，实际 ${sections.length} 段`)
  sections.forEach((s, i) => {
    const n = [...String(s || '')].length
    if (n < 30 || n > 60) problems.push(`text_sections[${i}] 长度 ${n} 字，超出 30-60 区间`)
  })
  if (!(Array.isArray(data.images) ? data.images : []).length) problems.push('images 为空，视频生成器会失败')
  return problems
}

function checkStoryboard(sb, duration, route) {
  const problems = []
  if (!sb || typeof sb !== 'object') return ['未返回可解析的 storyboard 对象']

  if (!String(sb.title || '').trim()) problems.push('title 为空（内部标题，不念不上屏）')
  if (_weightedLen(sb.publish_title) === 0) problems.push('publish_title 为空')
  else if (_weightedLen(sb.publish_title) > 15) {
    problems.push(`publish_title 折算 ${_weightedLen(sb.publish_title)} 字，超过 15（数字/英文各算半个）`)
  }
  if (_weightedLen(sb.publish_desc) === 0) problems.push('publish_desc 为空')
  else if (_weightedLen(sb.publish_desc) > 20) {
    problems.push(`publish_desc 折算 ${_weightedLen(sb.publish_desc)} 字，超过 20（数字/英文各算半个）`)
  }
  if (String(sb.voice || '') !== VOICE) {
    problems.push(`voice 必须是 ${VOICE}，实际 ${sb.voice || '空'}`)
  }
  if (Number(sb.duration_s) !== Number(duration)) {
    problems.push(`duration_s 必须是 ${duration}，实际 ${sb.duration_s}`)
  }
  const expectedRoute = route || (Number(duration) <= 12 ? 'template' : 'eac')
  if (String(sb.route || '') !== expectedRoute) {
    problems.push(`route 必须是 ${expectedRoute}（${duration}s），实际 ${sb.route || '空'}`)
  }

  const scenes = Array.isArray(sb.scenes) ? sb.scenes : []
  if (scenes.length < 4) problems.push(`scenes 至少 4 镜，实际 ${scenes.length} 镜`)
  if (scenes.length > 6) problems.push(`scenes 最多 6 镜，实际 ${scenes.length} 镜`)
  if (scenes.length && scenes[0]?.role !== 'hook') problems.push('第 1 镜 role 必须是 hook')
  if (scenes.length && scenes[scenes.length - 1]?.role !== 'outro') problems.push('最后一镜 role 必须是 outro')

  const firstNarration = String(scenes[0]?.narration || '').trimStart()
  if (scenes.length && /^[0-9０-９%％]/.test(firstNarration)) {
    problems.push('第 1 镜 narration 不许以数字或百分号开头，先交代人和场景（R1）')
  }

  const ids = []
  let totalDuration = 0
  let totalChars = 0
  for (let i = 0; i < scenes.length; i++) {
    const scene = scenes[i]
    const label = `第 ${i + 1} 镜`
    const id = String(scene?.id || '').trim()
    ids.push(id)
    if (!/^[a-z][a-z0-9_]*$/.test(id)) problems.push(`${label} id 必须是小写英文（可带数字/下划线），实际「${id}」`)
    if (!['hook', 'body', 'outro'].includes(String(scene?.role || ''))) {
      problems.push(`${label} role 必须是 hook/body/outro`)
    }
    const visualType = String(scene?.visual_type || '')
    if (!['event', 'order', 'chart', 'statement'].includes(visualType)) {
      problems.push(`${label} visual_type 必须是 event/order/chart/statement`)
    }
    if (i > 0 && String(scene?.visual_type || '') === String(scenes[i - 1]?.visual_type || '')) {
      problems.push(`${label} 和上一镜同类 visual_type（${visualType}），相邻两镜必须不同（R6）`)
    }
    // chart / statement 都是「没人」的画面，相邻两镜都不许没人（R6 第二条）
    if (i > 0) {
      const noHuman = ['chart', 'statement']
      if (noHuman.includes(visualType) && noHuman.includes(String(scenes[i - 1]?.visual_type || ''))) {
        problems.push(`${label} 和上一镜都是「没人」画面（chart/statement），中间要插一镜 event/order（R6）`)
      }
    }

    const sceneDuration = Number(scene?.duration_s)
    if (!Number.isFinite(sceneDuration) || sceneDuration <= 0) {
      problems.push(`${label} duration_s 必须是正数`)
    } else {
      totalDuration += sceneDuration
    }

    const narration = String(scene?.narration || '')
    if (!narration.trim()) {
      problems.push(`${label} narration 为空`)
    } else {
      const chars = _cnCount(narration)
      totalChars += chars
      if (chars < 6) problems.push(`${label} narration 只有 ${chars} 个汉字，至少 6 个`)
      if (/[0-9０-９%％]/.test(narration)) {
        problems.push(`${label} narration 含阿拉伯数字或百分号，必须写中文念法（R4）`)
      }
      if (/[A-Za-z]{2,}/.test(narration)) {
        problems.push(`${label} narration 含英文串，念不出来；英文名/版本号放到 visual/elements（R4）`)
      }
    }
    if (!String(scene?.visual || '').trim()) problems.push(`${label} visual 为空（要一句话讲这屏画什么）`)

    // R8：上屏单行 ≤24 个汉字
    const elementItems = String(scene?.elements || '').split(/[,，、/|]/).map((s) => s.trim()).filter(Boolean)
    elementItems.forEach((item) => {
      const n = _cnCount(item)
      if (n > 24) problems.push(`${label} elements 有一行 ${n} 个汉字，超过 24（R8）：${_short(item)}`)
    })

    // R9：运镜只允许 zoom-in / pan-*，amount 0.01~0.5
    const motion = scene?.motion
    if (motion && typeof motion === 'object') {
      const motionType = String(motion.type || '')
      if (!['zoom-in', 'pan-left', 'pan-right', 'pan-up', 'pan-down'].includes(motionType)) {
        problems.push(`${label} motion.type「${motionType}」不合法，禁用 zoom-out（R9）`)
      }
      const amount = Number(motion.amount)
      if (motion.amount !== undefined && (!Number.isFinite(amount) || amount < 0.01 || amount > 0.5)) {
        problems.push(`${label} motion.amount 必须在 0.01~0.5 之间（R9）`)
      }
    }
  }

  if (ids.some((id) => !id)) {
    // 上面已逐条报过，这里不重复
  } else {
    if (new Set(ids).size !== ids.length) problems.push('scenes[].id 有重复')
    const prefixes = ids.map((id) => id.slice(0, 2))
    if (new Set(prefixes).size !== prefixes.length) problems.push('scenes[].id 的前 2 个字母有重复')
  }

  if (scenes.length && Math.abs(totalDuration - Number(duration)) > 0.3) {
    problems.push(`scene.duration_s 合计 ${totalDuration.toFixed(2)}，必须等于 duration_s ${duration}（±0.3）`)
  }

  // 每 3 镜至少 1 镜有人有动作（event/order），否则整段像 PPT 翻页
  for (let i = 2; i < scenes.length; i++) {
    const windowTypes = scenes.slice(i - 2, i + 1).map((s) => String(s?.visual_type || ''))
    if (!windowTypes.includes('event') && !windowTypes.includes('order')) {
      problems.push(`第 ${i - 1}-${i + 1} 镜连续 3 镜没有 event/order`)
    }
  }

  if (totalChars < STORYBOARD_CHAR_FLOOR || totalChars > STORYBOARD_CHAR_CEIL) {
    problems.push(`旁白总汉字数 ${totalChars}，应落在 ${STORYBOARD_CHAR_FLOOR}-${STORYBOARD_CHAR_CEIL}（${duration}s × 5.5 字/秒 ±8%）`)
  }

  const facts = Array.isArray(sb.facts) ? sb.facts : []
  facts.forEach((f, i) => {
    const claim = String(f?.claim || '')
    const source = String(f?.source || '')
    if (/[0-9０-９]/.test(claim) && !/^https?:\/\//i.test(source)) {
      problems.push(`facts[${i}] 的 claim「${claim}」带数字但没有 http(s) 来源`)
    }
  })
  return problems
}

// ═══════════════════════════════════════════════════════════════════════════
// Phase 1: Summarize（06_content.json）
// ═══════════════════════════════════════════════════════════════════════════

phase('Summarize')

const contentSchema = {
  type: 'object',
  properties: {
    success: { type: 'boolean' },
    file: { type: 'string' },
    content: { type: 'string' },
    main_title: { type: 'string' },
    sub_title: { type: 'string' },
    text_sections: { type: 'array', items: { type: 'string' } },
    images: { type: 'array', items: { type: 'string' } },
  },
  required: ['success', 'file', 'content'],
}

const buildContentPrompt = (problems) => `读取文章，生成 content.json，并写入 ${CONTENT_FILE}。
${problems?.length ? `\n## 上一版被打回的原因（逐条修掉，别只改措辞）\n${problems.map((p, i) => `${i + 1}. ${p}`).join('\n')}\n` : ''}
## 输入
- 文章文件: ${deaiFile}
- 图片目录: ${OUT}\\images_good

## content.json 格式（严格，text_sections 每段 30-60 个汉字）
{
  "main_title": "大标题（≤10 字，含数字）",
  "sub_title": "副标题（≤12 字）",
  "text_sections": ["第一段", "第二段", "第三段"],
  "outro_text": "关注 AI不够酷｜获取更多AI资讯",
  "images": ["图片路径1", "图片路径2", "图片路径3"]
}

## 规则（程序逐条校验，超了就打回）
1. main_title ≤10 个汉字（数字也算 1 个），这是硬限制。
2. sub_title ≤12 个字符。
3. text_sections 固定 3 段，**每段 30-60 个汉字**（不含标点）。
4. images 写完整绝对路径，**优先用真实新闻图** ${OUT}\\images_good\\news_*.jpg（视频画面用照片最自然）；
   不足 3 张再用 xiaohei_*.png、illu_*.png 补。
   **不要用 diagram_*.png 和 ppt_slides\\slide_*.png**（数据图、整页幻灯片放进视频没法看）。
5. 先在 pwsh 里列一下图片目录，按真实文件名挑，不要凭空写路径。

## 输出
把这份 JSON 写入 ${CONTENT_FILE}（UTF-8，2 空格缩进），写完再读取一遍确认是合法 JSON。

## 返回格式（JSON）
{
  "success": true,
  "file": "${CONTENT_FILE}",
  "content": "JSON 文件内容（string，原样）",
  "main_title": "string",
  "sub_title": "string",
  "text_sections": ["...", "...", "..."],
  "images": ["...", "...", "..."]
}

如果读文章或写文件失败，抛出错误让流程停止。`

let contentFile = CONTENT_FILE
let contentData = null

// 可重跑：已有 06_content.json 且过校验就直接复用，不重写、不依赖任何缓存
const _reusedContent = await _probeJson(CONTENT_FILE, '06_content.json', 'Summarize')
if (_reusedContent && _checkContent(_reusedContent).length === 0) {
  contentData = _reusedContent
  log(`复用已有 ${CONTENT_FILE}（main_title="${contentData.main_title}"，${(contentData.text_sections || []).length} 段，${(contentData.images || []).length} 张图）`)
} else {
  if (_reusedContent) log(`已有 ${CONTENT_FILE} 不合规（${_checkContent(_reusedContent).join('；')}），重写`)
  for (let attempt = 1; attempt <= MAX_RETRIES && !contentData; attempt++) {
    try {
      const r = await agent(buildContentPrompt(_reusedContent ? _checkContent(_reusedContent) : []), {
        schema: contentSchema,
        label: `写 06_content.json（第 ${attempt} 次）`,
        phase: 'Summarize',
      })
      if (!r?.success) throw new Error(r?.error || 'Summarize 未成功')
      contentFile = String(r.file || CONTENT_FILE).trim() || CONTENT_FILE
      let parsed = null
      try { parsed = JSON.parse(r.content || '{}') } catch { parsed = null }
      if (!parsed || typeof parsed !== 'object') parsed = _reusedContent
      const problems = _checkContent(parsed)
      if (problems.length) throw new Error(`content.json 不合规：${problems.join('；')}`)
      contentData = parsed
      log(`Summarize done: ${contentFile}`)
      log(`  main_title: ${contentData.main_title}`)
      log(`  text_sections: ${(contentData.text_sections || []).length} 段`)
    } catch (err) {
      if (attempt === MAX_RETRIES) throw err
      log(`Summarize 第 ${attempt} 次失败：${String(err)}`)
    }
  }
}
if (!contentData) throw new Error('Summarize 没有产出可用的 06_content.json')

// ═══════════════════════════════════════════════════════════════════════════
// Phase 2: Review-Summary（content.json 硬校验 + 一次自动修复）
// ═══════════════════════════════════════════════════════════════════════════

phase('Review-Summary')
log(`content.json ready: ${contentFile}`)

let _contentProblems = _checkContent(contentData)

if (_contentProblems.length) {
  log(`content.json 校验失败（${_contentProblems.length} 项），尝试自动修复...`)
  const fixed = await agent(buildContentPrompt(_contentProblems), {
    schema: contentSchema,
    label: '修复 06_content.json',
    phase: 'Review-Summary',
  })
  if (!fixed?.success) throw new Error('自动修复失败：agent 未成功写入 06_content.json')

  contentFile = String(fixed.file || contentFile).trim() || contentFile
  let parsed = null
  try { parsed = JSON.parse(fixed.content || '{}') } catch { parsed = null }
  if (parsed && typeof parsed === 'object') contentData = parsed

  const stillBad = _checkContent(contentData)
  if (stillBad.length) throw new Error('自动修复后仍有问题：\n  - ' + stillBad.join('\n  - '))
  _contentProblems = []
  log(`content.json 已修复`)
}

const _sections = Array.isArray(contentData.text_sections) ? contentData.text_sections : []
const _images = Array.isArray(contentData.images) ? contentData.images.filter(Boolean) : []
log(`content.json OK: main_title="${contentData.main_title}", ${_sections.length} 段, ${_images.length} 张图`)

if (HUMAN_REVIEW) {
  log(`\n========== 人工审查点 ==========`)
  log(`content.json: ${contentFile}`)
  log(`main_title: ${contentData.main_title}`)
  log(`sub_title: ${contentData.sub_title}`)
  log(`text_sections: ${_sections.length} 段`)
  log(`images: ${_images.length} 张`)
  log(`===============================`)
  log(`workflow 已暂停。确认无误后带 human_review: false 重新运行以继续。`)
  return {
    success: false,
    awaiting: 'summary-review',
    output_dir: OUT,
    content_file: contentFile,
    content: contentData,
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// Phase 3: Storyboard（06_storyboard.json）
// ═══════════════════════════════════════════════════════════════════════════
//
// 把 06_content.json 的「摘要」升级成 06_storyboard.json 的「分镜」。
// 字段与判定口径以 Docs/storyboard-spec.md 为准（scenes[] / narration / visual_type）。
// 06_content.json 的既有契约不动（模板线还要用它）。
// 硬规则同时写进 prompt、JSON schema 和机器闸门，三处口径一致。

phase('Storyboard')

const storyboardSchema = {
  type: 'object',
  properties: {
    success: { type: 'boolean' },
    file: { type: 'string' },
    title: { type: 'string' },
    publish_title: { type: 'string' },
    publish_desc: { type: 'string' },
    voice: { type: 'string' },
    rate: { type: 'string' },
    duration_s: { type: 'number' },
    route: { type: 'string', enum: ['template', 'eac'] },
    units_per_sec: { type: 'number' },
    scenes: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          role: { type: 'string', enum: ['hook', 'body', 'outro'] },
          visual_type: { type: 'string', enum: ['event', 'order', 'chart', 'statement'] },
          duration_s: { type: 'number' },
          narration: { type: 'string' },
          visual: { type: 'string' },
          elements: { type: 'string' },
          motion: {
            type: 'object',
            properties: {
              type: { type: 'string', enum: ['zoom-in', 'pan-left', 'pan-right', 'pan-up', 'pan-down'] },
              amount: { type: 'number' },
            },
            required: ['type'],
          },
        },
        required: ['id', 'role', 'visual_type', 'duration_s', 'narration', 'visual'],
      },
    },
    facts: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          claim: { type: 'string' },
          source: { type: 'string' },
          verified: { type: 'boolean' },
        },
        required: ['claim'],
      },
    },
  },
  required: ['success', 'file', 'title', 'publish_title', 'publish_desc', 'voice', 'duration_s', 'route', 'scenes'],
}

const _sbRepairBlock = (problems) => (problems?.length
  ? `\n## 上一版被打回的原因（逐条修掉，别只改措辞）\n${problems.map((p, i) => `${i + 1}. ${p}`).join('\n')}\n\n必须覆盖 ${STORYBOARD_FILE} 重写整份分镜，不要只返回补丁。\n`
  : '')

const buildStoryboardPrompt = (problems) => `读取文章和已有摘要，写一条 ${DURATION} 秒竖版短视频的分镜，保存到 ${STORYBOARD_FILE}。
${_sbRepairBlock(problems)}
## 输入
- 文章: ${deaiFile}（事实、人名、时间都以它为准）
- 已有摘要: ${CONTENT_FILE}（main_title / sub_title / text_sections 的语气和标题要与它一致）
- 目标时长: ${DURATION} 秒
- 旁白语速: 曼波中文实测 5.5 字/秒，全片旁白总汉字数应 ≈ ${STORYBOARD_TARGET_CHARS} 字
  （允许 ±8%，即 ${STORYBOARD_CHAR_FLOOR}-${STORYBOARD_CHAR_CEIL} 个汉字；标点不计入汉字数）

## 先读再写
1. 先读取 ${CONTENT_FILE} 和 ${deaiFile}。
2. 扫文章里「有人在做一件事」的段落（测试员、工程师、用户在干嘛），把这种场面排成首镜。
3. 拆成 4-6 镜：首镜 hook，中间 body，末镜 outro；每镜只讲一件事。
4. 五问要齐：谁 / 什么时候 / 发生了什么 / 为什么 / 所以呢。

## 字段（严格按 Docs/storyboard-spec.md 的 schema）
{
  "title": "内部标题，不念、不上屏",
  "publish_title": "视频号标题，≤15 个汉字（数字/英文各算半个）",
  "publish_desc": "视频号描述，≤20 个汉字，补标题没说完的钩子",
  "voice": "${VOICE}",
  "rate": "+0%",
  "duration_s": ${DURATION},
  "route": "${STORYBOARD_ROUTE}",
  "units_per_sec": 5.5,
  "scenes": [
    {
      "id": "hook",
      "role": "hook",
      "visual_type": "event",
      "duration_s": 6,
      "narration": "纯中文口播，数字写中文念法",
      "visual": "一句话讲这屏画什么：元素、位置、画面上具体写哪几个标签",
      "elements": "上屏文字，逗号分隔（可选）",
      "motion": { "type": "zoom-in", "amount": 0.06 }
    }
  ],
  "facts": [
    { "claim": "百分之四十一点三", "source": "https://…", "verified": true }
  ]
}

## 硬规则（validate_storyboard.py 会实跑逐条校验，不合规直接打回重写）
1. scenes 固定 4-6 镜；首镜 role=hook，末镜 role=outro，中间 role=body（R7）。
2. 首镜 narration 第一句必须交代「谁 + 什么时候 + 发生了什么」，不许以数字或百分号开头（R1）。
3. 每镜 narration 至少 6 个汉字，必须是完整口播句；禁止纯数字句。
4. narration 里零阿拉伯数字、零百分号、零英文串，全部写中文念法（R4）：
   百分之四十一点三；二零二六年；人工智能；双子座四号碳。
   英文名、版本号、上屏标签只能放到 visual / elements（画面文字 ≠ 旁白）。
5. 总汉字数 ≈ duration_s × 5.5，必须落在 ${STORYBOARD_CHAR_FLOOR}-${STORYBOARD_CHAR_CEIL}，超出打回（R3）；
   每镜 narration ≈ 本镜 duration_s × 5.5（0.8-1.2 倍），别让某一镜画面空转或字挤成一团。
6. 每镜 duration_s > 0，所有 scene.duration_s 加起来必须等于 ${DURATION}（±0.3，R7）。
7. 禁止相邻两镜 visual_type 相同；相邻两镜也不许都是「没人」画面（chart/statement）；
   任意连续 3 镜至少 1 镜是 event/order（有人、有动作）（R6）。
8. facts 里每个带数字的 claim 必须给 http(s) 来源；文章里找不到出处的数字，不要写进 narration（R4）。
9. 至少一镜给出因果（含「因为/是因为/之所以」），末镜给出落点（含「所以/以后/接着」），
   并且落点要落到读者身上（R2/R2b/R2c）：末镜要有「你/你们」，或写清读者今天能做的动作。
10. publish_title ≤15 字、publish_desc ≤20 字；voice 必须是 ${VOICE}；route 填 ${STORYBOARD_ROUTE}。
11. elements 每一项（画面上的一行字）≤24 个汉字（R8，1080 宽 / 40px 一行约 24 字，超了会被截断）。
12. motion 只用 zoom-in / pan-left / pan-right / pan-up / pan-down，**禁用 zoom-out**；amount 0.01~0.5（R9）。

## visual_type 怎么选
- event: 有人在做一件事（优先，最像真实视频）
- order: 流程 / 步骤 / 时间顺序
- chart: 只有一个数字关系要看清（少用，别和相邻镜撞类型）
- statement: 一句结论（少用，别和相邻镜撞类型）

## 写完后按 R1-R9 自查
- [ ] 首镜 role=hook，第一句有主语、有时间，不以数字开头（R1）
- [ ] 五问都能在旁白里找到出处，末镜有「所以呢」且落到读者身上（R2/R2c）
- [ ] 句间有承接，全片不用「另外/此外」堆事实（R2b）
- [ ] 总汉字数落在 ${STORYBOARD_CHAR_FLOOR}-${STORYBOARD_CHAR_CEIL}（R3）
- [ ] 旁白零阿拉伯数字、零百分号、零英文串（R4）
- [ ] route=${STORYBOARD_ROUTE}，镜头时长加总等于 ${DURATION} 秒（R5）
- [ ] 相邻 visual_type 不同，相邻不得都没人，每 3 镜有人有动作（R6）
- [ ] 4-6 镜、首 hook 末 outro、id 唯一且前 2 字母不重复（R7）
- [ ] 上屏每行 ≤24 汉字（R8）
- [ ] 运镜只有 zoom-in / pan，没有 zoom-out（R9）

## 输出
把这份 JSON 写入 ${STORYBOARD_FILE}（UTF-8，2 空格缩进），写完再读取一遍确认是合法 JSON。

## 返回格式（JSON）
{ "success": true, "file": "${STORYBOARD_FILE}", "title": "string", "publish_title": "string", "publish_desc": "string", "voice": "${VOICE}", "rate": "+0%", "duration_s": ${DURATION}, "route": "${STORYBOARD_ROUTE}", "units_per_sec": 5.5, "scenes": [...], "facts": [...] }

如果文件写失败，抛出错误让流程停止。`

let storyboardFile = STORYBOARD_FILE
let storyboardData = null
let storyboardProblems = []
let storyboardValidator = null

// 可重跑：已有分镜先过同一道机器闸门，PASS 且时长对得上就复用（五问闸门照跑，不跳过）
const _reusedSb = await _probeJson(STORYBOARD_FILE, '06_storyboard.json', 'Storyboard')
if (_reusedSb && Number(_reusedSb.duration_s) === DURATION) {
  const v = await _runStoryboardValidator(STORYBOARD_FILE)
  storyboardValidator = v
  if (v.pass) {
    storyboardData = _reusedSb
    storyboardFile = STORYBOARD_FILE
    log(`复用已有 ${STORYBOARD_FILE}（validate_storyboard.py PASS，${(storyboardData.scenes || []).length} 镜）`)
  } else {
    log(`已有 ${STORYBOARD_FILE} 没过机器校验（${v.failLines.length} 行 FAIL），重写`)
  }
} else if (_reusedSb) {
  log(`已有 ${STORYBOARD_FILE} 的 duration_s=${_reusedSb.duration_s} 与目标 ${DURATION}s 不符，重写`)
}

// 盘上那份分镜没被复用时，把它的问题带进第一次重写（机器闸门的 FAIL 行优先）
let _sbRoundProblems = []
if (_reusedSb) {
  _sbRoundProblems = checkStoryboard(_reusedSb, DURATION, STORYBOARD_ROUTE)
  if (storyboardValidator && !storyboardValidator.pass) {
    _sbRoundProblems = (storyboardValidator.failLines || []).concat(_sbRoundProblems)
  }
}

// 机器闸门 PASS 才收工：FAIL 就把校验器的失败行原样交给重写 agent，最多 STORYBOARD_MAX_REWRITES 轮
let _sbMachinePass = Boolean(storyboardData)

for (let round = 0; round <= STORYBOARD_MAX_REWRITES && !_sbMachinePass; round++) {
  const isRewrite = round > 0 || Boolean(_reusedSb)
  try {
    const r = await agent(buildStoryboardPrompt(isRewrite ? _sbRoundProblems : []), {
      schema: storyboardSchema,
      label: round === 0 ? '写 06_storyboard.json' : `按机器校验打回重写分镜（第 ${round} 轮）`,
      phase: 'Storyboard',
    })
    if (!r?.success) throw new Error(r?.error || 'Storyboard 生成未成功')

    const targetFile = String(r.file || STORYBOARD_FILE).trim() || STORYBOARD_FILE
    storyboardData = r
    storyboardFile = targetFile

    // ★ 硬要求：agent 写完之后，由脚本真的跑一次机器校验，PASS 才往下走
    const v = await _runStoryboardValidator(targetFile)
    storyboardValidator = v
    const jsProblems = checkStoryboard(r, DURATION, STORYBOARD_ROUTE)

    if (v.pass) {
      _sbMachinePass = true
      storyboardProblems = []
      _sbRoundProblems = []
      log(`Storyboard done: ${targetFile}（${DURATION}s，${(r.scenes || []).length} 镜，${_cnCount((r.scenes || []).map((s) => s.narration).join(''))} 字，route=${STORYBOARD_ROUTE}）`)
      log(`validate_storyboard.py: PASS（exit=${v.exitCode}）`)
      if (jsProblems.length) log(`JS 预检另有提示（不阻塞）：${jsProblems.join('；')}`)
      break
    }

    storyboardProblems = v.failLines.length ? v.failLines : jsProblems
    _sbRoundProblems = storyboardProblems.length ? storyboardProblems : jsProblems
    log(`validate_storyboard.py: FAIL（第 ${round + 1} 次写稿，${storyboardProblems.length} 行）：${storyboardProblems.slice(0, 4).join('；') || '（无具体行）'}`)
    if (jsProblems.length) log(`JS 预检同时报出：${jsProblems.slice(0, 4).join('；')}`)

    if (round === STORYBOARD_MAX_REWRITES) {
      log(`重写 ${STORYBOARD_MAX_REWRITES} 轮后机器校验仍 FAIL，保留文件交给 Review-Storyboard 继续审（risk 会写进 handoff.review）`)
    }
  } catch (err) {
    if (round === STORYBOARD_MAX_REWRITES) {
      log(`Storyboard 在 ${STORYBOARD_MAX_REWRITES + 1} 次尝试后仍未成功：${String(err)} —— Video 若拿不到可用分镜会回退模板线`)
      break
    }
    log(`Storyboard 第 ${round + 1} 次写稿失败：${String(err)}`)
    _sbRoundProblems = [ `上一轮写稿失败：${_short(String(err), 120)}` ]
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// Phase 4: Review-Storyboard（只审旁白五问，最多 2 轮重写）
// ═══════════════════════════════════════════════════════════════════════════
//
// 只把 narration 交给 critic：没有画面、没有图、没有标题。旁白自己讲不清楚，
// 就不能靠画面脑补。任一问答不上就打回重写；重写后照样要过机器闸门。

phase('Review-Storyboard')

let storyboardApproved = false
const SB_REVIEW_MAX_ROUNDS = 2
const _sbMissingLabels = { who: '谁', when: '什么时候', what: '发生了什么', why: '为什么', so_what: '所以呢', relevance: '这跟我有什么关系' }
// 观众答不上时 critic 应原样回 unknown；这里把常见同义写法一并当缺口，避免「答不上」被当成有效答案
const _sbUnknownValues = new Set(['', 'unknown', 'n/a', 'na', 'none', 'null', 'undefined', '答不上', '答不上来', '不知道', '不确定', '无法回答', '未知', '空'])
const _sbIsUnknown = (v) => {
  const s = String(v ?? '').trim().toLowerCase()
  return !s || _sbUnknownValues.has(s) || /^(答不上|答不出|不确定|不知道)/.test(s)
}

const storyboardReviewSchema = {
  type: 'object',
  properties: {
    pass: { type: 'boolean' },
    verdict: { type: 'string', enum: ['clear', 'partly', 'unclear'] },
    why: { type: 'string' },
    confusing: { type: 'array', items: { type: 'string' } },
    answers: {
      type: 'object',
      properties: {
        who: { type: 'string' },
        when: { type: 'string' },
        what: { type: 'string' },
        why: { type: 'string' },
        so_what: { type: 'string' },
        relevance: { type: 'string' },
      },
      required: ['who', 'when', 'what', 'why', 'so_what', 'relevance'],
    },
    missing: { type: 'array', items: { type: 'string' } },
    issues: { type: 'array', items: { type: 'string' } },
  },
  required: ['pass', 'verdict', 'why', 'confusing', 'answers', 'missing', 'issues'],
}

const sbReviewPrompt = (narrationText) => `你是短视频观众。下面只有这条片子的旁白文本：没有画面、没有图、没有标题。
不要脑补，只根据这些文字回答五个问题，再判断「听完能不能讲清楚」。

## 旁白文本
${narrationText}

## 五问（每题用一句具体的话回答；答不上就原样写 unknown，不要编）
1. 谁：这件事说的是谁？
2. 什么时候：发生在什么时候？
3. 发生了什么：具体做了什么、出了什么结果？
4. 为什么：为什么会这样？
5. 所以呢：观众听完该记住什么、该做什么？

## 落点追问（R2c，单独回答，不并进上面五问）
- 这跟我有什么关系：观众自己能用上什么、会不会被影响、要不要做什么？只写到机构能力、行业判断、厂商战略 = unknown。

## 判定
- 五问里有任何一问答不上、或答出来的只是空泛套话 → pass=false，把对应键放进 missing。
- 末镜的「所以呢」只写到机构能力、行业判断、厂商战略，没有落到读者身上（R2c）→ pass=false，missing 里加 so_what。
- 句与句之间靠「另外 / 此外 / 同时 / 还有」把事实并排堆起来，没有因果/转折/递进/指代承接（R2b）→ pass=false，写进 issues。
- 五问都能从旁白里直接答出来 → pass=true，missing 为空数组。
- 不许把标题/摘要/你的背景知识算进答案：旁白没说的就是没讲清楚。
- verdict 只能填 clear / partly / unclear：五问答得上、句间有承接、末镜落点在读者身上，观众不用回头想 → "clear"；
  信息基本齐但表达有歧义（术语多、数字密、要倒回去想才懂）→ "partly"；关键信息缺失或前后矛盾 → "unclear"。
- **只有 verdict="clear" 才算通过**：pass=true 但 verdict 不是 clear，一律按不通过处理。
- why：一句话说明为什么给这个 verdict；confusing：列出观众会卡住、会追问的具体位置（具体到第几镜的哪句话），没有就空数组。

## 返回格式（JSON）
{
  "pass": boolean,
  "verdict": "clear" | "partly" | "unclear",
  "why": "为什么给这个 verdict",
  "confusing": ["观众会卡住/追问的具体位置"],
  "answers": { "who": "...", "when": "...", "what": "...", "why": "...", "so_what": "...", "relevance": "..." },
  "missing": ["why"],
  "issues": ["具体缺什么信息、应该补在哪一镜"]
}`

const sbRewritePrompt = (round, answers, missing, issues, hardProblems) => `观众只看了旁白，说这条片子没讲清楚。请重写 ${STORYBOARD_FILE}，把缺的要素补进 narration。

## 这是第 ${round} 轮重写（最多 ${SB_REVIEW_MAX_ROUNDS} 轮）
## 五问缺口（补进具体某一镜的 narration，不要只在结尾喊口号）
${missing.length ? missing.map((m) => {
  const label = _sbMissingLabels[m] || m
  const ans = String(answers?.[m] || '').trim()
  return `- 缺「${label}」${ans ? `：观众听到的是「${_short(ans)}」，信息不够` : '：旁白里没有能直接答出的内容'}`
}).join('\n') : '- （critic 没有标注具体缺口，按下面的意见补）'}

## critic 的具体意见
${(issues.length ? issues : ['（无）']).map((s, i) => `${i + 1}. ${s}`).join('\n')}

## 硬规则问题（validate_storyboard.py 校验出来的，必须一起修）
${(hardProblems.length ? hardProblems : ['（无）']).map((s, i) => `${i + 1}. ${s}`).join('\n')}

${buildStoryboardPrompt(hardProblems)}
`

if (!storyboardData) {
  log(`Review-Storyboard skipped：没有可审的分镜（Video 将回退模板线）`)
} else {
  let pendingHardProblems = storyboardProblems || []
  // 最后一轮 critic 的结论：handoff 里必须写清 verdict 与 confusing，未达 clear 不许当通过
  let finalVerdict = ''
  let finalWhy = ''
  let finalConfusing = []

  for (let round = 0; round <= SB_REVIEW_MAX_ROUNDS; round++) {
    const scenes = Array.isArray(storyboardData.scenes) ? storyboardData.scenes : []
    // 只给 narration：不传画面、不传图片、不传标题，避免 critic 靠画面或标题脑补
    const narrationText = scenes.map((s, i) => `${i + 1}. ${String(s?.narration || '')}`).join('\n')

    let verdict = null
    try {
      verdict = await agent(sbReviewPrompt(narrationText), {
        schema: storyboardReviewSchema,
        label: `五问闸门（第 ${round + 1} 次）`,
        phase: 'Review-Storyboard',
      })
    } catch (err) {
      log(`Review-Storyboard 审查调用失败：${String(err)} —— 不放行，按未达 clear 处理`)
      break
    }

    const answers = verdict?.answers || {}
    const missing = Array.isArray(verdict?.missing) ? verdict.missing : []
    const issues = Array.isArray(verdict?.issues) ? verdict.issues : []
    const confusing = (Array.isArray(verdict?.confusing) ? verdict.confusing : [])
      .map((s) => String(s ?? '').trim())
      .filter(Boolean)
    const whyText = String(verdict?.why || '').trim()
    const verdictLabel = String(verdict?.verdict || '').trim().toLowerCase()
    const passFlag = verdict?.pass === true

    // 收紧后的放行条件（三条同时成立）：
    //   ① verdict === 'clear'；② pass === true；③ 为什么 / 所以呢 / 这跟我有什么关系都不是 unknown
    const unknownAnswers = ['why', 'so_what', 'relevance'].filter((k) => _sbIsUnknown(answers[k]))
    const cleared = passFlag && verdictLabel === 'clear' && unknownAnswers.length === 0
    finalVerdict = verdictLabel
    finalWhy = whyText
    finalConfusing = confusing

    // 硬规则以机器闸门的实跑结果为准
    const hardV = await _runStoryboardValidator(storyboardFile)
    storyboardValidator = hardV
    const hardProblems = hardV.pass ? [] : (hardV.failLines.length ? hardV.failLines : pendingHardProblems)

    if (cleared && hardV.pass) {
      storyboardApproved = true
      log(`Review-Storyboard 通过：verdict=clear，pass=true；谁=${_short(answers.who)}；什么时候=${_short(answers.when)}；发生了什么=${_short(answers.what)}；为什么=${_short(answers.why)}；所以呢=${_short(answers.so_what)}；这跟我有什么关系=${_short(answers.relevance)}`)
      break
    }

    const isLastRound = round === SB_REVIEW_MAX_ROUNDS
    if (!cleared) {
      log(`第 ${round + 1} 轮 verdict=${verdictLabel || 'unknown'}，未达 clear，${isLastRound ? '止损（不进入 Handoff）' : '重写'}；缺失：${missing.map((m) => _sbMissingLabels[m] || m).join('、') || '（未标注）'}${unknownAnswers.length ? `；五问缺口：${unknownAnswers.map((k) => _sbMissingLabels[k] || k).join('、')}` : ''}；confusing：${confusing.length ? confusing.join('；') : '（无）'}`)
    } else {
      log(`Review-Storyboard：verdict=clear，但机器校验还有 ${hardProblems.length} 行 FAIL，${isLastRound ? '带风险继续' : '打回重写'}：${hardProblems.slice(0, 4).join('；') || '（无具体行）'}`)
    }

    // 重写轮数沿用上限；两轮仍不到 clear 就抛错止损，绝不把 partly 当通过往下走
    if (!cleared && isLastRound) {
      throw new Error(`Review-Storyboard 重写 ${SB_REVIEW_MAX_ROUNDS} 轮后 verdict=${finalVerdict || 'unknown'}，未达 clear，止损：不进入 Handoff。confusing=${finalConfusing.join('；') || '（无）'}`)
    }
    if (isLastRound) break

    let rewritten = null
    // confusing 是观众卡住的具体位置，和 issues 一起交给重写 agent
    const rewriteIssues = confusing.length
      ? issues.concat(confusing.map((c) => `观众卡在这里：${c}`))
      : issues
    try {
      rewritten = await agent(sbRewritePrompt(round + 1, answers, missing, rewriteIssues, hardProblems), {
        schema: storyboardSchema,
        label: `按五问打回重写分镜（第 ${round + 1} 轮）`,
        phase: 'Review-Storyboard',
      })
    } catch (err) {
      log(`Storyboard 重写第 ${round + 1} 轮失败：${String(err)} —— 停止重写`)
      break
    }
    if (!rewritten?.success) {
      log(`Storyboard 重写第 ${round + 1} 轮未成功：${rewritten?.error || 'unknown'} —— 停止重写`)
      break
    }
    storyboardData = rewritten
    storyboardFile = String(rewritten.file || storyboardFile).trim() || storyboardFile

    // 重写后照样重新实跑一次机器校验
    const reV = await _runStoryboardValidator(storyboardFile)
    storyboardValidator = reV
    pendingHardProblems = reV.pass ? [] : reV.failLines
    if (pendingHardProblems.length) log(`重写后机器校验仍有 ${pendingHardProblems.length} 行 FAIL：${pendingHardProblems.slice(0, 4).join('；')}`)
    else log(`重写后机器校验 PASS（exit=${reV.exitCode}）`)
  }
  // 以「盘上这份分镜最后一次实跑校验的结论」为准，别把已修好的旧 FAIL 行带进 handoff
  storyboardProblems = (storyboardValidator && !storyboardValidator.pass)
    ? (storyboardValidator.failLines || [])
    : (pendingHardProblems || [])
  if (storyboardApproved) {
    storyboardProblems = []
  } else {
    // 未达 clear 不放行：handoff.review.problems 必须写明最终 verdict 与 confusing，不能是空数组
    const verdictLine = finalVerdict === 'clear'
      ? '最终 verdict=clear，但五问/机器校验未全过，storyboard 未放行'
      : `最终 verdict=${finalVerdict || 'unknown'}（未达 clear），storyboard 未放行`
    const confusingLine = `confusing：${finalConfusing.length ? finalConfusing.join('；') : '（critic 未列出具体项）'}`
    const gateProblems = [verdictLine, confusingLine]
    if (finalWhy) gateProblems.push(`why：${_short(finalWhy, 100)}`)
    storyboardProblems = gateProblems.concat(storyboardProblems || [])
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// Phase 5: Video（时长路由）
// ═══════════════════════════════════════════════════════════════════════════
//
// ≤12 秒：本地模板线（06_content.json + run_video_generator_hf.py）。
// >12 秒：EAC 精品线。本仓库没有 EAC 本地 CLI，只产出 08_eac_handoff.json，
//         由人工/Agent 在 EAC 设计世界用 MCP 工具执行，不假装渲染过。
// 06_storyboard.json 缺失/损坏：回退模板线，不报错崩溃。

phase('Video')

let videoFile = ''
let videoRoute = 'template'
let eacHandoffFile = ''

// Storyboard 阶段没拿到可用分镜时，再读一次盘（可能是上一轮跑留下的）
if (!storyboardData) {
  const disk = await _probeJson(STORYBOARD_FILE, '06_storyboard.json', 'Video')
  if (disk) {
    storyboardData = disk
    storyboardFile = STORYBOARD_FILE
    log(`Video: 从 ${STORYBOARD_FILE} 读到分镜（${Number(storyboardData.duration_s)}s, route=${storyboardData.route}）`)
    const v = await _runStoryboardValidator(STORYBOARD_FILE)
    storyboardValidator = v
    storyboardProblems = v.pass ? [] : v.failLines
    if (!v.pass) log(`Video: 盘上分镜未过机器校验（${v.failLines.length} 行 FAIL），按风险继续`)
  } else {
    log(`Video: ${STORYBOARD_FILE} 不存在或不是合法 JSON，回退模板线`)
  }
}

const _sbDuration = storyboardData ? Number(storyboardData.duration_s) : NaN
const _sbUsable = Boolean(
  storyboardData &&
  Number.isFinite(_sbDuration) &&
  Array.isArray(storyboardData.scenes) &&
  storyboardData.scenes.length > 0
)

if (_sbUsable && _sbDuration > 12) {
  // ── EAC 精品线：不调用任何本地渲染脚本，只产出交接文件 ──────────────────────
  videoRoute = 'eac_handoff'
  eacHandoffFile = EAC_HANDOFF_FILE

  // handoff 是派生产物：生成 / 校验 / 回读全部交给 build_handoff.py。
  // workflow 只负责「在 pwsh 里跑命令 + 看退出码」，JS 里不再拼装任何 handoff 字段：
  // 运镜映射、clip 逐字段拼装、哈希自算与写后比对都已删除，同一份逻辑只许在脚本里存在。
  const _runHandoffCmd = async (cmd, what) => {
    let r = null
    try {
      r = await agent(
        `在 pwsh 里运行下面这一条命令，把结果原样回传。只跑这一条，不要改任何文件、不要自己补 handoff 内容。

## 命令
${cmd}

## 规则
- 用 pwsh 执行，工作目录用仓库根目录。
- stdout、stderr 与退出码原样回传，一个字都不要改写、总结或美化。
- 退出码 0 = 成功；非 0 = 失败（脚本约定：1 校验不一致，2 输入缺失或不合法）。
- 生成与校验都由脚本负责，不要手写、不要修补 08_eac_handoff.json。

## 返回格式（JSON）
{ "exit_code": number, "stdout": "原样 stdout", "stderr": "原样 stderr" }`,
        {
          schema: {
            type: 'object',
            properties: {
              exit_code: { type: 'number' },
              stdout: { type: 'string' },
              stderr: { type: 'string' },
            },
            required: ['exit_code', 'stdout'],
          },
          label: what,
          phase: 'Video',
        }
      )
    } catch (err) {
      throw new Error(`${what} 没能执行：${_short(String(err), 160)}`)
    }
    const code = typeof r?.exit_code === 'number' ? r.exit_code : null
    return { code, stdout: String(r?.stdout || ''), stderr: String(r?.stderr || '') }
  }
  const _rawOutput = (r) => `${r.stdout}${r.stderr ? `\n${r.stderr}` : ''}`

  // 1. 生成：脚本按分镜确定性写出 08_eac_handoff.json（默认与分镜同目录）
  const _gen = await _runHandoffCmd(
    `python "${BUILD_HANDOFF}" "${storyboardFile}"`,
    'build_handoff.py 生成'
  )
  if (_gen.code !== 0) {
    throw new Error(`build_handoff.py 生成失败（exit=${_gen.code}）：\n${_rawOutput(_gen)}`)
  }
  log(`Video: build_handoff.py 生成成功（exit=0）：${_short(_gen.stdout.replace(/\s+/g, ' ').trim(), 160)}`)

  // 2. 校验：--verify 必须 exit 0；非 0 就把脚本输出原样抛错，不在这里猜差异
  const _ver = await _runHandoffCmd(
    `python "${BUILD_HANDOFF}" "${storyboardFile}" --verify`,
    'build_handoff.py --verify'
  )
  if (_ver.code !== 0) {
    throw new Error(`build_handoff.py --verify 未通过（exit=${_ver.code}），handoff 与分镜不一致：\n${_rawOutput(_ver)}`)
  }
  log(`Video: build_handoff.py --verify 通过（exit=0）：${_short(_ver.stdout.replace(/\s+/g, ' ').trim(), 120)}`)

  // 3. 回读确认：数量 / 末镜起止 / 哈希字段都在，交接文件才算可用
  let _hb = null
  try {
    _hb = await agent(
      `只读检查一份刚生成的 handoff JSON，把下面几项原样报回来。不要修改文件，不要补字段。

## 文件
${eacHandoffFile}

## 规则
- 读取并解析该 JSON；不存在、读不了、不是合法 JSON → ok=false，不要创建或修补。
- clips_count 取 clips 数组的长度（数字）。
- last_start / last_duration 取 clips 最后一项的 start 与 duration（数字，原样，不要换算）。
- has_sha256：顶层 storyboard_sha256 是非空字符串才算 true；同时把它的值原样放进 sha256（没有就空字符串）。

## 返回格式（JSON）
{ "ok": boolean, "clips_count": number, "last_start": number, "last_duration": number, "has_sha256": boolean, "sha256": "string" }`,
      {
        schema: {
          type: 'object',
          properties: {
            ok: { type: 'boolean' },
            clips_count: { type: 'number' },
            last_start: { type: 'number' },
            last_duration: { type: 'number' },
            has_sha256: { type: 'boolean' },
            sha256: { type: 'string' },
          },
          required: ['ok', 'clips_count', 'last_start', 'last_duration', 'has_sha256'],
        },
        label: '回读 08_eac_handoff.json',
        phase: 'Video',
      }
    )
  } catch (err) {
    throw new Error(`回读 ${eacHandoffFile} 失败：${_short(String(err), 160)}`)
  }
  if (!_hb?.ok) throw new Error(`回读 ${eacHandoffFile} 失败：文件不存在或不是合法 JSON`)
  const _hbClips = Number(_hb.clips_count)
  if (!Number.isFinite(_hbClips) || _hbClips <= 0) {
    throw new Error(`回读 ${eacHandoffFile}：clips 数量是 ${_hb.clips_count}，交接文件不可用`)
  }
  if (_hb.has_sha256 !== true) {
    throw new Error(`回读 ${eacHandoffFile}：缺少 storyboard_sha256，拒绝继续（分镜一改 handoff 就失效，这个字段不能丢）`)
  }
  const _hbSha = String(_hb.sha256 || '').trim().toLowerCase()
  log(`Video: handoff 回读 OK：${_hbClips} 镜，末镜 start=${_hb.last_start}s / duration=${_hb.last_duration}s，storyboard_sha256=${_hbSha.slice(0, 12) || '（空）'}…`)

  log(`Video: 分镜 ${_sbDuration}s > 12s，不调用本地渲染脚本`)
  log(`进入 EAC 精品线：本仓库只有 MCP 工具（eac_status / eac_project_create / eac_timeline_update / eac_job_submit），没有 EAC 本地 CLI。`)
  log(`已产出 ${eacHandoffFile}：${_hbClips} 镜 / ${_sbDuration}s；path=pending 的镜头需要先补素材（由脚本统一写入）。`)
  log(`下一步由人工/Agent 在 EAC 设计世界会话里按 handoff 建项目、录真实产品/素材画面、配音、调色、渲染；workflow 不产出 07_video.mp4，也不把 handoff 当成品。`)

  if (_sbDuration < 20) {
    log(`注意：${_sbDuration}s 落在 13-19s 灰区，按约定并到 EAC 精品线，渲染前建议补到 20s 以上。`)
  }
} else {
  // ── 模板线：维持旧逻辑（<=12 秒，或分镜缺失时回退） ─────────────────────────
  videoRoute = 'template'
  if (storyboardData && _sbDuration <= 12) {
    log(`Video: 分镜 ${_sbDuration}s <= 12s，走本地模板线（06_content.json，9 秒兼容）`)
  } else if (!storyboardData) {
    log(`Video: 没有可用的 06_storyboard.json，回退旧逻辑（06_content.json + 本地渲染）`)
  } else {
    log(`Video: 分镜 duration_s 非法（${storyboardData.duration_s}），回退旧逻辑（06_content.json + 本地渲染）`)
  }

  const videoScript = VIDEO_ENGINE === 'legacy' ? 'run_video_generator.py' : 'run_video_generator_hf.py'
  const videoCmd = `python "${PROJECT_ROOT}\\we-video-generator\\scripts\\${videoScript}" "${contentFile}" "${OUT}\\images_good" "${OUT}\\07_video.mp4"`

  for (let attempt = 1; attempt <= MAX_RETRIES && !videoFile; attempt++) {
    try {
      const r = await agent(
        `从 content.json 和图片生成视频。

## 输入
- content.json: ${contentFile}
- 图片目录: ${OUT}\\images_good
- 输出目录: ${OUT}

## 步骤
1. 在 pwsh 里运行下面这条命令（默认 HyperFrames 渲染；传 video_engine: "legacy" 可回退旧版）：
   ${videoCmd}
2. 确认 ${OUT}\\07_video.mp4 真的存在且大于 0 字节（用 pwsh 查文件大小），再返回路径。
3. 命令报错就把 stderr 的关键几行放进 error，不要假装成功。

## 返回格式（JSON）
{
  "success": boolean,
  "file": "视频文件完整路径",
  "error": "错误信息（如果有）"
}

如果脚本执行失败，抛出错误让流程停止。`,
        {
          schema: {
            type: 'object',
            properties: {
              success: { type: 'boolean' },
              file: { type: 'string' },
              error: { type: 'string' },
            },
            required: ['success'],
          },
          label: `渲染 07_video.mp4（第 ${attempt} 次）`,
          phase: 'Video',
        }
      )

      if (!r?.success) throw new Error(r?.error || 'Video generation failed')
      videoFile = String(r.file || '').trim()
      log(`Video done: ${videoFile}`)
    } catch (err) {
      if (attempt === MAX_RETRIES) throw err
      log(`Video 第 ${attempt} 次失败：${String(err)}`)
    }
  }

  // 重试耗尽仍没有文件路径：agent 报 success 但漏字段时不能静默返回失败，
  // 否则下游会把「跑了但没成片」当成完成。抛错让调用方能区分「没跑」和「跑了但失败」。
  if (!videoFile) {
    throw new Error('模板线渲染失败：agent 未返回视频文件路径')
  }
}

// ─── 交付摘要 ───────────────────────────────────────────────────────────────

const result = {
  success: Boolean(videoFile || eacHandoffFile),
  output_dir: OUT,
  duration_s: DURATION,
  route: videoRoute,
  content_file: contentFile,
  storyboard_file: storyboardFile,
  storyboard_approved: storyboardApproved,
  validator: storyboardValidator
    ? { pass: Boolean(storyboardValidator.pass), exit_code: storyboardValidator.exitCode, fail_lines: storyboardValidator.failLines }
    : null,
  storyboard_problems: storyboardProblems,
  video_file: videoFile,
  eac_handoff: eacHandoffFile,
  note: eacHandoffFile
    ? '>12s 走 EAC 精品线：只产出 08_eac_handoff.json，未渲染 07_video.mp4，交接文件不是成品。'
    : (videoFile ? '<=12s 走模板线：已渲染 07_video.mp4。' : '未产出成片，也未产出交接文件。'),
}

log(`交付：route=${videoRoute}，video=${videoFile || '（无）'}，handoff=${eacHandoffFile || '（无）'}，storyboard_approved=${storyboardApproved}`)

return result
