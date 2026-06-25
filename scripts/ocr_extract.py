#!/usr/bin/env python3
"""
ocr_extract.py - Optional OCR extraction for image and scanned document inputs.

PaddleOCR is imported only when the user explicitly runs this script or the
Huashu CLI routes to it, so lightweight/core installs can still fail with clear
diagnostics instead of stack traces.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import importlib
import re
import sys
import tempfile
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
PDF_SUFFIXES = {".pdf"}

OCR_INSTALL_HELP = """\
OCR dependencies are missing.

If you installed Huashu with the lightweight/core install, run:

  python -m pip install -r requirements-ocr.txt

For the full recommended install, run:

  python -m pip install -r requirements.txt

Then verify:

  huashu doctor
"""
PADDLEOCR_INSTALL_HELP = OCR_INSTALL_HELP

PYMUPDF_INSTALL_HELP = """\
OCR dependencies are missing.

If you installed Huashu with the lightweight/core install, run:

  python -m pip install -r requirements-ocr.txt

For the full recommended install, run:

  python -m pip install -r requirements.txt

Then verify:

  huashu doctor
"""


@dataclass
class OcrPage:
    label: str
    text: str
    confidence: float | None = None


@dataclass
class OcrResult:
    source_path: Path
    engine: str
    status: str
    pages: list[OcrPage] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def confidence(self) -> float | None:
        scores = [page.confidence for page in self.pages if page.confidence is not None]
        if not scores:
            return None
        return mean(scores)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract text from an image or scanned PDF using optional OCR.",
    )
    parser.add_argument("source", help="Image or PDF path to OCR.")
    parser.add_argument(
        "--engine",
        default="paddleocr",
        choices=("paddleocr",),
        help="OCR engine to use. Currently only paddleocr is supported.",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output Markdown path. If omitted, writes through Huashu's auto output router.",
    )
    parser.add_argument(
        "--lang",
        default="en",
        help="PaddleOCR language code, for example en, ch, japan. Default: en.",
    )
    parser.add_argument(
        "--pdf-dpi",
        type=int,
        default=300,
        help="DPI used when rendering PDF pages before OCR.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress non-error progress output.",
    )
    return parser.parse_args(argv)


def load_paddleocr_class():
    try:
        module = importlib.import_module("paddleocr")
    except ImportError as exc:
        raise RuntimeError(PADDLEOCR_INSTALL_HELP) from exc

    paddleocr_class = getattr(module, "PaddleOCR", None)
    if paddleocr_class is None:
        raise RuntimeError(
            "The installed paddleocr package does not expose PaddleOCR. "
            "Try upgrading it with: pip install --upgrade paddleocr"
        )
    return paddleocr_class


def normalize_source_path(source: str) -> Path:
    parsed = urllib.parse.urlparse(source)
    if parsed.scheme == "file":
        if parsed.netloc and parsed.netloc not in ("localhost", "127.0.0.1"):
            path_text = f"//{parsed.netloc}{parsed.path}"
        else:
            path_text = parsed.path
        return Path(urllib.parse.unquote(path_text)).expanduser().resolve()
    return Path(source).expanduser().resolve()


def render_pdf_pages(pdf_path: Path, dpi: int) -> tuple[list[Path], tempfile.TemporaryDirectory[str]]:
    try:
        fitz = importlib.import_module("fitz")
    except ImportError as exc:
        raise RuntimeError(PYMUPDF_INSTALL_HELP) from exc

    tmp = tempfile.TemporaryDirectory(prefix="huashu-pdf-ocr-")
    page_paths: list[Path] = []
    try:
        doc = fitz.open(str(pdf_path))
        matrix = fitz.Matrix(dpi / 72, dpi / 72)
        for index, page in enumerate(doc, start=1):
            out_path = Path(tmp.name) / f"page_{index:04d}.png"
            page.get_pixmap(matrix=matrix).save(str(out_path))
            page_paths.append(out_path)
        doc.close()
    except Exception:
        tmp.cleanup()
        raise
    return page_paths, tmp


def build_paddleocr(lang: str):
    paddleocr_class = load_paddleocr_class()
    try:
        return paddleocr_class(
            lang=lang,
            use_doc_orientation_classify=True,
            use_doc_unwarping=True,
            use_textline_orientation=True,
        )
    except TypeError:
        return paddleocr_class(lang=lang)


def run_paddleocr_on_image(ocr: Any, image_path: Path) -> Any:
    if hasattr(ocr, "predict"):
        try:
            return ocr.predict(input=str(image_path))
        except TypeError:
            return ocr.predict(str(image_path))
    if hasattr(ocr, "ocr"):
        return ocr.ocr(str(image_path))
    raise RuntimeError("PaddleOCR object has neither predict() nor ocr().")


def normalize_ocr_result(raw: Any) -> tuple[str, float | None]:
    lines: list[str] = []
    scores: list[float] = []

    def add_text(text: Any, score: Any = None) -> None:
        if not isinstance(text, str):
            return
        cleaned = text.strip()
        if not cleaned:
            return
        lines.append(cleaned)
        if isinstance(score, (int, float)):
            scores.append(float(score))

    def walk(value: Any) -> None:
        if value is None:
            return

        if isinstance(value, dict):
            rec_texts = value.get("rec_texts")
            if isinstance(rec_texts, list):
                rec_scores = value.get("rec_scores")
                for index, text in enumerate(rec_texts):
                    score = None
                    if isinstance(rec_scores, list) and index < len(rec_scores):
                        score = rec_scores[index]
                    add_text(text, score)
                return

            for key in ("text", "transcription", "label"):
                if key in value:
                    add_text(value.get(key), value.get("score") or value.get("confidence"))
                    return

            for nested in value.values():
                walk(nested)
            return

        if isinstance(value, (list, tuple)):
            if len(value) >= 2 and isinstance(value[0], str):
                add_text(value[0], value[1])
                return
            if (
                len(value) >= 2
                and isinstance(value[1], (list, tuple))
                and len(value[1]) >= 2
                and isinstance(value[1][0], str)
            ):
                add_text(value[1][0], value[1][1])
                return
            for item in value:
                walk(item)
            return

        if hasattr(value, "json") and isinstance(value.json, dict):
            walk(value.json)
            return

        if hasattr(value, "to_dict"):
            try:
                walk(value.to_dict())
            except Exception:
                return

    walk(raw)
    return "\n".join(lines), mean(scores) if scores else None


def extract_with_paddleocr(source_path: Path, lang: str, pdf_dpi: int) -> OcrResult:
    suffix = source_path.suffix.lower()
    ocr = build_paddleocr(lang)
    result = OcrResult(source_path=source_path, engine="paddleocr", status="success")

    if suffix in IMAGE_SUFFIXES:
        raw = run_paddleocr_on_image(ocr, source_path)
        text, confidence = normalize_ocr_result(raw)
        if not text:
            result.status = "empty"
            result.warnings.append("PaddleOCR returned no recognized text.")
        result.pages.append(OcrPage(label="Image", text=text, confidence=confidence))
        return result

    if suffix in PDF_SUFFIXES:
        page_dir: tempfile.TemporaryDirectory[str] | None = None
        try:
            page_paths, page_dir = render_pdf_pages(source_path, pdf_dpi)
            if not page_paths:
                result.status = "empty"
                result.warnings.append("PDF rendered with zero pages.")
                return result
            for index, page_path in enumerate(page_paths, start=1):
                raw = run_paddleocr_on_image(ocr, page_path)
                text, confidence = normalize_ocr_result(raw)
                result.pages.append(
                    OcrPage(label=f"Page {index}", text=text, confidence=confidence)
                )
            if not any(page.text.strip() for page in result.pages):
                result.status = "empty"
                result.warnings.append("PaddleOCR returned no recognized text for the PDF.")
            return result
        finally:
            if page_dir is not None:
                page_dir.cleanup()

    result.status = "unsupported"
    result.warnings.append(
        f"Unsupported OCR input extension: {suffix or '(none)'}. "
        "Supported image types: png, jpg, jpeg, webp, bmp, tif, tiff; PDFs require PyMuPDF."
    )
    return result


def result_to_markdown(result: OcrResult) -> str:
    source = str(result.source_path)
    confidence = result.confidence
    confidence_text = f"{confidence:.3f}" if confidence is not None else "n/a"
    warnings = "; ".join(result.warnings) if result.warnings else "None"

    lines = [
        "# OCR Extract",
        "",
        "## Metadata",
        f"- Source: `{source}`",
        f"- OCR engine: `{result.engine}`",
        f"- Page/image count: `{result.page_count}`",
        f"- Status: `{result.status}`",
        f"- Confidence: `{confidence_text}`",
        f"- Notes/warnings: {warnings}",
        "",
        "## Text",
        "",
    ]

    for page in result.pages:
        if result.page_count > 1 or page.label.lower() != "image":
            lines.extend([f"### {page.label}", ""])
        lines.append(page.text.strip() or "_No text recognized._")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9ก-๙._-]+", "-", value).strip("-")
    return slug[:90] or "ocr"


def resolve_output_path(source_path: Path, output: str | None) -> Path:
    if output:
        return Path(output).expanduser().resolve()

    sys.path.append(str(REPO_ROOT / "scripts"))
    import output_router

    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"{stamp}-ocr-{slugify(source_path.stem)}.md"
    return Path(output_router.route_output(str(source_path), filename, "misc"))


def write_and_register(markdown: str, output_path: Path, source_path: Path, status: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")

    try:
        sys.path.append(str(REPO_ROOT / "scripts"))
        import output_router

        output_router.register_output(
            output_path=str(output_path),
            source=str(source_path),
            explicit_type="misc",
            title=f"OCR: {source_path.name}",
            status=status,
        )
    except Exception as exc:
        print(f"[warn] Failed to register OCR output in manifest/index: {exc}", file=sys.stderr)


def run(source: str, engine: str, output: str | None, lang: str, pdf_dpi: int) -> Path:
    source_path = normalize_source_path(source)
    if not source_path.exists():
        raise FileNotFoundError(f"Input file not found: {source_path}")
    if not source_path.is_file():
        raise ValueError(f"Input path is not a file: {source}")

    if engine != "paddleocr":
        raise ValueError(f"Unsupported OCR engine: {engine}")

    result = extract_with_paddleocr(source_path, lang=lang, pdf_dpi=pdf_dpi)
    output_path = resolve_output_path(source_path, output)
    write_and_register(result_to_markdown(result), output_path, source_path, result.status)
    return output_path


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        output_path = run(
            source=args.source,
            engine=args.engine,
            output=args.output,
            lang=args.lang,
            pdf_dpi=args.pdf_dpi,
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (FileNotFoundError, ValueError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - OCR engines raise broad runtime errors.
        print(f"[error] OCR extraction failed: {exc}", file=sys.stderr)
        return 1

    if not args.quiet:
        print(f"[ok] OCR Markdown written to: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
