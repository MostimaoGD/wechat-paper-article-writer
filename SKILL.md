---
name: wechat-paper-article-writer
description: Extract local academic paper PDFs into evidence bundles and guide Codex to write Chinese WeChat public-account style article drafts with key figures plus Markdown and DOCX outputs. Use when the user provides PDF file paths, a folder path, or asks to turn papers/literature in the current project or workspace into public-account articles, Chinese article drafts, figure/table interpretations, Markdown drafts, Word/DOCX documents, or per-paper public-account posts. Do not use for API-based LLM pipelines, OpenAI API calls, or project-specific paper radar pushes.
---

# WeChat Paper Article Writer

## Purpose

Use this skill to turn local paper PDFs into Chinese WeChat public-account style article drafts. The bundled scripts only discover PDFs, extract evidence, image candidates, and render outputs; the current Codex session must write the substantive article from the extracted PDF evidence.

Do not call OpenAI API or any other LLM API. Do not invent a summary when the PDF text or figure evidence is insufficient.

## Workflow

1. Resolve the input PDFs before extraction.

- If the user gives one or more PDF file paths, use those files.
- If the user gives a folder path, recursively search that folder for `*.pdf` files.
- If the user says the papers are in the current project/workspace/current folder, recursively search the current working directory or workspace root. Do not only inspect `work/`, `outputs/`, or other guessed subdirectories.
- If the user gives a title, filename fragment, or asks to search Zotero, use `--name "<fragment>"` and optionally `--include-zotero`.
- If no PDFs are found, report the exact root(s) searched and ask for a PDF or folder path, or offer to search Zotero when appropriate. Do not tell the user that they must move PDFs into the current directory as the only option; absolute local paths and external folder paths are valid inputs. Do not claim the skill failed or fabricate a note.

Use the helper when the input is a folder or ambiguous project/workspace request:

```bash
python C:/Users/Mosti/.codex/skills/wechat-paper-article-writer/scripts/find_paper_pdfs.py "<folder-or-workspace-root>"
```

For many PDFs, process each paper independently unless the user asks to narrow the set. If the user asks for a combined report, write per-paper notes first, then create a concise combined Markdown/DOCX report under `paper_summaries/` that links or references the per-paper deliverables.

If the output directory is not specified, use the current workspace under `paper_summaries/<safe-pdf-stem>/` for each PDF.

2. Check the local environment:

```bash
python C:/Users/Mosti/.codex/skills/wechat-paper-article-writer/scripts/check_environment.py
```

3. Extract PDF context:

```bash
python C:/Users/Mosti/.codex/skills/wechat-paper-article-writer/scripts/extract_pdf_context.py "<paper.pdf>"
```

Use `--output-dir "<dir>"` when the user wants a specific destination. Treat exit code `2` as a scanned/low-text warning: inspect the artifacts, then stop and tell the user OCR or a better PDF is needed unless enough evidence is clearly present.

4. Read the generated temporary evidence bundle before writing:

- `manifest.json`
- `metadata.json`
- `page_text.json`
- `full_text.md`
- `captions.md` and `captions.json`
- `candidate_figures.json`
- `images/`

Treat these files as temporary working evidence. Do not leave them in the final article output directory unless the user explicitly asks to keep extraction artifacts.

5. Select 3 to 5 key figures or tables. Prefer high-confidence image crops. If no reliable crop exists, use `figure-region` or `table-region` caption-guided crops before considering any full-page image. Avoid inserting whole paper pages unless there is truly no usable region crop; if a full page is unavoidable, explicitly call it a last-resort page-level image in the note. Never silently drop a requested or important figure; if no image can be inserted, keep a figure placeholder with the reason.

6. Choose a final note basename. Default to `note` for compatibility, but use a descriptive basename when the user asks or when multiple notes will share an output directory, for example `strip-loaded-lnoi-mpl-reading-note`. Write `<basename>.md` in Chinese under the output directory. Use an H1 that is a one-sentence summary of the paper's contribution, not the literal paper title; keep the official title in Paper basic information. Use these sections, in Chinese headings:

- Paper basic information (insert `images/paper_info.png` as the main paper-info image; do not use a metadata table unless the image is unavailable)
- Abstract translation or reconstructed abstract
- One-sentence summary
- Research question and background
- Method, system, or experiment storyline
- Key results
- Key figure and table interpretation
- Innovations
- Limitations and unproven claims
- Implications for research or engineering

In Paper basic information, insert `![Paper information](images/paper_info.png)` first when available, then add only brief text for missing fields such as DOI; avoid a table. Ground claims in page references such as `(Page 4)` and figure/table captions. Add Markdown image links using paths relative to the Markdown note, for example `![Figure 2 region image](images/p003_fig_2_01.png)`.

7. Export the note to DOCX:

```bash
python C:/Users/Mosti/.codex/skills/wechat-paper-article-writer/scripts/render_note_pdf.py "<output-dir>/<basename>.md" --output-dir "<output-dir>" --output-basename "<basename>"
```

The renderer writes `<basename>.docx` if `python-docx` is available. It does not write HTML or PDF by default; use `--write-html` only for temporary debugging, not as a final deliverable. DOCX text should be normalized to `Microsoft YaHei` for headings, body text, tables, and captions. If DOCX export fails, keep `<basename>.md` and report that DOCX was not generated.

8. Finalize the output directory so it contains only the deliverable Markdown and DOCX:

```bash
python C:/Users/Mosti/.codex/skills/wechat-paper-article-writer/scripts/finalize_note_outputs.py "<output-dir>" --output-basename "<basename>"
```

This embeds local Markdown images as data URIs, then removes `images/`, extraction JSON, `full_text.md`, caption files, report files, and any same-basename HTML/PDF debug outputs. Run this only after DOCX has been generated, because DOCX export needs the local image files before cleanup.

9. Verify the final article output directory contains exactly `<basename>.md` and `<basename>.docx` when DOCX is available. If DOCX export failed, it should contain only `<basename>.md`. Also verify the DOCX embedded images are present and that the Markdown no longer depends on an `images/` folder.

## Figure Policy

- Select 3 to 5 key figures/tables by relevance to the paper's argument, not only by image size.
- Use crop candidates when `candidate_figures.json` gives a high-confidence crop near a caption.
- Use caption-guided `figure-region` or `table-region` crops for vector-heavy figures, tables, or multi-panel figures that cannot be isolated as PDF image blocks.
- Avoid whole-page screenshots by default. Use full-page screenshots only as a last resort, and state "last-resort page-level image" in the caption or surrounding text whenever one is used.
- Keep a visible placeholder and reason when no image can be inserted.

## Output Contract

- Default output directory: `paper_summaries/<safe-pdf-stem>/` under the current working directory.
- Final deliverable files: `<basename>.md` and optional `<basename>.docx`. The default basename is `note`. The final article output directory should contain no `images/` folder, extraction JSON, `full_text.md`, caption files, HTML, PDF, or render report.
- Intermediate evidence: use extraction JSON, full text Markdown, caption lists, `images/paper_info.png`, and figure candidate data while writing; remove them with `finalize_note_outputs.py` after DOCX export unless the user explicitly asks to keep evidence.
- Failure mode: if text extraction is too sparse or the PDF appears scanned, stop before writing the final note and ask for OCR or a better source PDF.
- Scope: do not use `OPENAI_API_KEY`, external LLM APIs, or project-specific `photonics_paper_radar` modules.

## Scripts

- `scripts/check_environment.py`: report Python, PyMuPDF, DOCX, and Markdown conversion availability.
- `scripts/find_paper_pdfs.py`: recursively find local paper PDFs from a file, folder, current workspace, or optional Zotero storage hint.
- `scripts/extract_pdf_context.py`: extract text, metadata, captions, image crops, page screenshots, and a manifest.
- `scripts/render_note_pdf.py`: convert a Markdown note to same-basename DOCX when local backends are available; optional `--write-html` is only for debugging. The script name is kept for compatibility.
- `scripts/finalize_note_outputs.py`: embed local Markdown images and remove intermediate evidence so the article output directory contains only MD/DOCX deliverables.
- `scripts/quick_smoke_test.py`: create a tiny synthetic paper PDF, run extraction, render a Chinese Markdown note with an image, finalize the directory, and verify only MD/DOCX remain.



