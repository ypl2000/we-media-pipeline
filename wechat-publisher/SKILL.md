---
name: wechat-publisher
description: Push a Markdown article + cover image into a WeChat Official Account (公众号) draft box via the official cgi-bin API. Use when the user wants to publish/send an article to 公众号, put it in the 草稿箱, or wants a WeChat-ready HTML preview without opening the MP backend. Draft-only by default; freepublish is opt-in.
---

# 公众号发布（WeChat Publisher）

把 Markdown 文章 + 封面图直推公众号草稿箱，用微信官方 `/cgi-bin` 接口，不进后台、不手动拖图。

## When to Use

- 文章跑完流水线，想直接进草稿箱（替代人工拖 docx 进后台）
- 想先看看微信里的排版长什么样（`--preview`，不调接口、不需要凭据）

## Quick Start

```bash
# 1) 先本地预览（不需要凭据）
python we-media-pipeline/scripts/wechat_draft.py "输出目录/03_article.md" \
    --images-dir "输出目录/images_good" --preview preview.html

# 2) 推到草稿箱
python we-media-pipeline/scripts/wechat_draft.py "输出目录/03_article.md" \
    --cover "输出目录/images_good/cover.png" \
    --images-dir "输出目录/images_good" \
    --title "文章标题" --author "作者名"
```

正文图片用文章里的 `[[IMG: ...]]` 占位符，在 `--images-dir` 里解析（和 docx 导出同一套逻辑）。
`--cover` 省略时会在图片目录和文章所在目录里找 `cover.png` / `cover.jpg`。

## 凭据

只从环境变量读，不落盘、不进日志、不出现在返回里：

```sh
export WECHAT_APP_ID=wx______________
export WECHAT_APP_SECRET=______________
export WECHAT_AUTHOR=作者名            # 可选
```

公众号后台要先做两件事，否则一定失败：

1. **IP 白名单** —— 设置与开发 → 基本配置 → IP 白名单，把本机外网出口 IP 加进去。
   报 `errcode=40164` 就是漏了这步。
2. **接口权限** —— 订阅号需要认证才有 `draft/add` 权限。

脚本**不走代理**调微信接口（微信校验真实出口 IP，走代理必然对不上）。

## 发布模式

| 模式 | 命令 | 行为 |
|---|---|---|
| 草稿箱（默认） | 默认 | 只调 `draft/add`，落到后台草稿箱，你还能检查、微调、手动发 |
| 直接发布 | `--publish` | 额外调 `freepublish/submit`。**慎用**：API 发布和后台手动发布的首页可见性并不总是一致 |

## 返回

```json
{"ok": true, "stage": "done", "media_id": "xxx", "publish_id": "", "article_url": "", "title": "标题", "error": ""}
```

`stage` 说明卡在哪一步：

| stage | 含义 | 常见原因 |
|---|---|---|
| `token` | 拿 access_token | appid/secret 错（40013）、IP 不在白名单（40164）、订阅号没认证（48001） |
| `cover` | 封面上传 | 封面不是 jpg/png 或超过 10MB |
| `content` | 正文转换 | 正文图上传失败（单图超过 1MB 会自动转码压缩） |
| `draft` | 建草稿 | 标题过长、正文被拒 |
| `publish` | 提交发布 | **草稿已存好**，去后台手动发即可 |

## 已实测的硬限制（按 UTF-8 字节算，不是字符）

| 字段 | 上限 | 说明 |
|---|---|---|
| 标题 | **64 字节 ≈ 21 个汉字** | 超了脚本会断在标点处截断；建议发布前手动给短标题 |
| 摘要 digest | 120 字节 ≈ 40 字 | 自动取首段 |
| **作者 author** | **8 字节 ≈ 2 个汉字** | 「AI不够酷」这种 4 字名会被拒（45110），默认留空 |
| 正文 content | 20000 字符（含 HTML 标签） | 长文注意 |

## 已验证的账号事实（2026-11 实测）

- **个人主体、未认证的订阅号也能用 `draft/add` 建草稿**（2025-07 被收回的是 `freepublish` 发布权限，不是草稿箱）——所以这条链路个人号可用，最后一步发布手动点。
- IP 白名单入口：**developers.weixin.qq.com/platform** → 我的业务与服务 → 公众号 → 基础信息/开发 → 「API IP白名单 → 设置名单」，保存要管理员扫码，生效有 1–5 分钟延迟。
- `freepublish`（`--publish`）在未认证个人号上预期报 48001，别用。

## 已踩过的坑

- **JSON 里的中文必须 UTF-8 明文发**：`requests` 的 `json=` 参数默认 `ensure_ascii=True`，会把中文转成 `\uXXXX`，微信服务端**不解码**，草稿正文全是 `唤` 字面量乱码。脚本已用 `json.dumps(ensure_ascii=False).encode('utf-8')` + `data=` 发送，别改回 `json=`。
- 解析微信响应也别用 `resp.json()`（无 charset 时按 ISO-8859-1 解，中文 errmsg 花掉），用 `resp.content.decode('utf-8')`。
- 作者名超 8 字节报 `45110`，不是文档上写的更宽的限。

## 注意

- 封面走 `material/add_material`（永久素材，占素材库额度，跑一次存一个，攒多了要去后台删），正文图走 `media/uploadimg`（临时外链），两条路不能混用。
- 正文图上限 1MB，脚本自动用 Pillow 转 JPEG 压缩；封面上限 10MB。
- 微信只认 jpg/png/gif/bmp，webp 会自动转码。
- 正文 HTML 只输出微信不删的标签，样式全部内联（微信会剥掉 `<style>`）。
