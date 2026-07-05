#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import mimetypes
import re
import shutil
import sys
from pathlib import Path

IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
EVIDENCE_FILES = {
    "candidate_figures.json",
    "captions.json",
    "captions.md",
    "full_text.md",
    "manifest.json",
    "metadata.json",
    "page_text.json",
    "render_report.json",
}
EVIDENCE_DIRS = {"images"}


def safe_output_basename(value: str) -> str:
    name = Path(value).name
    if Path(name).suffix.lower() in {".md", ".html", ".docx", ".pdf"}:
        name = Path(name).stem
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip(" ._")
    if not name:
        raise ValueError("Output basename cannot be empty.")
    return name


def is_relative_local_image(ref: str) -> bool:
    lowered = ref.lower()
    return not (
        lowered.startswith("data:")
        or lowered.startswith("http://")
        or lowered.startswith("https://")
        or lowered.startswith("file:")
        or lowered.startswith("#")
        or Path(ref).is_absolute()
    )


def within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def image_mime(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def embed_markdown_images(md_path: Path, root: Path) -> tuple[int, list[str]]:
    text = md_path.read_text(encoding="utf-8")
    embedded = 0
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        nonlocal embedded
        alt = match.group(1)
        ref = match.group(2).strip()
        if not is_relative_local_image(ref):
            return match.group(0)
        image_path = (md_path.parent / ref).resolve()
        if not within(image_path, root) or not image_path.exists() or not image_path.is_file():
            missing.append(ref)
            return match.group(0)
        data = base64.b64encode(image_path.read_bytes()).decode("ascii")
        embedded += 1
        return f"![{alt}](data:{image_mime(image_path)};base64,{data})"

    new_text = IMAGE_RE.sub(replace, text)
    if new_text != text:
        md_path.write_text(new_text, encoding="utf-8")
    return embedded, missing


def safe_remove(path: Path, root: Path, protected: set[Path]) -> bool:
    resolved = path.resolve()
    if resolved in protected:
        return False
    if not within(resolved, root):
        raise RuntimeError(f"Refusing to remove outside output directory: {resolved}")
    if resolved.is_dir():
        shutil.rmtree(resolved)
        return True
    if resolved.exists():
        resolved.unlink()
        return True
    return False


def visible_names(root: Path) -> list[str]:
    return sorted(p.name for p in root.iterdir())


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize a paper note directory so only Markdown and DOCX deliverables remain.")
    parser.add_argument("output_dir", help="Directory containing the note, DOCX, images, and extraction evidence.")
    parser.add_argument("--output-basename", "--basename", dest="basename", help="Base filename without extension. Defaults to note if present or the only Markdown file.")
    parser.add_argument("--no-embed-markdown-images", action="store_true", help="Do not convert local Markdown image links to embedded data URIs before cleanup.")
    parser.add_argument("--allow-missing-docx", action="store_true", help="Do not fail when the DOCX is missing.")
    args = parser.parse_args()

    root = Path(args.output_dir).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        print(f"Output directory not found: {root}", file=sys.stderr)
        return 1

    if args.basename:
        basename = safe_output_basename(args.basename)
    else:
        markdown_files = sorted(p for p in root.glob("*.md") if p.name not in EVIDENCE_FILES)
        if (root / "note.md").exists():
            basename = "note"
        elif len(markdown_files) == 1:
            basename = markdown_files[0].stem
        else:
            print("Could not infer note basename; pass --output-basename.", file=sys.stderr)
            return 1

    md_path = root / f"{basename}.md"
    docx_path = root / f"{basename}.docx"
    if not md_path.exists():
        print(f"Markdown deliverable not found: {md_path}", file=sys.stderr)
        return 1
    if not docx_path.exists() and not args.allow_missing_docx:
        print(f"DOCX deliverable not found: {docx_path}", file=sys.stderr)
        return 1

    embedded = 0
    missing: list[str] = []
    if not args.no_embed_markdown_images:
        embedded, missing = embed_markdown_images(md_path, root)

    protected = {md_path.resolve()}
    if docx_path.exists():
        protected.add(docx_path.resolve())

    targets: list[Path] = []
    for name in EVIDENCE_FILES:
        targets.append(root / name)
    for name in EVIDENCE_DIRS:
        targets.append(root / name)
    for suffix in (".html", ".pdf"):
        targets.append(root / f"{basename}{suffix}")
        targets.append(root / f"note{suffix}")

    removed: list[str] = []
    for target in targets:
        if target.exists() and safe_remove(target, root, protected):
            removed.append(target.name)

    allowed = {md_path.name}
    if docx_path.exists():
        allowed.add(docx_path.name)
    leftovers = [name for name in visible_names(root) if name not in allowed]

    print(f"Embedded Markdown images: {embedded}")
    if missing:
        print("Missing image refs left unchanged: " + ", ".join(missing))
    print("Removed: " + (", ".join(sorted(removed)) if removed else "none"))
    print("Remaining: " + ", ".join(visible_names(root)))
    if leftovers:
        print("Unexpected remaining items: " + ", ".join(leftovers), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
