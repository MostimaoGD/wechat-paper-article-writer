#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import fitz  # type: ignore
except Exception as exc:  # pragma: no cover - dependency error path
    print("PyMuPDF is required. Install it with: python -m pip install pymupdf", file=sys.stderr)
    print(f"Import error: {exc}", file=sys.stderr)
    raise SystemExit(1)


CAPTION_RE = re.compile(
    r"^\s*((?:fig(?:ure)?s?\.?|table|tab\.|scheme|algorithm|extended\s+data\s+fig\.?|supplementary\s+fig\.?|[\u56fe\u8868])\s*[\w.\-:() ]*)",
    re.IGNORECASE,
)


@dataclass
class TextBlock:
    text: str
    bbox: tuple[float, float, float, float]


def safe_stem(name: str) -> str:
    stem = Path(name).stem
    stem = re.sub(r"[^\w.-]+", "_", stem, flags=re.ASCII).strip("._")
    return stem or "paper"


def default_output_dir(pdf_path: Path) -> Path:
    return Path.cwd() / "paper_summaries" / safe_stem(pdf_path.name)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def extract_text_blocks(page: fitz.Page) -> tuple[list[TextBlock], list[tuple[float, float, float, float]]]:
    text_blocks: list[TextBlock] = []
    image_boxes: list[tuple[float, float, float, float]] = []
    try:
        data = page.get_text("dict")
    except Exception:
        return text_blocks, image_boxes

    for block in data.get("blocks", []):
        bbox_raw = block.get("bbox")
        if not bbox_raw:
            continue
        bbox = tuple(float(v) for v in bbox_raw)
        if block.get("type") == 1:
            image_boxes.append(bbox)
            continue
        if block.get("type") != 0:
            continue
        parts: list[str] = []
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            line_text = "".join(span.get("text", "") for span in spans).strip()
            if line_text:
                parts.append(line_text)
        text = "\n".join(parts).strip()
        if text:
            text_blocks.append(TextBlock(text=text, bbox=bbox))
    return text_blocks, image_boxes


def caption_kind(text: str) -> str:
    low = text.lower().lstrip()
    if low.startswith(("table", "tab.")) or text.lstrip().startswith("\u8868"):
        return "table"
    if low.startswith(("scheme", "algorithm")):
        return "diagram"
    return "figure"


def collect_captions(page_number: int, text: str, text_blocks: list[TextBlock]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    captions: list[dict[str, Any]] = []
    caption_blocks: list[dict[str, Any]] = []
    lines = [line.strip() for line in text.splitlines()]
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line:
            i += 1
            continue
        match = CAPTION_RE.match(line)
        if not match:
            i += 1
            continue

        collected = [line]
        j = i + 1
        while j < len(lines) and lines[j] and not CAPTION_RE.match(lines[j]) and len(" ".join(collected)) < 1200:
            candidate = lines[j]
            if re.match(r"^(abstract|introduction|methods?|results?|discussion|conclusion|references)\b", candidate, re.I):
                break
            collected.append(candidate)
            j += 1

        caption_text = " ".join(collected)
        label = match.group(1).strip()
        captions.append(
            {
                "id": f"p{page_number:03d}_c{len(captions) + 1:02d}",
                "page": page_number,
                "line_index": i,
                "kind": caption_kind(line),
                "label": label,
                "text": caption_text,
            }
        )
        i = max(j, i + 1)

    for block in text_blocks:
        first = block.text.splitlines()[0].strip() if block.text else ""
        if CAPTION_RE.match(first):
            caption_blocks.append(
                {
                    "page": page_number,
                    "kind": caption_kind(first),
                    "text": " ".join(block.text.split()),
                    "bbox": list(block.bbox),
                }
            )

    return captions, caption_blocks


def rect_area(rect: fitz.Rect) -> float:
    return max(0.0, rect.width) * max(0.0, rect.height)


def iou(a: fitz.Rect, b: fitz.Rect) -> float:
    inter = a & b
    inter_area = rect_area(inter)
    if inter_area <= 0:
        return 0.0
    union = rect_area(a) + rect_area(b) - inter_area
    return inter_area / union if union > 0 else 0.0


def nearest_caption(rect: fitz.Rect, page_captions: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float]:
    best: dict[str, Any] | None = None
    best_dist = math.inf
    for caption in page_captions:
        bbox = caption.get("bbox")
        if not bbox:
            continue
        c_rect = fitz.Rect(bbox)
        horizontal_overlap = max(0.0, min(rect.x1, c_rect.x1) - max(rect.x0, c_rect.x0))
        overlap_ratio = horizontal_overlap / max(1.0, min(rect.width, c_rect.width))
        vertical_gap = min(abs(c_rect.y0 - rect.y1), abs(rect.y0 - c_rect.y1))
        dist = vertical_gap - 40.0 * overlap_ratio
        if dist < best_dist:
            best = caption
            best_dist = dist
    return best, best_dist


def save_clip(page: fitz.Page, bbox: tuple[float, float, float, float], path: Path, dpi: int) -> tuple[int, int]:
    rect = fitz.Rect(bbox) & page.rect
    matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    pix = page.get_pixmap(matrix=matrix, clip=rect, alpha=False)
    pix.save(path)
    return pix.width, pix.height


def add_image_candidate(
    *,
    candidates: list[dict[str, Any]],
    page: fitz.Page,
    page_number: int,
    bbox: tuple[float, float, float, float],
    root: Path,
    images_dir: Path,
    dpi: int,
    source: str,
    page_caption_blocks: list[dict[str, Any]],
) -> None:
    rect = fitz.Rect(bbox) & page.rect
    if rect.width < 36 or rect.height < 36:
        return
    area_ratio = rect_area(rect) / max(1.0, rect_area(page.rect))
    if area_ratio < 0.01:
        return

    candidate_id = f"p{page_number:03d}_img{len(candidates) + 1:03d}"
    image_path = images_dir / f"{candidate_id}.png"
    try:
        width, height = save_clip(page, tuple(rect), image_path, dpi)
    except Exception as exc:
        candidates.append(
            {
                "id": candidate_id,
                "kind": "image-crop",
                "page": page_number,
                "path": None,
                "bbox": [round(v, 2) for v in tuple(rect)],
                "confidence": "failed",
                "score": 0,
                "source": source,
                "reason": f"Crop failed: {exc}",
            }
        )
        return

    caption, distance = nearest_caption(rect, page_caption_blocks)
    caption_bonus = 25 if caption and distance < 120 else 10 if caption else 0
    score = min(100.0, 25.0 + area_ratio * 90.0 + caption_bonus)
    if caption and distance < 120 and area_ratio >= 0.04:
        confidence = "high"
    elif area_ratio >= 0.03:
        confidence = "medium"
    else:
        confidence = "low"

    candidates.append(
        {
            "id": candidate_id,
            "kind": "image-crop",
            "page": page_number,
            "path": rel(image_path, root),
            "absolute_path": str(image_path),
            "width_px": width,
            "height_px": height,
            "bbox": [round(v, 2) for v in tuple(rect)],
            "confidence": confidence,
            "score": round(score, 2),
            "source": source,
            "nearest_caption": caption.get("text") if caption else None,
            "reason": "Rendered crop from PDF image block or xref rectangle.",
        }
    )


def render_page_screenshot(page: fitz.Page, page_number: int, root: Path, images_dir: Path, dpi: int) -> dict[str, Any]:
    image_path = images_dir / f"page_{page_number:03d}.png"
    matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    pix.save(image_path)
    return {
        "id": f"p{page_number:03d}_page",
        "kind": "page-screenshot",
        "page": page_number,
        "path": rel(image_path, root),
        "absolute_path": str(image_path),
        "width_px": pix.width,
        "height_px": pix.height,
        "bbox": [round(v, 2) for v in tuple(page.rect)],
        "confidence": "last-resort",
        "score": 20.0,
        "source": "page-render",
        "nearest_caption": None,
        "reason": "Last-resort full-page image; prefer caption-region crops whenever possible.",
    }


def caption_label_key(text: str, fallback: str) -> str:
    match = CAPTION_RE.match(text or "")
    label = match.group(1) if match else fallback
    key = re.sub(r"[^A-Za-z0-9]+", "_", label).strip("_").lower()
    return key[:36] or fallback


def should_ignore_boundary_text(text: str) -> bool:
    stripped = re.sub(r"\s+", " ", text).strip()
    if not stripped:
        return True
    lower = stripped.lower()
    if lower in {"article", "research article"}:
        return True
    if lower.startswith(("http://", "https://", "doi:")):
        return True
    if re.fullmatch(r"\d+", stripped):
        return True
    if "nature communications" in lower or "optics express" in lower:
        return True
    return False


def content_rect_for_page(page: fitz.Page, text_blocks: list[TextBlock]) -> fitz.Rect:
    boxes = [fitz.Rect(block.bbox) for block in text_blocks if not should_ignore_boundary_text(block.text)]
    top_margin = max(40.0, page.rect.height * 0.058)
    if boxes:
        x0 = max(page.rect.x0, min(box.x0 for box in boxes) - 10)
        x1 = min(page.rect.x1, max(box.x1 for box in boxes) + 10)
        if x1 - x0 >= page.rect.width * 0.45:
            return fitz.Rect(x0, page.rect.y0 + top_margin, x1, page.rect.y1 - 24)
    margin = max(18.0, page.rect.width * 0.06)
    return fitz.Rect(page.rect.x0 + margin, page.rect.y0 + top_margin, page.rect.x1 - margin, page.rect.y1 - 24)


def infer_caption_region_bbox(
    page: fitz.Page,
    caption_block: dict[str, Any],
    text_blocks: list[TextBlock],
    image_boxes: list[tuple[float, float, float, float]],
    all_caption_blocks: list[dict[str, Any]],
) -> tuple[float, float, float, float] | None:
    bbox = caption_block.get("bbox")
    if not bbox:
        return None
    caption_rect = fitz.Rect(bbox) & page.rect
    if caption_rect.is_empty:
        return None

    content_rect = content_rect_for_page(page, text_blocks)
    page_height = max(1.0, page.rect.height)
    kind = str(caption_block.get("kind") or "figure").lower()

    other_caption_rects: list[fitz.Rect] = []
    for other in all_caption_blocks:
        if other is caption_block or not other.get("bbox"):
            continue
        rect = fitz.Rect(other["bbox"]) & page.rect
        if not rect.is_empty:
            other_caption_rects.append(rect)

    previous_caption_bottoms = [rect.y1 for rect in other_caption_rects if rect.y1 < caption_rect.y0 - 2]
    next_caption_tops = [rect.y0 for rect in other_caption_rects if rect.y0 > caption_rect.y1 + 2]
    upper_guard = max([content_rect.y0] + previous_caption_bottoms) + 4
    lower_guard = min([content_rect.y1] + next_caption_tops) - 4

    if kind == "table":
        below_blocks: list[fitz.Rect] = []
        for block in text_blocks:
            rect = fitz.Rect(block.bbox) & page.rect
            if rect.y0 <= caption_rect.y1 + 1 or rect.y0 >= lower_guard:
                continue
            if should_ignore_boundary_text(block.text):
                continue
            below_blocks.append(rect)
        below_blocks.sort(key=lambda rect: (rect.y0, rect.x0))
        included: list[fitz.Rect] = []
        last_y = caption_rect.y1
        for rect in below_blocks:
            gap = rect.y0 - last_y
            if included and gap > max(18.0, page_height * 0.025):
                break
            included.append(rect)
            last_y = max(last_y, rect.y1)
        if included:
            x0 = min([caption_rect.x0] + [rect.x0 for rect in included]) - 8
            x1 = max([caption_rect.x1] + [rect.x1 for rect in included]) + 8
            y1 = max(rect.y1 for rect in included) + 8
        else:
            x0 = content_rect.x0
            x1 = content_rect.x1
            y1 = min(lower_guard, caption_rect.y1 + page_height * 0.20)
        y0 = max(content_rect.y0, caption_rect.y0 - 8)
    else:
        caption_text_rects = [caption_rect]
        continuation_candidates: list[fitz.Rect] = []
        continuation_limit = min(lower_guard, caption_rect.y1 + page_height * 0.18)
        for block in text_blocks:
            rect = fitz.Rect(block.bbox) & page.rect
            if rect.is_empty or iou(rect, caption_rect) > 0.80:
                continue
            if rect.y0 < caption_rect.y0 - 4 or rect.y0 > continuation_limit:
                continue
            if should_ignore_boundary_text(block.text):
                continue
            continuation_candidates.append(rect)
        continuation_candidates.sort(key=lambda rect: (rect.y0, rect.x0))
        last_caption_y = caption_rect.y1
        for rect in continuation_candidates:
            gap = rect.y0 - last_caption_y
            if caption_text_rects and gap > max(24.0, page_height * 0.03):
                break
            caption_text_rects.append(rect)
            last_caption_y = max(last_caption_y, rect.y1)

        visual_rects: list[fitz.Rect] = []
        for raw in image_boxes:
            rect = fitz.Rect(raw) & page.rect
            if rect.is_empty:
                continue
            if rect.y1 <= upper_guard or rect.y0 >= caption_rect.y0 + page_height * 0.08:
                continue
            horizontal_overlap = max(0.0, min(rect.x1, content_rect.x1) - max(rect.x0, content_rect.x0))
            if horizontal_overlap <= 0:
                continue
            visual_rects.append(rect)

        if visual_rects:
            x0 = min([rect.x0 for rect in caption_text_rects] + [rect.x0 for rect in visual_rects]) - 8
            x1 = max([rect.x1 for rect in caption_text_rects] + [rect.x1 for rect in visual_rects]) + 8
            y0 = min(rect.y0 for rect in visual_rects) - 8
        else:
            x0 = content_rect.x0
            x1 = content_rect.x1
            y0 = upper_guard
            nearby_above = [
                fitz.Rect(block.bbox)
                for block in text_blocks
                if upper_guard <= fitz.Rect(block.bbox).y1 <= caption_rect.y0 and not should_ignore_boundary_text(block.text)
            ]
            if nearby_above:
                y0 = min(rect.y0 for rect in nearby_above) - 8
        y1 = max(rect.y1 for rect in caption_text_rects) + 8
        x0 = min(x0, content_rect.x0)
        x1 = max(x1, content_rect.x1)

    if kind != "table":
        table_after = [rect.y0 for rect in other_caption_rects if rect.y0 > caption_rect.y1 and rect.y0 < y1 + page_height * 0.15]
        if table_after:
            y1 = min(y1, min(table_after) - 6)

    rect = fitz.Rect(x0, y0, x1, y1) & content_rect & page.rect
    if rect.width < 72 or rect.height < 48:
        return None
    if rect.height > page.rect.height * 0.72:
        if kind == "table":
            rect.y1 = min(rect.y1, caption_rect.y1 + page.rect.height * 0.28)
        else:
            rect.y0 = max(rect.y0, caption_rect.y0 - page.rect.height * 0.42)
    return tuple(rect)


def render_caption_region(
    page: fitz.Page,
    page_number: int,
    caption_block: dict[str, Any],
    text_blocks: list[TextBlock],
    image_boxes: list[tuple[float, float, float, float]],
    all_caption_blocks: list[dict[str, Any]],
    root: Path,
    images_dir: Path,
    dpi: int,
    index: int,
) -> dict[str, Any] | None:
    bbox = infer_caption_region_bbox(page, caption_block, text_blocks, image_boxes, all_caption_blocks)
    if bbox is None:
        return None
    kind = str(caption_block.get("kind") or "figure").lower()
    label = caption_label_key(str(caption_block.get("text") or ""), f"region_{index:02d}")
    candidate_id = f"p{page_number:03d}_{label}_{index:02d}"
    image_path = images_dir / f"{candidate_id}.png"
    width, height = save_clip(page, bbox, image_path, dpi)
    rect = fitz.Rect(bbox)
    area_ratio = rect_area(rect) / max(1.0, rect_area(page.rect))
    confidence = "region-high" if area_ratio <= 0.45 else "region-medium"
    return {
        "id": candidate_id,
        "kind": f"{kind}-region",
        "page": page_number,
        "path": rel(image_path, root),
        "absolute_path": str(image_path),
        "width_px": width,
        "height_px": height,
        "bbox": [round(v, 2) for v in tuple(rect)],
        "confidence": confidence,
        "score": round(max(35.0, 68.0 - area_ratio * 25.0), 2),
        "source": "caption-region-render",
        "nearest_caption": caption_block.get("text"),
        "reason": "Caption-guided page-region crop; avoids full-page screenshot while preserving vector/table content.",
    }


def _block_plain_text(block: dict[str, Any]) -> str:
    parts: list[str] = []
    for line in block.get("lines", []):
        text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
        if text:
            parts.append(text)
    return " ".join(parts).strip()


def infer_paper_info_bbox(page: fitz.Page) -> tuple[float, float, float, float]:
    fallback_bottom = page.rect.y0 + page.rect.height * 0.35
    abstract_y: float | None = None
    affiliation_y: float | None = None

    try:
        blocks = page.get_text("dict").get("blocks", [])
    except Exception:
        blocks = []

    text_blocks: list[tuple[float, str, tuple[float, float, float, float]]] = []
    for block in blocks:
        if block.get("type") != 0 or not block.get("bbox"):
            continue
        text = _block_plain_text(block)
        if not text:
            continue
        y0 = float(block["bbox"][1])
        bbox = tuple(float(v) for v in block["bbox"])
        text_blocks.append((y0, text, bbox))
        if abstract_y is None and re.search(r"\babstract\b", text, re.IGNORECASE):
            abstract_y = y0

    for y0, text, _bbox in sorted(text_blocks):
        if y0 < page.rect.y0 + 140:
            continue
        if abstract_y is not None and y0 >= abstract_y:
            continue
        compact = re.sub(r"\s+", " ", text).strip()
        lower = compact.lower()
        looks_like_affiliation = (
            re.match(r"^\d+\s*[A-Z]", compact) is not None
            or "@" in compact
            or any(term in lower for term in ("university", "institute", "department", "laboratory", "center", "centre", "school", "college", "faculty"))
        )
        if looks_like_affiliation:
            affiliation_y = y0
            break

    if affiliation_y is not None:
        bottom = affiliation_y - 6
    elif abstract_y is not None:
        bottom = abstract_y - 8
    else:
        bottom = fallback_bottom

    bottom = max(page.rect.y0 + 120, min(bottom, page.rect.y0 + page.rect.height * 0.55))

    relevant_bboxes = [bbox for y0, _text, bbox in text_blocks if y0 < bottom]
    if relevant_bboxes:
        left = max(page.rect.x0, min(b[0] for b in relevant_bboxes) - 8)
        right = min(page.rect.x1, max(b[2] for b in relevant_bboxes) + 8)
        if right - left >= page.rect.width * 0.45:
            return (left, page.rect.y0, right, bottom)
    return (page.rect.x0, page.rect.y0, page.rect.x1, bottom)


def render_paper_info_image(page: fitz.Page, root: Path, images_dir: Path, dpi: int) -> dict[str, Any]:
    image_path = images_dir / "paper_info.png"
    bbox = infer_paper_info_bbox(page)
    width, height = save_clip(page, bbox, image_path, dpi)
    return {
        "id": "paper_info",
        "kind": "paper-info-crop",
        "page": 1,
        "path": rel(image_path, root),
        "absolute_path": str(image_path),
        "width_px": width,
        "height_px": height,
        "bbox": [round(v, 2) for v in bbox],
        "confidence": "heuristic",
        "source": "first-page-title-author-crop",
        "reason": "First-page crop intended for the Paper basic information section; it includes journal/header, paper title, and authors while avoiding affiliations or abstract when detectable.",
    }


def metadata_to_jsonable(metadata: dict[str, Any]) -> dict[str, Any]:
    return {str(k): ("" if v is None else str(v)) for k, v in metadata.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract text, captions, and figure candidates from a local paper PDF.")
    parser.add_argument("pdf", help="Path to the local PDF file.")
    parser.add_argument("--output-dir", help="Output directory. Defaults to ./paper_summaries/<pdf-stem>/")
    parser.add_argument("--password", default=None, help="PDF password, if needed.")
    parser.add_argument("--min-text-chars", type=int, default=1000, help="Warn with exit code 2 below this extracted text length.")
    parser.add_argument("--max-candidates", type=int, default=20, help="Maximum crop candidates retained in candidate_figures.json.")
    parser.add_argument("--max-page-screenshots", type=int, default=20, help="Maximum caption-region fallback crops to render. Kept for CLI compatibility.")
    parser.add_argument("--allow-full-page-fallback", action="store_true", help="Also render last-resort full-page screenshots when no caption-region crop can be inferred.")
    parser.add_argument("--image-dpi", type=int, default=220, help="DPI for image crop rendering.")
    parser.add_argument("--page-dpi", type=int, default=160, help="DPI for page screenshot rendering.")
    parser.add_argument("--save-all-page-images", action="store_true", help="Render screenshots for all pages.")
    args = parser.parse_args()

    pdf_path = Path(args.pdf).expanduser().resolve()
    if not pdf_path.exists():
        print(f"PDF not found: {pdf_path}", file=sys.stderr)
        return 1
    if pdf_path.suffix.lower() != ".pdf":
        print(f"Input is not a PDF: {pdf_path}", file=sys.stderr)
        return 1

    root = Path(args.output_dir).expanduser().resolve() if args.output_dir else default_output_dir(pdf_path).resolve()
    images_dir = root / "images"
    root.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []
    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        print(f"Failed to open PDF: {exc}", file=sys.stderr)
        return 1

    if doc.needs_pass:
        if not args.password or not doc.authenticate(args.password):
            print("PDF is encrypted and requires a password.", file=sys.stderr)
            return 1

    paper_info_image: dict[str, Any] | None = None
    try:
        if len(doc) > 0:
            paper_info_image = render_paper_info_image(doc[0], root, images_dir, args.page_dpi)
    except Exception as exc:
        warnings.append(f"Paper info crop failed: {exc}")

    page_entries: list[dict[str, Any]] = []
    all_captions: list[dict[str, Any]] = []
    all_caption_blocks: dict[int, list[dict[str, Any]]] = {}
    all_text_blocks: dict[int, list[TextBlock]] = {}
    all_image_boxes: dict[int, list[tuple[float, float, float, float]]] = {}
    candidates: list[dict[str, Any]] = []
    page_screenshot_numbers: set[int] = set()

    for index, page in enumerate(doc, start=1):
        text = clean_text(page.get_text("text") or "")
        text_blocks, image_boxes = extract_text_blocks(page)
        captions, caption_blocks = collect_captions(index, text, text_blocks)
        all_captions.extend(captions)
        all_caption_blocks[index] = caption_blocks
        all_text_blocks[index] = text_blocks
        all_image_boxes[index] = image_boxes

        page_entries.append(
            {
                "page": index,
                "width_pt": round(page.rect.width, 2),
                "height_pt": round(page.rect.height, 2),
                "char_count": len(text),
                "word_count_estimate": len(re.findall(r"\w+", text)),
                "caption_count": len(captions),
                "image_block_count": len(image_boxes),
                "text": text,
            }
        )

        seen_rects: list[fitz.Rect] = []
        for bbox in image_boxes:
            rect = fitz.Rect(bbox) & page.rect
            if any(iou(rect, old) > 0.80 for old in seen_rects):
                continue
            seen_rects.append(rect)
            add_image_candidate(
                candidates=candidates,
                page=page,
                page_number=index,
                bbox=tuple(rect),
                root=root,
                images_dir=images_dir,
                dpi=args.image_dpi,
                source="text-dict-image-block",
                page_caption_blocks=caption_blocks,
            )

        try:
            for image in page.get_images(full=True):
                xref = image[0]
                for rect in page.get_image_rects(xref):
                    rect = rect & page.rect
                    if any(iou(rect, old) > 0.80 for old in seen_rects):
                        continue
                    seen_rects.append(rect)
                    add_image_candidate(
                        candidates=candidates,
                        page=page,
                        page_number=index,
                        bbox=tuple(rect),
                        root=root,
                        images_dir=images_dir,
                        dpi=args.image_dpi,
                        source=f"xref-{xref}",
                        page_caption_blocks=caption_blocks,
                    )
        except Exception as exc:
            warnings.append(f"Page {index}: xref image scan failed: {exc}")

    candidates.sort(key=lambda item: item.get("score", 0), reverse=True)
    retained_candidates = candidates[: max(0, args.max_candidates)]
    for candidate in retained_candidates[:5]:
        if candidate.get("page"):
            page_screenshot_numbers.add(int(candidate["page"]))

    region_candidates: list[dict[str, Any]] = []
    rendered_regions = 0
    for page_number in sorted(all_caption_blocks):
        if rendered_regions >= max(0, args.max_page_screenshots):
            break
        page = doc[page_number - 1]
        page_region_count = 0
        for caption_index, caption_block in enumerate(all_caption_blocks.get(page_number, []), start=1):
            if rendered_regions >= max(0, args.max_page_screenshots):
                break
            try:
                region = render_caption_region(
                    page=page,
                    page_number=page_number,
                    caption_block=caption_block,
                    text_blocks=all_text_blocks.get(page_number, []),
                    image_boxes=all_image_boxes.get(page_number, []),
                    all_caption_blocks=all_caption_blocks.get(page_number, []),
                    root=root,
                    images_dir=images_dir,
                    dpi=args.page_dpi,
                    index=caption_index,
                )
                if region is None:
                    continue
                region_candidates.append(region)
                rendered_regions += 1
                page_region_count += 1
            except Exception as exc:
                warnings.append(f"Page {page_number}: caption-region crop failed: {exc}")
        if page_region_count == 0 and args.allow_full_page_fallback:
            page_screenshot_numbers.add(page_number)

    if args.save_all_page_images:
        page_screenshot_numbers.update(range(1, len(doc) + 1))

    screenshot_candidates: list[dict[str, Any]] = []
    if args.allow_full_page_fallback or args.save_all_page_images:
        for page_number in sorted(page_screenshot_numbers)[: max(0, args.max_page_screenshots)]:
            try:
                screenshot = render_page_screenshot(doc[page_number - 1], page_number, root, images_dir, args.page_dpi)
                page_captions = [c for c in all_captions if c["page"] == page_number]
                if page_captions:
                    screenshot["nearest_caption"] = page_captions[0]["text"]
                    screenshot["reason"] = "Last-resort full-page fallback for captioned page; prefer caption-region crops."
                screenshot_candidates.append(screenshot)
            except Exception as exc:
                warnings.append(f"Page {page_number}: page screenshot failed: {exc}")

    final_candidates = retained_candidates + region_candidates + screenshot_candidates
    total_chars = sum(entry["char_count"] for entry in page_entries)
    if total_chars < args.min_text_chars:
        warnings.append(
            f"Only {total_chars} text characters were extracted; the PDF may be scanned or image-only. OCR or a better source PDF is recommended."
        )

    metadata = {
        "source_pdf": str(pdf_path),
        "source_pdf_sha256": sha256_file(pdf_path),
        "output_dir": str(root),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "page_count": len(doc),
        "total_text_chars": total_chars,
        "total_captions": len(all_captions),
        "total_figure_candidates": len(final_candidates),
        "paper_info_image": paper_info_image,
        "pdf_metadata": metadata_to_jsonable(doc.metadata or {}),
    }

    full_text_parts = ["# Extracted Full Text", "", f"Source PDF: `{pdf_path}`", ""]
    for entry in page_entries:
        full_text_parts.extend([f"## Page {entry['page']}", "", entry["text"] or "[No extractable text]", ""])
    (root / "full_text.md").write_text("\n".join(full_text_parts), encoding="utf-8")

    caption_lines = ["# Caption List", ""]
    if all_captions:
        for caption in all_captions:
            caption_lines.append(f"- Page {caption['page']} | {caption['kind']} | {caption['text']}")
    else:
        caption_lines.append("No figure or table captions were detected by the heuristic.")
    caption_lines.append("")
    (root / "captions.md").write_text("\n".join(caption_lines), encoding="utf-8")

    write_json(root / "metadata.json", metadata)
    write_json(root / "page_text.json", page_entries)
    write_json(root / "captions.json", all_captions)
    write_json(root / "candidate_figures.json", final_candidates)

    manifest = {
        "status": "low_text_warning" if total_chars < args.min_text_chars else "ok",
        "warnings": warnings,
        "artifacts": {
            "metadata": str(root / "metadata.json"),
            "page_text": str(root / "page_text.json"),
            "full_text": str(root / "full_text.md"),
            "captions_markdown": str(root / "captions.md"),
            "captions_json": str(root / "captions.json"),
            "candidate_figures": str(root / "candidate_figures.json"),
            "paper_info_image": str(root / paper_info_image["path"]) if paper_info_image and paper_info_image.get("path") else None,
            "images_dir": str(images_dir),
        },
        "summary": {
            "pages": len(doc),
            "text_chars": total_chars,
            "captions": len(all_captions),
            "candidate_figures": len(final_candidates),
        },
    }
    write_json(root / "manifest.json", manifest)

    print(f"Output directory: {root}")
    print(f"Pages: {len(doc)}")
    print(f"Extracted text characters: {total_chars}")
    print(f"Captions detected: {len(all_captions)}")
    print(f"Figure candidates: {len(final_candidates)}")
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning}")

    return 2 if total_chars < args.min_text_chars else 0


if __name__ == "__main__":
    raise SystemExit(main())






