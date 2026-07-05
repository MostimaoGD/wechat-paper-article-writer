#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import fitz  # type: ignore
except Exception as exc:  # pragma: no cover - dependency error path
    print("PyMuPDF is required for the smoke test.", file=sys.stderr)
    print(f"Import error: {exc}", file=sys.stderr)
    raise SystemExit(1)


SKILL_DIR = Path(__file__).resolve().parents[1]
EXTRACT_SCRIPT = SKILL_DIR / "scripts" / "extract_pdf_context.py"
RENDER_SCRIPT = SKILL_DIR / "scripts" / "render_note_pdf.py"
FINALIZE_SCRIPT = SKILL_DIR / "scripts" / "finalize_note_outputs.py"


def create_test_pdf(pdf_path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    text = (
        "Synthetic Photonics Paper\n\n"
        "Abstract. This small PDF is generated for testing the wechat-paper-article-writer skill. "
        "It contains extractable text, a figure caption, and simple vector graphics.\n\n"
        "1. Introduction\n"
        "The method compares a baseline device with a compact resonant design and reports improved coupling stability.\n\n"
        "2. Results\n"
        "The key result is a simulated efficiency curve and a compact layout sketch."
    )
    page.insert_textbox(fitz.Rect(60, 60, 535, 290), text, fontsize=11, fontname="helv", align=0)
    page.draw_rect(fitz.Rect(100, 330, 495, 555), color=(0.1, 0.2, 0.4), width=1.5)
    page.draw_line(fitz.Point(120, 520), fitz.Point(470, 360), color=(0.0, 0.45, 0.45), width=2)
    page.draw_circle(fitz.Point(225, 430), 38, color=(0.75, 0.2, 0.1), fill=(0.95, 0.65, 0.50), width=1)
    page.insert_text(fitz.Point(112, 580), "Figure 1. Synthetic device layout and efficiency trend used for extraction testing.", fontsize=10, fontname="helv")
    page.insert_text(fitz.Point(112, 615), "Table 1. The synthetic design improves the representative metric from 0.42 to 0.68.", fontsize=10, fontname="helv")

    if pdf_path.exists():
        pdf_path.unlink()
    doc.save(pdf_path)
    doc.close()


def run_command(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, encoding="utf-8", errors="replace", capture_output=True)


def choose_image(extract_dir: Path) -> str:
    candidates_path = extract_dir / "candidate_figures.json"
    if not candidates_path.exists():
        return ""
    candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
    for candidate in candidates:
        path = candidate.get("path")
        if path and (extract_dir / path).exists():
            return path
    return ""


def write_test_note(extract_dir: Path, image_rel: str) -> Path:
    image_block = ""
    if image_rel:
        image_block = f"\n![Figure 1 page-level image]({image_rel})\n"
    else:
        image_block = "\n> Figure placeholder: Figure 1, page 1. Reason: no usable image candidate was generated.\n"

    zh_title = "\u5408\u6210\u8bba\u6587\u7cbe\u8bfb\u6d4b\u8bd5\uff1a\u672c\u5730 PDF \u80fd\u88ab\u62bd\u53d6\u5e76\u5bfc\u51fa\u4e3a\u5fae\u8f6f\u96c5\u9ed1 DOCX"
    note = f"""# {zh_title}

## \u8bba\u6587\u57fa\u672c\u4fe1\u606f

\u8fd9\u662f\u7531 smoke test \u81ea\u52a8\u751f\u6210\u7684\u5408\u6210 PDF\uff0c\u7528\u6765\u9a8c\u8bc1\u6587\u672c\u62bd\u53d6\u3001\u56fe\u50cf\u5019\u9009\u548c DOCX \u5bfc\u51fa\u94fe\u8def\u3002

## \u539f\u6587\u6458\u8981\u7ffb\u8bd1\u6216\u6458\u8981\u91cd\u6784

\u8be5\u6d4b\u8bd5\u8bba\u6587\u63cf\u8ff0\u4e86\u4e00\u4e2a\u7528\u4e8e\u9a8c\u8bc1\u7684\u5149\u5b50\u5668\u4ef6\u793a\u4f8b\uff0c\u5305\u542b\u53ef\u62bd\u53d6\u6587\u672c\u3001\u56fe\u6ce8\u548c\u7b80\u5355\u56fe\u5f62\u3002

## \u4e00\u53e5\u8bdd\u603b\u7ed3

\u5982\u679c\u8fd9\u4efd\u7b14\u8bb0\u80fd\u6b63\u5e38\u751f\u6210 DOCX \u5e76\u5d4c\u5165\u56fe\u7247\uff0c\u8bf4\u660e skill \u7684\u57fa\u7840\u94fe\u8def\u53ef\u7528\u3002

## \u7814\u7a76\u95ee\u9898\u4e0e\u80cc\u666f

\u6d4b\u8bd5\u5173\u6ce8\u672c\u5730 PDF \u662f\u5426\u80fd\u88ab\u7a33\u5b9a\u8bfb\u53d6\uff0c\u5e76\u628a\u8bc1\u636e\u4ea4\u7ed9 Codex \u7ee7\u7eed\u5199\u4e2d\u6587\u7cbe\u8bfb\u603b\u7ed3\u3002

## \u65b9\u6cd5/\u7cfb\u7edf/\u5b9e\u9a8c\u4e3b\u7ebf

\u811a\u672c\u5148\u751f\u6210 PDF\uff0c\u518d\u62bd\u53d6\u5168\u6587\u3001caption \u548c\u5019\u9009\u56fe\u50cf\uff0c\u6700\u540e\u6e32\u67d3\u672c Markdown\u3002

## \u5173\u952e\u7ed3\u679c

\u62bd\u53d6\u94fe\u8def\u5e94\u751f\u6210 `full_text.md`, `captions.json`, `candidate_figures.json` \u548c `images/`\u3002\u6700\u7ec8\u4ea4\u4ed8\u76ee\u5f55\u5e94\u53ea\u5269 Markdown \u548c DOCX\u3002

## \u5173\u952e\u56fe\u8868\u89e3\u8bfb
{image_block}
\u56fe 1 \u7528\u4e8e\u786e\u8ba4\u56fe\u7247\u8def\u5f84\u5728 DOCX \u4e2d\u53ef\u663e\u793a\uff0c\u5e76\u80fd\u5728\u6700\u7ec8 Markdown \u4e2d\u88ab\u5185\u5d4c\u3002

## \u521b\u65b0\u70b9

\u8be5\u6d4b\u8bd5\u4e0d\u8bc4\u4ef7\u79d1\u5b66\u521b\u65b0\uff0c\u53ea\u9a8c\u8bc1\u5de5\u5177\u94fe\u3002

## \u5c40\u9650\u4e0e\u672a\u8bc1\u660e\u4e8b\u9879

\u5408\u6210 PDF \u4e0d\u80fd\u4ee3\u8868\u590d\u6742\u53cc\u680f\u8bba\u6587\u3001\u626b\u63cf\u7248\u8bba\u6587\u6216\u5f02\u5e38\u7f16\u7801 PDF\u3002

## \u5bf9\u7814\u7a76/\u5de5\u7a0b\u7684\u542f\u53d1

\u771f\u5b9e\u4efb\u52a1\u4e2d\u4ecd\u5e94\u7531 Codex \u9605\u8bfb\u8bc1\u636e\u540e\u624b\u5199\u603b\u7ed3\uff0c\u811a\u672c\u53ea\u8d1f\u8d23\u62bd\u53d6\u548c DOCX \u5bfc\u51fa\u3002

## \u662f\u5426\u503c\u5f97\u7cbe\u8bfb\u4e0e\u4e0b\u4e00\u6b65\u5efa\u8bae

\u8fd9\u662f\u6d4b\u8bd5\u6587\u4ef6\uff0c\u4e0d\u9700\u8981\u7cbe\u8bfb\u3002\u4e0b\u4e00\u6b65\u5e94\u5e94\u7528\u5230\u771f\u5b9e\u8bba\u6587 PDF\u3002
"""
    note_path = extract_dir / "note.md"
    note_path.write_text(note, encoding="utf-8")
    return note_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a smoke test for wechat-paper-article-writer scripts.")
    parser.add_argument("--output-dir", default=str(Path.cwd() / "paper_summaries" / "_wechat_paper_article_writer_smoke"), help="Smoke test output directory.")
    args = parser.parse_args()

    out_dir = Path(args.output_dir).expanduser().resolve()
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / "smoke_paper.pdf"
    extract_dir = out_dir / "extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)

    create_test_pdf(pdf_path)
    print(f"Created test PDF: {pdf_path}")

    extract = run_command([sys.executable, str(EXTRACT_SCRIPT), str(pdf_path), "--output-dir", str(extract_dir), "--min-text-chars", "200"])
    print(extract.stdout)
    if extract.stderr:
        print(extract.stderr, file=sys.stderr)
    if extract.returncode not in (0, 2):
        print(f"Extraction failed with exit code {extract.returncode}", file=sys.stderr)
        return extract.returncode

    image_rel = choose_image(extract_dir)
    note_path = write_test_note(extract_dir, image_rel)
    print(f"Wrote test note: {note_path}")

    render = run_command([sys.executable, str(RENDER_SCRIPT), str(note_path), "--output-dir", str(extract_dir)])
    print(render.stdout)
    if render.stderr:
        print(render.stderr, file=sys.stderr)
    if render.returncode != 0:
        print(f"Render failed with exit code {render.returncode}", file=sys.stderr)
        return render.returncode

    finalize = run_command([sys.executable, str(FINALIZE_SCRIPT), str(extract_dir), "--output-basename", "note"])
    print(finalize.stdout)
    if finalize.stderr:
        print(finalize.stderr, file=sys.stderr)
    if finalize.returncode != 0:
        print(f"Finalize failed with exit code {finalize.returncode}", file=sys.stderr)
        return finalize.returncode

    remaining = sorted(p.name for p in extract_dir.iterdir())
    md_text = (extract_dir / "note.md").read_text(encoding="utf-8")
    docx_ok = (extract_dir / "note.docx").exists()
    clean_ok = remaining == ["note.docx", "note.md"]
    embedded_ok = "data:image/" in md_text
    print(f"Smoke result: docx_ok={docx_ok}, clean_ok={clean_ok}, embedded_markdown_image={embedded_ok}, remaining={remaining}")
    return 0 if docx_ok and clean_ok and embedded_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
