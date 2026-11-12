// META: {"name":"tutorial-video","description":"生成 AI 科普/教程竖版短视频（HyperFrames 多场景）：输入一个主题，产出带配音、底部字幕、品牌 logo 的 1080x1920 mp4。阶段 Outline（分镜）→ ScriptQA（事实/去缩写/去 AI 味/字幕可读）→ TTS（配音 + 词级字幕）→ Compose（场景 HTML）→ Check（hyperframes check 必须 0 error）→ Review（抽帧看图）→ Render（渲染导出）。可重跑：已存在的 storyboard / 配音 / 场景 HTML / 成片优先复用。","phases":[{"title":"Outline"},{"title":"ScriptQA"},{"title":"TTS"},{"title":"Compose"},{"title":"Check"},{"title":"Review"},{"title":"Render"}]}

// ARGS: {"topic":"AI 为什么记不住你写的字","audience":"普通职场人，无技术背景","duration":30,"scenes":"4 到 6","reference":"","voice":"zh-CN-YunxiNeural","rate":"+0%","human_review":false,"force_rewrite":false}

const A = typeof args === 'undefined' || !args ? {} : args

const DURATION = Number(A.duration) || 30
const VOICE = A.voice || 'zh-CN-YunxiNeural'
const RATE = A.rate || '+0%'          // edge-tts 语速：+0% 正常，越大越快
const SCENES_HINT = A.scenes || '4 到 6'
const AUDIENCE = A.audience || '普通职场人，无技术背景'
const HUMAN_REVIEW = A.human_review === true
const FORCE = A.force_rewrite === true

// 旁白字数预算的语速常数：5.5 字/秒（曼波中文实测）。原文按 4.5 字/秒写的各处已统一改为 5.5，
// 见仓库 CLAUDE.md 第 3 条；5.5 只是写稿估值，成片时长仍以 TTS 实测为准。
const CPS = 5.5
const NARRATION_TARGET = Math.round(DURATION * CPS)
// 旧值 4.5 会被写成 duration * 4.5，这里改成 5.5 后同样的 30 秒从 135 字变 165 字。

// slug 化：主题里的非法文件名字符换成 -
const SLUG =
  String(A.topic || 'tutorial')
    .trim()
    .replace(/[\\/:*?"<>|]/g, '-')
    .replace(/\s+/g, '-')
    .slice(0, 40) || 'tutorial'

// ─── 0. 路径解析 ──────────────────────────────────────────────────────────────
// 工程目录和成片都放在输出根目录下的项目文件夹里，**不写进代码仓库**。
// 输出根目录来自 config.json 的 default_output_dir（和其他流水线同一个开关）。
const _rootRes = await agent(
  `确定项目根目录（仓库根）和输出根目录。只做只读探查，不要创建或修改任何文件。

1. 在仓库里 pwsh 运行：
   git rev-parse --show-toplevel
   把 stdout 原样记为项目根目录（完整路径）。命令失败返回 error 字段并停止。

2. 再 pwsh 运行（Windows 下用 python，路径含空格要加引号）：
   python "<项目根目录>/shared/config_loader.py" --get default_output_dir
   把 stdout 原样作为输出根目录返回（不要改写、不要加引号、不要自己拼桌面路径）。`,
  {
    label: 'resolve-paths',
    schema: {
      type: 'object',
      properties: {
        project_root: { type: 'string' },
        output_root: { type: 'string' },
        error: { type: 'string' },
      },
      required: ['project_root', 'output_root'],
    },
  }
)

const PROJECT_ROOT = String(_rootRes.project_root || '').trim()
if (!PROJECT_ROOT) throw new Error('无法确定项目根目录')
const SCRIPTS = PROJECT_ROOT + '\\ai-tutorial-video\\scripts'
const REFS = PROJECT_ROOT + '\\ai-tutorial-video\\references'
const EXPORT_ROOT = String(_rootRes.output_root || '').trim().replace(/[\\/]+$/, '')
if (!EXPORT_ROOT) throw new Error('无法读取 default_output_dir')
const PROJ =
  String(A.topic || 'tutorial')
    .split(/[：:]/)[0]
    .trim()
    .replace(/[\\/:*?"<>|]/g, '-')
    .slice(0, 20) || 'tutorial'
const PROJ_DIR = EXPORT_ROOT + '\\' + PROJ

// guard: 产物不许写进代码仓库
const _norm = (p) => String(p).replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
const _projNorm = _norm(PROJECT_ROOT)
if (
  _norm(PROJ_DIR).startsWith(_projNorm + '/') ||
  _norm(PROJ_DIR) === _projNorm ||
  _norm(EXPORT_ROOT) === _projNorm
) {
  throw new Error(`输出目录不能位于代码仓库内: ${PROJ_DIR}（仓库: ${PROJECT_ROOT}）`)
}

const RUN_ROOT = PROJ_DIR + '\\_hf' // 流水线中间产物（配音/HTML/渲染）
const RUN_DIR = RUN_ROOT + '\\' + SLUG
const WORK_DIR = RUN_DIR + '\\_work'
const STORYBOARD = WORK_DIR + '\\storyboard.json'
const SLOTS = RUN_DIR + '\\_work\\slots.json'
const SUBS = RUN_DIR + '\\_work\\subs.json'
const QA_MARK = WORK_DIR + '\\qa-approval.json'

log(`Run dir: ${RUN_DIR}`)
log(`Export: ${PROJ_DIR}`)
log(`字数预算: ${DURATION}s × ${CPS} 字/秒 ≈ ${NARRATION_TARGET} 字`)

// ─── Phase 1: Outline ─────────────────────────────────────────────────────────
// 产出 storyboard.json：场景列表 + 每个场景的旁白文本 + 画面意图。
// 场景数量按目标时长算：中文语速按 5.5 字/秒核算，30 秒 ≈ 165 字。

phase('Outline')

const outline = await agent(
  `写一条 AI 科普/教程短视频的分镜脚本，保存为 ${STORYBOARD}。

## 可重跑：先看已有产物
如果 ${STORYBOARD} 已经存在，先用读取工具打开它核对：
- scenes 数组齐全（id 小写英文、前 2 字母不重复）、每个场景有 narration 和 visual、voice 是中文音色、
  publish_title ≤15 汉字、publish_desc ≤20 汉字、旁白总字数落在 ${NARRATION_TARGET} 字的 95%~105% 内
  → 直接复用，不要重写。返回 { "success": true, "reused": true, "file": ..., "scene_count": ..., "total_chars": ... }
- 只有部分场景缺 narration/visual 或字数明显不足 → 只补写缺的部分，保留已有场景的 id 与顺序。
- 本次调用 ${
    FORCE
      ? '要求强制重写（args.force_rewrite = true）→ 覆盖重写整份 storyboard。'
      : '没有要求强制重写（args.force_rewrite 不为 true）→ 能复用就复用。'
  }

## 输入
- 主题: ${A.topic}
- 受众: ${AUDIENCE}
- 目标时长: ${DURATION} 秒
${A.reference ? '- 参考资料（必须以它为准，数字不能编）:\n' + A.reference : '- 参考资料: 无（数字要写成「大致/通常」这类模糊表述，或只用常识性结论）'}

## 先建目录
pwsh 运行：python -c "import os; os.makedirs(r'${WORK_DIR}', exist_ok=True)"

## 分镜规则
1. **场景数 = ${SCENES_HINT} 个**，第一个是钩子（hook），最后一个是收尾（outro），中间是讲解场景。
2. 每个场景 id 用小写英文单词，前 2 个字母不能和别的场景重复（如 hook/split/numbers/outro）。
3. **旁白（narration）是这个场景要念出来的完整中文口语稿**，不是标题。一句一句写，读出来要顺。
   - 中文 TTS 语速按 **5.5 字/秒** 核算：总旁白字数 ≈ 目标时长 × 5.5。${DURATION} 秒 ≈ ${NARRATION_TARGET} 字。
     写到预算的 95%~105%，**写满预算，宁多勿少**——旁白偷工减料视频就偏短。
   - **句子长短必须错开**：短的 6~10 字，长的 18~22 字，混着来。连续几句都差不多长，
     念出来就是机器稿——这是 AI 味最大的指纹，比任何禁词都致命。
   - **一句里逗号隔开的每个小段 ≤14 字**（字幕按标点切行，一个逗号小段就是一行字幕）。
   - 句末带标点（TTS 靠标点断句，标点也影响字幕切分）。
   - 数字写成中文读法（41.3% → 百分之四十一点三），TTS 吃不了拉丁字母和符号。
   - 口语垫词可以点缀：「你看」「说白了」「对吧」这类，每个场景最多 1 个，有人味。
   - 不要出现「大家好」「今天我们来聊聊」这类废话开场，直接进钩子。
4. **画面文字 ≠ 旁白**。字幕会把旁白原样打在画面底部，画面再写一遍就是复读，纯属浪费一屏。
   画面文字只写**旁白里没有的东西**：数字、专有名词、对比项、流程节点名、方块里的字。
   - ✅ 「上方三张对比卡：『训练目标』/『接得顺』/『事实正确』，下方一行小字『都不等于知道真相』」
   - ✅ 「左侧表格：公司名 / 数字 / 时间三列，数据行不写人名」
   - ❌ 「大字『模型不认识单字，只认识词块』」——这句字幕已经念过了
   - ❌ 「大字『你以为 AI 上网就能查到答案』」——钩子的大字也必须比旁白短，最多 12 字
5. **画面意图（visual）** 用一句话描述这屏要展示什么（元素、位置、**画面上具体写哪几个标签**）。
   例如：「上方三张对比卡，卡标题『训练目标』，正文『接得顺』『事实正确』，逐张翻入」
6. **钩子句式每期轮换，别次次都是同一个**。从这几种里挑一个最贴题的：
   - 反直觉对比：「你以为 X，其实 Y」
   - 事实砸场：直接甩一个反常识的事实或数字开场
   - 场景代入：从观众刚做过的一个具体动作切入
   - 结论先行：先把结论说了，再回头解释为什么
7. **至少一个具体锚点**：整条脚本至少有一处具体的例子、场景或数字，
   从头到尾都是抽象名词串（「单位」「边界」「能力」）就是机器稿。数字必须可追溯：
   有参考资料时只能用资料里的数字；没有资料就别给具体数字，改用常识性例子或定性表述。
8. 不要在旁白里念「点赞」「关注」「订阅」这类口播 CTA，收尾场景可以在画面上放但别念。

## storyboard.json 格式
\`\`\`json
{
  "title": "视频标题（不念出来）",
  "publish_title": "微信短视频标题，不超过 15 个汉字（发视频号用）",
  "publish_desc": "微信短视频描述，不超过 20 个汉字（发视频号用，补充标题没说完的钩子）",
  "voice": "${VOICE}",
  "scenes": [
    {
      "id": "hook",
      "narration": "你以为 AI 在读你写的字？其实它看到的是一堆词块。",
      "visual": "上排一串空方块（方块里不写字），下方两个黄标签『TOKEN』『词块』，箭头从方块指向标签",
      "elements": "可选：补充要出现的具体文本"
    }
  ]
}
\`\`\`
voice 固定用 ${VOICE}；publish_title / publish_desc 按汉字数硬限（15/20），数字和英文算半个字。
写文件用写入工具，编码 UTF-8，不要 BOM。

## 返回格式（JSON）
{ "success": boolean, "reused": boolean, "file": "完整路径", "scene_count": number, "total_chars": number }`,
  {
    label: 'outline',
    phase: 'Outline',
    schema: {
      type: 'object',
      properties: {
        success: { type: 'boolean' },
        reused: { type: 'boolean' },
        file: { type: 'string' },
        scene_count: { type: 'number' },
        total_chars: { type: 'number' },
        error: { type: 'string' },
      },
      required: ['success', 'file'],
    },
  }
)

if (!outline?.success) throw new Error('Outline failed: ' + (outline?.error || 'unknown'))
log(`Outline: ${outline.scene_count} 场景, 旁白 ${outline.total_chars} 字${outline.reused ? '（复用已有 script）' : ''}`)

// ─── Phase 2: ScriptQA ───────────────────────────────────────────────────────
// 分镜脚本的四道体检：事实准且新 / 不自造缩写 / 去 AI 味 / 字幕行读得顺。
// 审一轮改一轮，最多 3 轮；改的是 narration（口播稿）和 visual（画面文字），
// 场景 id / 顺序 / 数量不动 —— 后面的 TTS 阶段直接读改完的 storyboard.json。

phase('ScriptQA')

const QA_MAX_ROUNDS = 3
// 预算基数复用 NARRATION_TARGET（CPS 常量，改值见文件头的 5.5 注释）
const QA_TARGET_CHARS = NARRATION_TARGET
const QA_MIN_CHARS = Math.round(QA_TARGET_CHARS * 0.95)
const QA_MAX_CHARS = Math.round(QA_TARGET_CHARS * 1.1)
let qaChars = outline.total_chars || 0
let qaFixed = false

const reviewPrompt = `审查这条短视频的分镜脚本，判断能不能进配音。

## 可重跑：先看上次的通过记录
先用读取工具看 ${QA_MARK}：
- 它存在、里面 approved=true、chars 与 ${STORYBOARD} 当前旁白总字数一致，
  且 storyboard.json 的修改时间不晚于这个记录文件（用 pwsh 的 Get-Item 比 LastWriteTime）
  → 说明上次已经通过、脚本没再改过：直接返回 { "approved": true, "issues": [], "severity": "low" }，
    并在 issues 里补一句「复用上次通过记录」，不要再重复审。
- 记录不存在、字数变了、或 storyboard 比记录更新 → 正常审。

## 待审
- 分镜脚本: ${STORYBOARD}
- 主题: ${A.topic}
- 受众: ${AUDIENCE}
- 目标时长: ${DURATION} 秒（口播总字数应 ≈ ${DURATION} × ${CPS} = ${QA_TARGET_CHARS} 字；**不低于 ${QA_MIN_CHARS} 字**，略超到 ${QA_MAX_CHARS} 字没问题；当前 ${qaChars} 字，低于下限直接打回）
- 参考资料: ${A.reference || '（无）'}

## 先看字幕成品（审稿对象是观众读到的字幕行，不是旁白原文）
旁白会按标点被切成一行行字幕打在画面底部。审稿前先 pwsh 运行：
    python "${SCRIPTS}\\tutorial_build.py" subs-preview --storyboard "${STORYBOARD}"
对着它的输出查下面的第 4 条。命令跑不了就退回审旁白原文。

## 审查标准（四条，任一不合格就打回）

### 1. 事实准确，且不过时
- 脚本里出现的每个数字、时间、版本号、公司名、产品名、能力宣称，都必须可追溯。
  有参考资料 → 只能引用资料里有的数字；没有参考资料 → 核实关键事实（有联网搜索就用搜索；没有搜索工具就只保留你有把握的常识结论）。
- 涉及时效性表述的（模型版本、价格、能力边界、发布日期、"目前/已经/还没"）：
  核实是不是**当前**状态。信息是最近的 → 保留；是过时的 → 打回。
  核实不了 → 打回，要求改成不依赖具体数字的定性表述。
- 不要拿旧信息当现状讲（把已被更新的版本当成"目前最强"这类）。

### 2. 不要自造缩写，用大家通用的叫法
- 脚本里所有缩写和术语，检查是不是圈子里本来就通用的说法：
  ✅ 大语言模型（LLM）、检索增强生成（RAG）、智能体（Agent）、API、上下文窗口、微调、推理、多模态
  ❌ 自己生造的缩写、只有作者自己懂的命名、把大白话硬凑成三段式术语
  ❌ 给一个普通概念安一个新名词（"认知增强闭环""多维语义对齐引擎"这类）
- 没有公认简称的概念，就用大白话直说，不要给它安缩写。
- 画面文字（visual / elements 里要写的标签）同样查一遍。

### 3. 去 AI 味（这是短视频口播，不是文章）
念出来不能像 AI 写的，逐条查：
- 删开场铺垫："大家好""今天我们来聊聊""在开始之前""接下来我们"
- 删书面强调套路："值得注意的是""需要强调的是""总而言之""总的来说""可以说""某种程度上"
- 删商业黑话和 AI 味词："赋能""颠覆""革命性""重塑""底层逻辑""抓手""闭环""降本增效""一站式""无缝"
- 删书面腔副词："非常""极其""基本上""确实"（「其实」口头说一次无妨，出现两处以上才算问题）
- **句子长短必须有变化**：连续三句字数接近（±30%）就是机器稿最大的指纹，打回
- 排比克制："不是……而是……""既……又……""不仅……而且……"整条最多一次；
  三个结构完全相同的短句连排也算
- 泛指换成具体："人们""大家" → "你"或具体的人
- 书面公文腔改口语："该项技术被广泛采用" → "现在大家都在用"
- 数字说人话："提升约 37.2%" → "快了三成多"
- **至少一个具体锚点**：整条脚本要有一处具体例子/场景/数字，从头到尾全是抽象名词就打回
- 口语垫词是加分项不是减分项："你看""说白了""对吧"每个场景最多 1 个，别删干净

### 4. 字幕行读得顺（对着 subs-preview 的输出查）
字幕是观众逐字读的东西，切得碎/拼得怪比用词更暴露机器味：
- 每行 4~16 字：出现 ≤3 字的孤行（信息量趋近零、一闪而过）或超 16 字的长行都打回。
  改法是挪逗号/加逗号，让每个逗号小段落在 4~14 字 —— 改旁白句读，别动字幕逻辑
- 每行默念一遍要通顺，不能有读不通的拼接

## 返回格式（JSON）
{ "approved": boolean, "issues": ["问题1", "问题2"], "severity": "high" | "medium" | "low" }
issues 必须具体到能照着改：指出是哪句口播、画面里哪个标签、哪行字幕、怎么改。approved=false 时 issues 至少一条。
severity：事实错/过时、自造缩写 = high；AI 味、字幕行问题 = medium/low。`

const reviewSchema = {
  type: 'object',
  properties: {
    approved: { type: 'boolean' },
    issues: { type: 'array', items: { type: 'string' } },
    severity: { type: 'string' },
  },
  required: ['approved', 'issues'],
}

const rewritePrompt = (issues) => `按审查意见改写分镜脚本，覆盖保存回原路径。

## 审查意见（逐条修掉）
${issues.map((issue, i) => `${i + 1}. ${issue}`).join('\n')}

## 当前脚本
${STORYBOARD}

## 约束
- 只改 narration（口播稿）和 visual / elements（画面文字）。
  场景 id、顺序、数量、publish_title / publish_desc 都不许动。
- 口播总字数保持在 ≈ ${QA_TARGET_CHARS} 字上下 20% 内（当前 ${qaChars} 字）。
- 改句读时：每个逗号小段 4~14 字，别制造 ≤3 字的孤段；句子长短保持错开。
- 改完把每个场景的旁白默念一遍，要顺。
- 修事实时不要引入新数字。资料里没有的信息，要么删掉，要么改成不依赖具体数字的定性表述。
- 不要为了改而改：只是措辞偏好、没有事实问题的句子可以保留原样。
- 改完把通过记录写到 ${QA_MARK}：{ "approved": true, "chars": <当前总字数>, "severity": "low", "note": "rewritten" }，
  用写入工具，UTF-8。这样重跑时不必再审一遍。

## 返回格式（JSON）
{ "success": boolean, "file": "完整路径", "total_chars": number, "fixed": ["修了什么"] }`

let qaApproved = false
let qaIssues = []
let qaSeverity = 'high'

// 审一轮改一轮：改完进下一轮复审。
for (let round = 1; round <= QA_MAX_ROUNDS; round++) {
  const verdict = await agent(reviewPrompt, { label: `scriptqa-review-r${round}`, phase: 'ScriptQA', schema: reviewSchema })
  qaIssues = verdict?.issues || []
  qaSeverity = verdict?.severity || 'high'

  if (verdict?.approved) {
    qaApproved = true
    log(`ScriptQA passed (round ${round})`)
    break
  }

  log(`ScriptQA round ${round} rejected (${qaSeverity}): ${qaIssues.join('; ')}`)

  const fixed = await agent(rewritePrompt(qaIssues), {
    label: `scriptqa-rewrite-r${round}`,
    phase: 'ScriptQA',
    schema: {
      type: 'object',
      properties: {
        success: { type: 'boolean' },
        file: { type: 'string' },
        total_chars: { type: 'number' },
        fixed: { type: 'array', items: { type: 'string' } },
      },
      required: ['success', 'total_chars'],
    },
  })
  if (!fixed?.success) throw new Error('ScriptQA rewrite failed: ' + (fixed?.error || 'unknown'))
  qaFixed = true
  qaChars = fixed.total_chars || qaChars
  log(`ScriptQA rewrite round ${round}: ${(fixed.fixed || []).length} 处修改, ${qaChars} 字`)

  // 只有 high 级（事实错、自造缩写）才值得报废整条流水线；
  // medium/low 是打磨项，改一轮就放行，别让 30 秒科普片死在吹毛求疵上。
  if (qaSeverity !== 'high') {
    qaApproved = true
    log(`ScriptQA 遗留打磨项（已改一轮，放行）: ${qaIssues.join('; ')}`)
    break
  }
}

// 最后一轮改完还没复审过 → 再审一次确认
if (!qaApproved) {
  const finalVerdict = await agent(reviewPrompt, { label: 'scriptqa-final-review', phase: 'ScriptQA', schema: reviewSchema })
  if (finalVerdict?.approved) {
    qaApproved = true
    qaIssues = []
    log('ScriptQA passed after final review')
  } else {
    qaIssues = finalVerdict?.issues || qaIssues
    qaSeverity = finalVerdict?.severity || 'high'
    if (qaSeverity !== 'high') {
      qaApproved = true
      log(`ScriptQA 遗留打磨项（已改，放行）: ${qaIssues.join('; ')}`)
    }
  }
}

if (!qaApproved) {
  throw new Error(
    'ScriptQA failed after ' + QA_MAX_ROUNDS + ' rounds, remaining issues:\n' + qaIssues.join('\n')
  )
}
log(`ScriptQA: 通过${qaFixed ? '（已改写）' : '（原稿即合格）'}`)

// ─── Phase 3: TTS ────────────────────────────────────────────────────────────
// 声音是时钟：配音生成后，场景槽位 = 配音时长 + 0.4s。

phase('TTS')

const tts = await agent(
  `按分镜脚本生成配音和字幕时间戳。

## 可重跑：先判断能不能复用已有配音和槽位
先 pwsh 查看 ${SLOTS}、${SUBS}、${RUN_DIR}\\assets\\voice\\：
- 三样齐全（slots.json、subs.json、每个场景的 vo_<id>.mp3）、
  slots.json 里的场景 id 和顺序与 storyboard.json 完全一致、
  每个 vo_<id>.mp3 用 ffprobe 量的时长与 slots 里的 voice_dur 相差 ≤0.15s、
  且 storyboard.json 的修改时间不晚于 slots.json（用 Get-Item 比 LastWriteTime）
  → 配音没过期：跳过第 1、2 步，只做第 3 步核对后按返回格式返回（"reused": true）。
- 只是个别场景的旁白改了 → 备份 ${SLOTS} 和 ${SUBS} 到 _work 下带 _bak 后缀，
  然后整条重跑第 2 步（tts 会重写全部场景的 mp3 和 slots，代价只有几分钟，比手工挑场景稳）。
- 什么都没有 → 走完整流程。

## 步骤
1. 初始化工程目录（拷 assets / package.json / hyperframes.json 到 run 目录；已初始化过会跳过）：
   pwsh 运行：python "${SCRIPTS}\\tutorial_build.py" init --run-dir "${RUN_DIR}"

2. 生成配音 + 词级字幕时间戳 + 场景槽位：
   pwsh 运行：python "${SCRIPTS}\\tutorial_build.py" tts --run-dir "${RUN_DIR}" --storyboard "${STORYBOARD}" --voice "${VOICE}" --rate "${RATE}"

   脚本会：edge-tts 合成每个场景的 mp3 → ffprobe 量时长 → 取 WordBoundary 词级时间戳 →
   按标点切成字幕子句 → 写 _work/subs.json 和 _work/slots.json（场景起点/时长）。

   语速：${RATE}（edge-tts 百分比，+0% = 正常约 ${CPS} 字/秒，-10% 明显拖慢）。
   字幕停不下时脚本会自动再降 10% 重试一次。

3. 读 ${SLOTS}，确认：
   - total 不低于目标时长 ${DURATION} 秒的 90%（宁可略长不要偏短）；超过 120% 才需要精简
   - 每个场景 slots 里 duration = voice_dur + 0.4（末场可能另有尾留白）

4. 如果 total 低于目标的 90%，**改 storyboard.json 的旁白**（加一句补足字数）重跑第 2 步；
   超过 120% 才精简句子。最多改 2 次。

## 注意
- edge-tts 报 403 = 微软 token 过期，\`pip install -U edge-tts -i https://mirrors.aliyun.com/pypi/simple/\` 再重试。
- ffprobe 找不到时装 ffmpeg 或确保 D:\\ffmpeg\\bin 在 PATH 里。
- 完整读命令输出，不要过滤。

## 返回格式（JSON）
{ "success": boolean, "reused": boolean, "total_duration": number, "scenes": [{"id":"hook","duration":5.3,"subs":3}] }`,
  {
    label: 'tts',
    phase: 'TTS',
    schema: {
      type: 'object',
      properties: {
        success: { type: 'boolean' },
        reused: { type: 'boolean' },
        total_duration: { type: 'number' },
        scenes: {
          type: 'array',
          items: {
            type: 'object',
            properties: {
              id: { type: 'string' },
              duration: { type: 'number' },
              subs: { type: 'number' },
            },
            required: ['id'],
          },
        },
        error: { type: 'string' },
      },
      required: ['success', 'total_duration'],
    },
  }
)

if (!tts?.success) throw new Error('TTS failed: ' + (tts?.error || 'unknown'))
log(`TTS: 总时长 ${tts.total_duration}s, ${(tts.scenes || []).length} 场景${tts.reused ? '（复用已有配音）' : ''}`)

// ─── Phase 4: Compose ────────────────────────────────────────────────────────
// agent 只写「画面」，配音和字幕由脚本注入。

phase('Compose')

const compose = await agent(
  `按分镜脚本写每个场景的 HTML，并生成根 composition。

## 可重跑：先看已有场景 HTML
先 pwsh 跑一次 verify 看现状：
    python "${SCRIPTS}\\tutorial_build.py" verify --run-dir "${RUN_DIR}"
如果 ${RUN_DIR}\\compositions\\ 下每个场景都有 <id>.html、verify 通过、且这些 html 的修改时间都不早于 slots.json 和 storyboard.json
→ 不用重写，直接返回 { "success": true, "scenes": [...], "verify_passed": true, "reused": true }。
只有缺场景、或 verify 报错、或 storyboard/slots 比 html 新时，才重写受影响的那几个场景。

## 必读
先读取 ${REFS}\\scene-authoring.md —— 里面有完整的骨架、硬约束、品牌色板、版面安全区。
样例场景在 ${REFS}\\example-scenes\\（已通过 check），可以照着抄结构。

## 输入
- 分镜脚本: ${STORYBOARD}
- 场景槽位（每个场景的时长/起点，**场景内所有时间都是相对场景起点的**）: ${SLOTS}
- 字幕文本和时间: ${SUBS}

## 步骤
1. 读 ${SLOTS}，拿到每个场景的 duration。场景内所有元素的
   \`data-start\` 和 \`data-start + data-duration\` 必须 ≤ 该场景时长。
2. 为每个场景写 \`${RUN_DIR}\\compositions\\<id>.html\`（用写入工具，UTF-8）：
   - \`data-composition-id\` = 场景 id，\`window.__timelines["<id>"]\` 用同一个 id
   - 元素 id 用场景 id 前 2 字母做前缀（hk- / sp- / nm- / ot-），全页唯一
   - 按 storyboard 里的 visual 描述实现画面
   - **只写画面**：不写 \`<audio>\`、不写 \`.sub\` 字幕 div、不写字幕 tween —— 这些由脚本注入
   - 不要写 \`<style>\` 里的 \`.sub\` 规则，脚本会统一插入
3. 运行注入（生成 \`compositions/captions.html\` 字幕子合成 + index.html 里的配音轨）：
   pwsh 运行：python "${SCRIPTS}\\tutorial_build.py" build --run-dir "${RUN_DIR}"

4. 自检（必须通过）：
   pwsh 运行：python "${SCRIPTS}\\tutorial_build.py" verify --run-dir "${RUN_DIR}"

5. 如果 verify 报字幕缺失/时间不匹配，说明第 2 步的 HTML 里混进了字幕或配音标签，
   删掉重写那些片段再 build。最多修 3 次。
   如果 verify 报「画面文字是字幕原话」，说明画面在复读旁白 —— 见下面的硬约束，改画面别改旁白。

## 硬约束（照做，否则渲染出来是坏的）
- **画面文字不复读字幕**。字幕带在画面底部把旁白原样打出来，画面再写一遍就是白白浪费一屏。
  画面文字只写旁白里**没有**的东西：数字、专有名词、对比项、流程节点名、方块/表格里的字。
  verify 会统计「画面文字和字幕重复的比例」：讲解场景超过 45%、首尾场景超过 75% 直接失败，
  并会点名是哪几段在复读 —— 照着改画面，不要改旁白。
  例：旁白说「模型不认识单字，只认识词块」，画面就该画一排方块标「TOKEN / 词块」，
  而不是再打一行「模型不认识单字，只认识词块」。
- 每个要动的元素都要 \`class="clip"\` + \`data-start\` + \`data-duration\`
- 动画一律用 \`fromTo\`，**不要用 \`from\`**（\`from\` 的初始态立即生效，会让元素整个窗口都不可见）
- **不要给 \`.clip\` 元素补间 display/visibility/autoAlpha**，要淡入就动子元素
- 画面内容不要越过 y=1500（字幕带在 1500-1620）
- **浅色背景（全系列统一，别做深色）**：场景根用
  \`radial-gradient(ellipse at 50% 38%, #ffffff 0%, #e9ecf1 78%)\`
  - 主文字 \`#141519\`，次要/注释 \`#4b5260\`（浅底上别用浅灰，contrast 会挂）
  - 浅底上的强调字用深金 \`#6f5700\`；\`#ffd700\` 只做描边/装饰，或深色块上的字（浅底上做正文看不清）
  - 卡片：底 \`#ffffff\`，边框 \`#d6dae2\`；要反衬时用深色块（底 \`#1b1d24\`，字 \`#f2f3f5\`）
- **场景里不要放 logo 图片**：根 composition 已经常驻顶部品牌 logo（脚本放的），场景里再放就是重复。
  结尾 CTA 附近尤其不许出现 logo。
- 结尾不放品牌名胶囊（顶部常驻 logo 已经承担品牌曝光，结尾只留「点赞 · 关注」CTA）。
- 结尾「点赞 · 关注」CTA **固定 top:1366px 居中**（紧贴字幕带上沿，别放右上角，全系列统一），用深底 + 3px 金色描边胶囊：
  \`background:#1e212b; border:3px solid #ffd700; border-radius:999px; padding:16px 52px; color:#f2f3f5; font-size:44px; font-weight:900; letter-spacing:6px; box-shadow:0 0 26px rgba(255,215,0,.28)\`；
  入场用 \`back.out(2.2)\` 从 scale .55 弹到 1，末尾加一次 scale 1.07 轻脉冲
- 不要 Date.now()、不要无种子随机
- **特效音（克制，不是每屏都要响）**：关键元素入场在元素上加 \`data-sfx="pop|whoosh|ding"\`
  （pop=卡片/标签翻入，whoosh=转场/箭头扫入，ding=数字/要点亮相），
  build 会按该元素的 data-start 自动注入低音量音效，场景里**不要写 <audio>**（verify 会拦）。
  **全片最多 4 处**：只给钩子大字 reveal、数字特写、结尾 CTA 弹入这类重点时刻，
  普通文字和场景切换一律不加。详见 scene-authoring.md 的「特效音」一节。

## 画面节奏（check 的 craft 规则，不满足会出 warning）
- **一行字在屏上至少要停 0.5 + 0.3 × 词数 秒**（3 个词 1.05s，7 个词 1.95s）。
  算不准就干脆多停一会儿。字越少停越短，别让观众来不及读。
- **不能有超过 3 秒画面完全不动**（dead_stretch）。出场动画别都挤在开头，
  要跟旁白节奏对齐，尾部再补一拍（缩放/淡出/换行都算变化）。
  确实要静止停住（比如刻意留白），给那个元素加 \`data-hold\`。
- 场景时长是配音时长 + 0.4s，画面元素的时间要铺满这段时间，别提前演完。
  **每个场景最后一个元素的 \`data-start + data-duration\` 必须等于场景时长**（误差 ≤0.1s）——
  差一截就等于成片结尾有几帧只剩 logo 和字幕的空屏。

## 返回格式（JSON）
{ "success": boolean, "reused": boolean, "scenes": ["hook","split"], "verify_passed": boolean, "error": "错误信息" }`,
  {
    label: 'compose',
    phase: 'Compose',
    schema: {
      type: 'object',
      properties: {
        success: { type: 'boolean' },
        reused: { type: 'boolean' },
        scenes: { type: 'array', items: { type: 'string' } },
        verify_passed: { type: 'boolean' },
        error: { type: 'string' },
      },
      required: ['success'],
    },
  }
)

if (!compose?.success || !compose?.verify_passed) {
  throw new Error('Compose failed: ' + (compose?.error || 'verify not passed'))
}
log(`Compose: ${(compose.scenes || []).join(', ')}${compose.reused ? '（复用已有场景 HTML）' : ''}`)

// ─── Phase 5: Check ───────────────────────────────────────────────────────────

phase('Check')

let checkResult = null
for (let attempt = 1; attempt <= 3; attempt++) {
  checkResult = await agent(
    `跑 HyperFrames 校验并修掉所有 error。

## 步骤
1. 跑校验（**必须用这个包装命令**，它会把 ffmpeg/ffprobe 加进 PATH，Windows 上 npx 是 .cmd）：
   pwsh 运行：python "${SCRIPTS}\\tutorial_build.py" hf --run-dir "${RUN_DIR}" check --json

2. 读 JSON 里的 error（**warning 可以先放行，error 必须清零**）。常见修法：
   - composition id 不匹配 → 改场景文件里的 data-composition-id / window.__timelines
   - clip 时间越界 → 调 data-start / data-duration（别超场景时长）
   - id 重复 → 加场景前缀
   - 对比度不足 → 浅底上把灰字换成更深的（\`#4b5260\` / \`#141519\`），金色正文换深金 \`#6f5700\`
   - \`.clip\` 上补间了 display/visibility → 改成动子元素
   - lint 报「0 samples」 → 说明还有 lint error 没清，先清 lint

3. 顺手把 craft warning 也修了（warning 不挡渲染，但画面确实不好）：
   - \`line_unread\` → 那行字在屏上停得不够久，加长它的 data-duration
   - \`dead_stretch\` → 超过 3 秒画面没动，加一拍动画，或给元素加 \`data-hold\`
   - \`text_below_floor\` → 字太小（1080 宽下小于 28px），放大它
   - \`first_frame_empty\` → 第 0 帧什么都没有，让首屏在 0.2s 内出东西

4. **只要改了场景 HTML 就必须先重跑 build 再 check**（build 幂等，几秒的事；
   场景里的 data-sfx 标注也要 build 才会变成 index.html 里的音轨）：
   pwsh 运行：python "${SCRIPTS}\\tutorial_build.py" build --run-dir "${RUN_DIR}"
   然后重跑 check --json，最多 3 轮。

5. **不要过滤命令输出**（会吞掉真实错误）。完整读输出。

## 返回格式（JSON）
{ "success": boolean, "error_count": number, "warning_count": number, "fixed": ["修了什么"] }`,
    {
      label: `check-attempt-${attempt}`,
      phase: 'Check',
      schema: {
        type: 'object',
        properties: {
          success: { type: 'boolean' },
          error_count: { type: 'number' },
          warning_count: { type: 'number' },
          fixed: { type: 'array', items: { type: 'string' } },
        },
        required: ['success', 'error_count'],
      },
    }
  )
  if (checkResult?.success && checkResult.error_count === 0) break
  log(`Check attempt ${attempt}: ${checkResult?.error_count} errors`)
}

if (!checkResult?.success || checkResult.error_count !== 0) {
  throw new Error('Check failed: ' + (checkResult?.error_count ?? '?') + ' errors remaining')
}
log(`Check: 0 errors, ${checkResult.warning_count || 0} warnings`)

// ─── Phase 6: Review ──────────────────────────────────────────────────────────

phase('Review')

const review = await agent(
  `抽帧看效果，确认每屏真的显示对了。

## 步骤
1. 抽每个场景中点的帧：
   pwsh 运行：python "${SCRIPTS}\\tutorial_build.py" hf --run-dir "${RUN_DIR}" snapshot --at <各场景中点秒数,逗号分隔>
   （场景中点 = 场景起点 + 时长/2，从 ${SLOTS} 里算）
2. 快照 PNG 在 ${RUN_DIR}\\.hyperframes\\artifacts\\snapshots\\ 下。
   **用读取工具逐张看图**，确认：
   - 标题/大字都在，没有空白屏、没有元素重叠
   - 底部有字幕（黑底白字胶囊），末尾没有标点
   - 字幕没有压在画面内容上
   - logo 在顶部
3. 发现问题：改对应场景 HTML → 重跑
   pwsh 运行：python "${SCRIPTS}\\tutorial_build.py" build --run-dir "${RUN_DIR}"
   然后重新 check --json 确认 0 error，再抽一次帧看。
4. 如果快照已经存在、且都比场景 HTML 和 slots.json 新、check 也是 0 error，
   可以直接复用这些快照复看，不必重新抽帧。

## 返回格式（JSON）
{ "success": boolean, "snapshots": ["文件路径"], "issues_found": ["问题"], "issues_fixed": boolean }`,
  {
    label: 'review',
    phase: 'Review',
    schema: {
      type: 'object',
      properties: {
        success: { type: 'boolean' },
        snapshots: { type: 'array', items: { type: 'string' } },
        issues_found: { type: 'array', items: { type: 'string' } },
        issues_fixed: { type: 'boolean' },
        error: { type: 'string' },
      },
      required: ['success'],
    },
  }
)

if (!review?.success) throw new Error('Review failed: ' + (review?.error || 'unknown'))
log(`Review: ${(review.snapshots || []).length} 张快照, 问题 ${(review.issues_found || []).length} 个`)

if (HUMAN_REVIEW) {
  log(`\n========== 人工审查点 ==========`)
  log(`工程: ${RUN_DIR}`)
  log(`快照: ${(review.snapshots || []).join(', ')}`)
  log(`分镜: ${STORYBOARD}`)
  log(`==============================`)
  log(`已停在 Review。看过快照后把 args.human_review 改成 false 重跑；已有产物会复用，不会重做配音和画面。`)
  return {
    success: false,
    awaiting: 'video-review',
    run_dir: RUN_DIR,
    storyboard: STORYBOARD,
    snapshots: review.snapshots || [],
  }
}

// ─── Phase 7: Render ──────────────────────────────────────────────────────────

phase('Render')

const render = await agent(
  `渲染最终视频。

## 可重跑：先看能不能复用已有成片
先 pwsh 看 ${RUN_DIR} 下的 ${SLUG}_v*.mp4：
- 有现成 mp4，且 ffprobe 时长与 ${SLOTS} 的 total 相差 ≤0.3s，抽 2 帧确认底部字幕带在，
  并且这些 mp4 的修改时间不晚于 scenes HTML 和 slots.json（Get-Item 比 LastWriteTime）
  → 直接复用最新那个（"reused": true），跳过第 1、2 步，只做第 3、4 步。
- 没有、或画面/时长比成片新 → 重新渲染。

## 步骤
1. 渲染（**输出文件名带序号，不要覆盖旧文件** —— 旧文件可能正被播放器占用，
   Windows 上覆盖会静默失败，还看着像成功）：
   pwsh 运行：python "${SCRIPTS}\\tutorial_build.py" hf --run-dir "${RUN_DIR}" render --quality looks -o "${RUN_DIR}\\${SLUG}_v1.mp4"

   如果 ${RUN_DIR}\\${SLUG}_v1.mp4 已存在，改用 _v2、_v3…
2. **完整读渲染输出**，不要过滤。失败就按输出里的 Fix: 提示改，重试最多 2 次。
3. 验片（两条都要做）：
   a. 文件非空，ffprobe 时长 ≈ root 的 data-duration：
      "D:\\ffmpeg\\bin\\ffprobe.exe" -v error -show_entries format=duration -of csv=p=0 "<成片路径>"
   b. 抽 3-4 帧，确认字幕是亮的（底部字幕带白字）：
      "D:\\ffmpeg\\bin\\ffmpeg.exe" -y -ss <秒> -i "<成片路径>" -frames:v 1 "${RUN_DIR}\\_work\\final_<秒>.png"
      用读取工具看图，有字幕 = 底部有黑底白字胶囊。
4. **导出到输出根下的项目文件夹**（和 Word 稿同放，文件名 07_video.mp4，重跑自动 _v2/_v3；
   同时会从 storyboard 的 publish_title/publish_desc 生成 08_视频号文案.txt）：
   pwsh 运行：python "${SCRIPTS}\\tutorial_build.py" export --run-dir "${RUN_DIR}" --dst-dir "${PROJ_DIR}"

## 返回格式（JSON）
{ "success": boolean, "reused": boolean, "file": "视频完整路径", "exported": "导出后的完整路径", "duration": number, "size_mb": number, "error": "错误信息" }`,
  {
    label: 'render',
    phase: 'Render',
    schema: {
      type: 'object',
      properties: {
        success: { type: 'boolean' },
        reused: { type: 'boolean' },
        file: { type: 'string' },
        exported: { type: 'string' },
        duration: { type: 'number' },
        size_mb: { type: 'number' },
        error: { type: 'string' },
      },
      required: ['success'],
    },
  }
)

if (!render?.success) throw new Error('Render failed: ' + (render?.error || 'unknown'))
log(`Render: ${render.file} (${render.duration}s, ${render.size_mb}MB)${render.reused ? '（复用已有成片）' : ''}`)

return {
  success: true,
  run_dir: RUN_DIR,
  project_dir: PROJ_DIR,
  storyboard: STORYBOARD,
  slots: SLOTS,
  subs: SUBS,
  video_file: render.file || '',
  exported: render.exported || null,
  duration: render.duration || null,
  snapshots: review.snapshots || [],
}
