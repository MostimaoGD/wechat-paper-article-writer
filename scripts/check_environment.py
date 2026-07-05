#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import sys
from typing import Any


def module_available(import_name: str) -> bool:
    return importlib.util.find_spec(import_name) is not None


def get_fitz_status() -> dict[str, Any]:
    status: dict[str, Any] = {"available": False, "version": None, "error": None}
    if not module_available("fitz"):
        return status
    try:
        import fitz  # type: ignore

        status["available"] = True
        status["version"] = getattr(fitz, "__doc__", "").splitlines()[0] if getattr(fitz, "__doc__", None) else "unknown"
    except Exception as exc:  # pragma: no cover - defensive environment check
        status["error"] = str(exc)
    return status


def build_report() -> dict[str, Any]:
    report: dict[str, Any] = {
        "python": {
            "executable": sys.executable,
            "version": sys.version.split()[0],
            "ok": sys.version_info >= (3, 9),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "pymupdf": get_fitz_status(),
        "markdown_module": {"available": module_available("markdown")},
        "python_docx": {"available": module_available("docx")},
    }
    report["ok_for_extraction"] = bool(report["python"]["ok"] and report["pymupdf"]["available"])
    report["ok_for_docx_export"] = bool(report["python_docx"]["available"])
    return report


def print_human(report: dict[str, Any]) -> None:
    def line(label: str, ok: bool, detail: str = "") -> None:
        prefix = "[OK]" if ok else "[MISSING]"
        if detail:
            print(f"{prefix} {label}: {detail}")
        else:
            print(f"{prefix} {label}")

    line("Python >= 3.9", report["python"]["ok"], f"{report['python']['version']} at {report['python']['executable']}")
    pymupdf = report["pymupdf"]
    line("PyMuPDF / fitz", pymupdf["available"], pymupdf.get("version") or pymupdf.get("error") or "not installed")
    line("Python markdown module", report["markdown_module"]["available"], "optional; only used for --write-html debug output; fallback renderer exists")
    line("python-docx", report["python_docx"]["available"], "required for DOCX export")

    if not report["ok_for_extraction"]:
        print("\nExtraction is not ready. Install PyMuPDF in the active Python environment.")
    elif not report["ok_for_docx_export"]:
        print("\nExtraction is ready. DOCX export is not ready; install python-docx.")
    else:
        print("\nExtraction and DOCX export checks are ready.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check local dependencies for wechat-paper-article-writer.")
    parser.add_argument("--json", action="store_true", help="Print a JSON report instead of human-readable text.")
    args = parser.parse_args()

    report = build_report()
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print_human(report)
    return 0 if report["ok_for_extraction"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
