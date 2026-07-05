# wechat-paper-article-writer

`wechat-paper-article-writer` 是一个全局 Codex skill，用于把本地学术论文 PDF 转成中文公众号格式文章草稿，并输出 Markdown 和 DOCX。

这个 skill 不调用 OpenAI API，也不依赖 `photonics_paper_radar` 项目。脚本只负责查找 PDF、抽取文本证据、抽取图表候选和导出 DOCX；公众号文章正文由当前 Codex 会话基于抽取证据来写。

## 位置

```text
C:\Users\Mosti\.codex\skills\wechat-paper-article-writer
```

关键文件：

- `SKILL.md`：Codex 实际读取的 skill 工作流说明。
- `agents/openai.yaml`：Codex UI 中显示的 skill 名称、简介和默认提示。
- `scripts/`：PDF 查找、抽取、渲染、清理和测试脚本。

## 适用场景

适合这些请求：

- 总结一篇本地论文 PDF。
- 总结某个文件夹或当前项目里的论文。
- 生成中文公众号格式文章草稿。
- 插入关键图表并解释。
- 输出 Markdown 和 Word DOCX。
- 按每篇论文分别生成公众号文章。

不适合这些场景：

- 调用 OpenAI API 或其他 LLM API。
- 替代 OCR 处理扫描版论文。

## 输出结果

默认输出目录：

```text
<current-workspace>\paper_summaries\<safe-pdf-stem>\
```

最终只保留：

```text
<basename>.md
<basename>.docx
```

中间材料例如 `images/`、`metadata.json`、`page_text.json`、`full_text.md`、`captions.md`、`candidate_figures.json` 会在最终清理后删除。Markdown 中的图片会被内嵌为 data URI，因此最终不依赖 `images/` 文件夹。

## 报告结构

生成的中文报告默认包含：

- 论文基本信息
- 摘要翻译或摘要重构
- 一句话总结
- 研究问题与背景
- 方法、系统或实验主线
- 关键结果
- 关键图表解读
- 创新点
- 局限与未证明事项
- 对研究或工程的启发

报告标题使用一句话总结风格，不直接复用论文题名。论文正式题名保留在“论文基本信息”部分。

## 典型用法

在 Codex 中可以直接说：

```text
用 wechat-paper-article-writer 把这篇 PDF 写成公众号文章，并输出 md 和 docx
```

或者：

```text
总结当前项目文件夹里的文献，每篇生成一篇公众号文章
```

如果没有明确 PDF 路径，skill 会先递归查找当前工作区或指定文件夹里的 PDF。

## 手动命令流程

### 1. 检查环境

```powershell
python C:\Users\Mosti\.codex\skills\wechat-paper-article-writer\scripts\check_environment.py
```

主要检查：

- Python 版本
- PyMuPDF / `fitz`
- `python-docx`
- 可选 Markdown HTML 渲染依赖

### 2. 查找 PDF

查找某个文件夹：

```powershell
python C:\Users\Mosti\.codex\skills\wechat-paper-article-writer\scripts\find_paper_pdfs.py "C:\path\to\folder"
```

按文件名片段查找：

```powershell
python C:\Users\Mosti\.codex\skills\wechat-paper-article-writer\scripts\find_paper_pdfs.py "C:\path\to\folder" --name "lithium niobate"
```

同时搜索 Zotero storage：

```powershell
python C:\Users\Mosti\.codex\skills\wechat-paper-article-writer\scripts\find_paper_pdfs.py "C:\path\to\folder" --include-zotero
```

### 3. 抽取论文证据

```powershell
python C:\Users\Mosti\.codex\skills\wechat-paper-article-writer\scripts\extract_pdf_context.py "C:\path\to\paper.pdf" --output-dir "C:\path\to\output"
```

会生成：

- `metadata.json`
- `page_text.json`
- `full_text.md`
- `captions.md`
- `captions.json`
- `candidate_figures.json`
- `images/`

如果文本抽取过少，说明 PDF 可能是扫描版，需要 OCR 或更好的 PDF。

### 4. 由 Codex 写 Markdown 笔记

Codex 应阅读抽取材料后写 `<basename>.md`。正文必须基于证据包，不应凭空总结。

图片引用使用相对路径，例如：

```markdown
![Figure 2 region image](images/p003_fig_2_01.png)
```

### 5. 导出 DOCX

```powershell
python C:\Users\Mosti\.codex\skills\wechat-paper-article-writer\scripts\render_note_pdf.py "C:\path\to\output\<basename>.md" --output-dir "C:\path\to\output" --output-basename "<basename>"
```

脚本名保留为 `render_note_pdf.py` 是为了兼容旧命名；默认不会导出 PDF，只导出 DOCX。Word 字体会尽量统一为 Microsoft YaHei。

### 6. 清理最终输出目录

```powershell
python C:\Users\Mosti\.codex\skills\wechat-paper-article-writer\scripts\finalize_note_outputs.py "C:\path\to\output" --output-basename "<basename>"
```

清理后目录应只剩：

```text
<basename>.md
<basename>.docx
```

## 图表策略

优先级：

1. 高置信度 PDF 图像裁剪。
2. `figure-region` 或 `table-region` caption 引导区域裁剪。
3. 只有完全没有可用区域图时，才使用整页截图作为 last-resort page-level image。

默认不应把整页论文截图当作关键图插入。无法插入图像时，应保留图表占位和原因，不要静默丢图。

## 脚本说明

| 脚本 | 用途 |
| --- | --- |
| `check_environment.py` | 检查 Python、PyMuPDF、DOCX 渲染依赖 |
| `find_paper_pdfs.py` | 从文件、文件夹、当前项目或 Zotero 中查找 PDF |
| `extract_pdf_context.py` | 抽取全文、逐页文本、caption、图表候选和论文信息截图 |
| `render_note_pdf.py` | 把 Markdown 笔记导出为 DOCX |
| `finalize_note_outputs.py` | 内嵌 Markdown 图片并清理中间文件 |
| `quick_smoke_test.py` | 运行最小链路测试 |

## 测试

校验 skill：

```powershell
python C:\Users\Mosti\.codex\skills\.system\skill-creator\scripts\quick_validate.py C:\Users\Mosti\.codex\skills\wechat-paper-article-writer
```

期望输出：

```text
Skill is valid!
```

运行 smoke test：

```powershell
python C:\Users\Mosti\.codex\skills\wechat-paper-article-writer\scripts\quick_smoke_test.py
```

期望结果：

- 能创建临时测试 PDF。
- 能抽取文本和图像。
- 能生成 `note.md` 和 `note.docx`。
- 最终目录只剩 Markdown 和 DOCX。

## 常见问题

### 找不到 PDF

先确认查找根目录是否正确：

```powershell
python C:\Users\Mosti\.codex\skills\wechat-paper-article-writer\scripts\find_paper_pdfs.py "<folder>"
```

如果论文在 Zotero，可以加：

```powershell
--include-zotero
```

### PDF 是扫描版

如果抽取文本字符数很少，skill 应停止并提示需要 OCR。不要生成假总结。

### DOCX 未生成

通常是缺少 `python-docx`。运行环境检查脚本确认：

```powershell
python C:\Users\Mosti\.codex\skills\wechat-paper-article-writer\scripts\check_environment.py
```

### 图片变成整页论文

当前策略默认使用 caption 引导区域裁剪。若仍出现整页截图，应检查 `candidate_figures.json` 中该图的 `kind` 是否是 `page-screenshot`，并优先改用相邻的 `figure-region` 或 `table-region`。

## 维护注意

- 修改工作流时优先改 `SKILL.md`。
- 修改脚本后至少运行 `python -m py_compile <script>`。
- 大改后运行 `quick_validate.py` 和 `quick_smoke_test.py`。
- 不要把中间抽取结果长期保留在最终报告目录，除非用户明确要求。
