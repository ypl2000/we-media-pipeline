# 搜索 Query 模板参考

> 本文件是 `web-search-assistant` skill 的支持参考，列出常用搜索场景的 query 模板。

---

## 教程搜索模板

### 编程开发

```
site:github.com "tutorial" <语言/框架>
site:github.com "getting started" <技术>
site:github.com "examples" <库名>
intitle:"tutorial" <主题>
intitle:"入门" <主题>
intitle:"从零开始" <主题>

# Python
site:github.com "tutorial" Python
site:stackoverflow.com python "multiprocessing" OR "threading"

# JavaScript/Node.js
site:github.com "tutorial" "Node.js"
site:docs.npmjs.com <包名>

# AI/ML
site:github.com "tutorial" "LangChain" OR "RAG"
site:arxiv.org <主题>  # 学术论文
```

### 工具软件

```
# 开发工具
site:github.com "tutorial" Docker
site:docs.docker.com <主题>
intitle:"入门" Kubernetes

# 设计工具
site:help.figma.com <功能>
site:affinity.net <主题>

# 效率工具
site:notion.so <主题>
site:support.linear.app <主题>
```

### 学习资源

```
# 视频教程
site:bilibili.com <主题> 教程
site:youtube.com <主题> tutorial

# 付费课程
site:juejin.cn <主题>
site:segmentfault.com <主题>
```

---

## 产品搜索模板

### 评测对比

```
site:sspai.com <产品> 评测
site:zhihu.com "<产品> 怎么样" OR "vs"
site:bilibili.com <产品> 测评

# 对比类
site:zhihu.com "MacBook vs" <其他产品>
site:zhihu.com "<产品A> 还是 <产品B>"
```

### 口碑体验

```
site:toutiao.com <产品> 体验
site:xueqiu.com <产品>  # 雪球，投资相关
site:douban.com <产品>

# 电商评价（参考）
<产品> 怎么样 Reddit
<产品> review Amazon
```

### 官网文档

```
<产品名称> 官网
<产品名称> documentation
<产品名称> manual
```

---

## 文档搜索模板

```
# PDF手册/白皮书
filetype:pdf <主题>
filetype:pdf "user guide" <产品>
filetype:pdf "documentation" <框架>

# GitHub README
site:github.com "README.md" <项目>
site:github.com <项目> "CONTRIBUTING.md"

# API文档
site:developer.github.com <主题>
site:docs.microsoft.com <主题>
site:cloud.google.com <主题>
```

---

## 常用排除词

```
# 排除广告和推广
<主题> -广告 -推广 -软文

# 排除特定来源
<主题> -csdn -简书 -博客园

# 精确匹配
"exact phrase here" <主题>
```

---

## 时间限定

```
# GitHub 最新项目（带年份）
site:github.com "2024" OR "2025" <主题>

# 最近教程
<主题> tutorial 2024
```

---

## 组合示例

```bash
# 组合：GitHub + 教程 + Python + 最新
site:github.com "tutorial" Python "2024"

# 组合：知乎 + 产品对比
site:zhihu.com "iPhone 15 vs" "三星"

# 组合：PDF + 官方文档 + AI
filetype:pdf "TensorFlow" "tutorial"
```
