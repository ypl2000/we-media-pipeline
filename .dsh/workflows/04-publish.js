// META: {"name":"04-publish","description":"发布线（04/04）：把 03_article.md 推到公众号草稿箱。个人未认证订阅号只到草稿箱（不加 --publish）；缺 WECHAT_APP_ID/WECHAT_APP_SECRET 时跳过不报错；publish:false 关掉。封面优先 images_good/ppt_slides/slide_01.png。","phases":[{"title":"Publish"}]}
// ARGS: {"topic":"","output_dir":"","publish":true}
// topic: 本次项目名（必填，<输出根>/<topic> 子目录）
// output_dir: 输出根目录；留空则取 config.json 的 default_output_dir
// publish: false 时整段跳过，不推草稿
//
// 发布线（第 4 段 / 共 4 段）
// 输入：<out_dir>/03_article.md（01 段产出，可用 args.article 覆盖）
//       <out_dir>/images_good/（02 段产出，正文 [[IMG: ...]] 占位符在这里解析）
//       封面：images_good/ppt_slides/slide_01.png → images_good/news_*.jpg
// 输出：公众号后台草稿箱里的一条草稿（media_id + 实际标题）
// 依赖：python、we-media-pipeline/scripts/wechat_draft.py、环境变量 WECHAT_APP_ID / WECHAT_APP_SECRET
//
// 与原 .claude/workflows/run-pipeline.yml 的 Publish 段保持一致：只建草稿不发布、缺凭据跳过、
// publish:false 关闭、中文 JSON 走 UTF-8 明文、微信接口不挂代理。去掉了 resume 与阶段缓存。
// DSH 的 workflow 脚本本身没有文件系统，所有读/写/命令都通过 agent 完成。

const MAX_RETRIES = 3

// args 防御：未传时按空对象处理，所有参数都有默认值
const A = args || {}

phase('Publish')

// ─── 0. 路径解析与前置检查 ────────────────────────────────────────────────────
// 04 是独立一段，不能读 01–03 的变量，所以路径要在这里重新确定（可被 args 覆盖）。

const setup = await agent(
  `为「公众号草稿」这一步确定路径、检查输入是否齐全。只读取和 pwsh 运行，不要写任何文件、不要建目录。

## 参数
- 项目根目录（调用方给了就用，空字符串表示没给）: "${A.project_root || ''}"
- 输出根目录（调用方给了就用，空字符串表示没给）: "${A.output_dir || ''}"
- 项目名（产出子目录名）: "${A.topic || ''}"
- 文章文件（调用方给了就用，空字符串表示没给）: "${A.article || ''}"

## 步骤
1. 项目根目录：上面给了就原样使用；没给就在仓库里用 pwsh 运行 git rev-parse --show-toplevel，stdout 原样作为项目根目录。命令失败就返回 error 并停止。
2. 输出根目录：上面给了就原样使用；没给就运行（路径含空格要加引号）
   python "<项目根目录>/shared/config_loader.py" --get default_output_dir
   stdout 原样作为输出根目录。
3. out_dir = <输出根目录>\\<项目名>。若输出根目录末尾已经是项目名（大小写不敏感），不要重复拼接。
4. 文章文件：上面给了就原样取它，没给就取 out_dir\\03_article.md。用 pwsh 检查文件是否存在。
5. 图片目录：out_dir\\images_good，用 pwsh 检查是否存在。
6. 封面：按优先级取第一个存在的文件
   a. out_dir\\images_good\\ppt_slides\\slide_01.png
   b. out_dir\\images_good\\news_*.jpg 里的一张（横图优先）
   都不存在就把 cover 置空字符串。

## 返回格式（JSON）
{
  "project_root": "项目根目录完整路径",
  "output_root": "输出根目录完整路径（未归一化，原样）",
  "out_dir": "本次项目输出目录完整路径",
  "article_file": "文章完整路径",
  "article_exists": boolean,
  "images_dir": "图片目录完整路径",
  "images_dir_exists": boolean,
  "cover": "封面完整路径（没有就空字符串）",
  "error": "错误信息（如果有）"
}

只做检查，不要修改任何文件。`,
  {
    label: '发布前置检查',
    phase: 'Publish',
    schema: {
      type: 'object',
      properties: {
        project_root: { type: 'string' },
        output_root: { type: 'string' },
        out_dir: { type: 'string' },
        article_file: { type: 'string' },
        article_exists: { type: 'boolean' },
        images_dir: { type: 'string' },
        images_dir_exists: { type: 'boolean' },
        cover: { type: 'string' },
        error: { type: 'string' },
      },
      required: ['project_root', 'out_dir', 'article_file', 'article_exists'],
    },
  }
)

if (setup?.error) throw new Error(`发布前置检查失败: ${setup.error}`)

const PROJECT_ROOT = String(setup.project_root || '').trim().replace(/[\\/]+$/, '')
if (!PROJECT_ROOT) throw new Error('未能确定项目根目录（git rev-parse --show-toplevel 失败）')

// 输出目录必须在仓库外：产物不许写进代码仓库
const _norm = (p) => String(p).replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
const OUT = String(setup.out_dir || '').trim().replace(/[\\/]+$/, '')
if (!OUT) throw new Error('未能确定输出目录（config.json 的 default_output_dir 读取失败）')
if (_norm(OUT).startsWith(_norm(PROJECT_ROOT) + '/') || _norm(OUT) === _norm(PROJECT_ROOT)) {
  throw new Error(`输出目录不能位于代码仓库内: ${OUT}（仓库: ${PROJECT_ROOT}）`)
}

// 路径兜底：setup 漏字段时按目录契约补上
const articleFile = String(setup.article_file || '').trim() || OUT + '\\03_article.md'
const imagesDir = String(setup.images_dir || '').trim() || OUT + '\\images_good'
const coverFile = String(setup.cover || '').trim()

log(`Output: ${OUT}`)
log(`Article: ${articleFile}`)

// publish:false 直接跳过：不检查文章、不推草稿（与原 run-pipeline.yml 行为一致）
if (A.publish === false) {
  log('Publish skipped (publish: false)')
  return {
    success: true,
    stage: 'publish',
    output_dir: OUT,
    article_file: articleFile,
    images_dir: imagesDir,
    cover_file: coverFile,
    publish_ok: false,
    publish_media_id: '',
    publish_title: '',
    publish_stage: 'skipped',
    error: '',
  }
}

// 缺文章就停：发布一个不存在的文件没有意义，让调用方先补 01–03 段
if (!setup.article_exists) {
  throw new Error(`发布输入缺失：${articleFile} 不存在（先跑 01–03 段生成 03_article.md）`)
}

// ─── 1. 发布 ─────────────────────────────────────────────────────────────────

let publishOk = false
let publishMediaId = ''
let publishStage = ''
let publishTitle = ''
let publishError = ''

if (!coverFile) {
  // 微信草稿必须带封面，没有候选就别浪费三次重试
  publishStage = 'failed'
  publishError = 'no cover candidate'
  log('Publish failed: 没有封面候选（images_good/ppt_slides/slide_01.png 与 images_good/news_*.jpg 都不存在）')
  log(`手动补封面后重跑: python "${PROJECT_ROOT}\\we-media-pipeline\\scripts\\wechat_draft.py" "${articleFile}" --cover "<封面>" --images-dir "${imagesDir}"`)
} else {
  for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
    try {
      const r = await agent(
        `把文章推到公众号草稿箱（默认只建草稿，不调 --publish，最后一步在后台手动发）。

## 输入
- 文章: ${articleFile}
- 图片目录: ${imagesDir}
- 封面: ${coverFile}
- 脚本: ${PROJECT_ROOT}\\we-media-pipeline\\scripts\\wechat_draft.py

## 步骤
1. 用 pwsh 检查环境变量 WECHAT_APP_ID 和 WECHAT_APP_SECRET 是否都存在（只打印长度，不要打印值）。
   任一缺失 → 直接返回 {"success": true, "skipped": true, "stage": "skipped", "reason": "missing credentials"}，不调脚本。
2. 用 pwsh 运行（一条命令：转换 HTML、上传封面和正文图、建草稿）：
   python "${PROJECT_ROOT}\\we-media-pipeline\\scripts\\wechat_draft.py" "${articleFile}" --cover "${coverFile}" --images-dir "${imagesDir}"
   **不要加 --publish**（未认证个人号没有 freepublish 权限，报 48001）。
3. 脚本往 stdout 打一行 JSON：用 UTF-8 读取并按 errcode 判定成败。
4. 草稿落到后台草稿箱，标题取文章第一行 #（超 21 个汉字脚本会在标点处自动截断）。

## 硬规矩
- **不要给微信接口挂代理**（微信校验真实出口 IP，走代理必挂 40164）。
- 凭据只在环境变量里，不落盘、不写进日志和返回值。
- JSON 里的中文必须是 UTF-8 明文：脚本用 json.dumps(ensure_ascii=False)，不要改成 \\uXXXX 转义；读脚本输出时也不要经过会改编码的管道/重定向，否则草稿标题和正文会全是乱码。
- 报 errcode=40164 是 IP 不在白名单（developers.weixin.qq.com/platform → 公众号 → API IP白名单），改不了就原样报错返回。
- 只读取文章和图片，不要改写 ${articleFile}。

## 返回格式（JSON）
{
  "success": boolean,
  "skipped": boolean,
  "stage": "done" | "token" | "cover" | "content" | "draft" | "skipped",
  "media_id": "草稿 media_id（成功时有）",
  "title": "实际使用的标题",
  "error": "错误信息（如果有）"
}

如果脚本执行失败，抛出错误让流程重试。`,
        {
          label: '推送公众号草稿',
          phase: 'Publish',
          schema: {
            type: 'object',
            properties: {
              success: { type: 'boolean' },
              skipped: { type: 'boolean' },
              stage: { type: 'string' },
              media_id: { type: 'string' },
              title: { type: 'string' },
              error: { type: 'string' },
            },
            required: ['success'],
          },
        }
      )

      if (r?.skipped) {
        publishStage = 'skipped'
        log('Publish skipped: missing WECHAT_APP_ID / WECHAT_APP_SECRET')
        break
      }
      if (r?.success) {
        publishOk = true
        publishMediaId = r.media_id || ''
        publishStage = r.stage || 'done'
        publishTitle = r.title || ''
        log(`Publish done: draft media_id=${publishMediaId}, title="${publishTitle}"`)
        break
      }
      throw new Error(r?.error || 'Publish failed')
    } catch (err) {
      publishError = String(err)
      if (attempt === MAX_RETRIES) {
        // 文章已经产出，发布失败不回滚前 3 段；把命令留给人工重跑
        publishStage = 'failed'
        log(`Publish failed after ${MAX_RETRIES} attempts: ${publishError}`)
        log(`草稿没推进去，手动跑: python "${PROJECT_ROOT}\\we-media-pipeline\\scripts\\wechat_draft.py" "${articleFile}" --cover "${coverFile}" --images-dir "${imagesDir}"`)
        break
      }
      log(`Publish attempt ${attempt} failed: ${publishError}`)
    }
  }
}

log(`\n========== PUBLISH STAGE COMPLETE ==========`)
log(`Output: ${OUT}`)
log(`Article: ${articleFile}`)
log(`Cover: ${coverFile || '（无）'}`)
log(`Publish: ${publishOk ? 'draft ' + publishMediaId : publishStage}`)
log(`下一步：到公众号后台草稿箱检查排版，手动点发布（个人未认证订阅号没有 freepublish 权限）`)
log(`============================================`)

return {
  success: publishOk || publishStage === 'skipped',
  stage: 'publish',
  output_dir: OUT,
  article_file: articleFile,
  images_dir: imagesDir,
  cover_file: coverFile,
  publish_ok: publishOk,
  publish_media_id: publishMediaId,
  publish_title: publishTitle,
  publish_stage: publishStage,
  error: publishOk || publishStage === 'skipped' ? '' : publishError,
}
