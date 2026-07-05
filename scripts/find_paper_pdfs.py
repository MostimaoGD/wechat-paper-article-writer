#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except Exception:
                pass


SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024.0 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024.0
    return f"{size} B"


def file_entry(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path),
        "name": path.name,
        "size_bytes": stat.st_size,
        "size": human_size(stat.st_size),
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
    }


def matches_name(path: Path, name_fragment: str | None) -> bool:
    if not name_fragment:
        return True
    return name_fragment.casefold() in path.name.casefold()


def iter_pdf_files(root: Path, max_depth: int, name_fragment: str | None) -> Iterable[Path]:
    root = root.expanduser().resolve()
    if root.is_file():
        if root.suffix.lower() == ".pdf" and matches_name(root, name_fragment):
            yield root
        return
    if not root.exists() or not root.is_dir():
        return

    root_depth = len(root.parts)
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        rel_depth = len(current.parts) - root_depth
        dirnames[:] = [
            name
            for name in dirnames
            if name not in SKIP_DIR_NAMES and not name.startswith(".")
        ]
        if max_depth >= 0 and rel_depth >= max_depth:
            dirnames[:] = []
        for filename in filenames:
            if not filename.lower().endswith(".pdf"):
                continue
            path = current / filename
            if matches_name(path, name_fragment):
                yield path.resolve()


def zotero_storage() -> Path:
    return Path.home() / "Zotero" / "storage"


def unique_roots(raw_roots: list[str], include_zotero: bool) -> list[Path]:
    roots = [Path(item).expanduser() for item in raw_roots] if raw_roots else [Path.cwd()]
    if include_zotero:
        roots.append(zotero_storage())

    seen: set[str] = set()
    unique: list[Path] = []
    for root in roots:
        try:
            resolved = str(root.resolve())
        except Exception:
            resolved = str(root)
        key = resolved.casefold() if os.name == "nt" else resolved
        if key in seen:
            continue
        seen.add(key)
        unique.append(root)
    return unique


def main() -> int:
    configure_stdio()
    parser = argparse.ArgumentParser(description="Find local academic paper PDFs from file or folder roots.")
    parser.add_argument("roots", nargs="*", help="PDF files or folders to search. Defaults to the current working directory.")
    parser.add_argument("--name", help="Case-insensitive filename fragment to match.")
    parser.add_argument("--include-zotero", action="store_true", help="Also search ~/Zotero/storage.")
    parser.add_argument("--max-depth", type=int, default=8, help="Maximum folder depth to recurse from each root. Use -1 for unlimited.")
    parser.add_argument("--max-results", type=int, default=200, help="Maximum results to print.")
    parser.add_argument("--json", action="store_true", help="Write machine-readable JSON.")
    args = parser.parse_args()

    roots = unique_roots(args.roots, args.include_zotero)
    missing_roots = [str(root) for root in roots if not root.expanduser().exists()]

    found: list[Path] = []
    seen_files: set[str] = set()
    for root in roots:
        for path in iter_pdf_files(root, args.max_depth, args.name):
            key = str(path).casefold() if os.name == "nt" else str(path)
            if key in seen_files:
                continue
            seen_files.add(key)
            found.append(path)

    found.sort(key=lambda path: path.name.casefold())
    entries = [file_entry(path) for path in found[: max(0, args.max_results)]]
    truncated = len(found) > len(entries)
    result = {
        "searched_roots": [str(root.expanduser().resolve()) if root.expanduser().exists() else str(root) for root in roots],
        "missing_roots": missing_roots,
        "count": len(found),
        "returned": len(entries),
        "truncated": truncated,
        "pdfs": entries,
    }

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Searched roots:")
        for root in result["searched_roots"]:
            print(f"- {root}")
        if missing_roots:
            print("Missing roots:")
            for root in missing_roots:
                print(f"- {root}")
        if not found:
            print("No PDF files found.")
            return 0
        print(f"Found {len(found)} PDF file(s):")
        for index, entry in enumerate(entries, start=1):
            print(f"{index}. {entry['path']} ({entry['size']}, modified {entry['modified']})")
        if truncated:
            print(f"Results truncated to {len(entries)}. Increase --max-results to show more.")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(130)
