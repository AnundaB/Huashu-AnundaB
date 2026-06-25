#!/usr/bin/env python3
"""Universal intake classifier and router for `huashu "<anything>"`."""
from __future__ import annotations

import datetime as _dt
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from local_file_resolver import LocalFileResolution, resolve_local_file


REPO_ROOT = Path(__file__).resolve().parents[1]
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
PDF_EXTENSIONS = {".pdf"}
CODE_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".sh", ".sql", ".html", ".css"}
STRUCTURED_EXTENSIONS = {".json", ".yaml", ".yml", ".toml", ".md", ".txt", ".csv"}
OCR_DEPENDENCY_MODULES = ("paddleocr", "paddle", "fitz")
FENCE_LANGS = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".jsx": "jsx",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".md": "markdown",
    ".txt": "text",
    ".sh": "bash",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".csv": "csv",
}
TYPE_LABELS = {
    ".py": "Python source",
    ".js": "JavaScript source",
    ".ts": "TypeScript source",
    ".tsx": "TSX source",
    ".jsx": "JSX source",
    ".json": "JSON data",
    ".yaml": "YAML data",
    ".yml": "YAML data",
    ".toml": "TOML data",
    ".md": "Markdown text",
    ".txt": "Text file",
    ".sh": "Shell script",
    ".sql": "SQL file",
    ".html": "HTML file",
    ".css": "CSS file",
    ".csv": "CSV data",
}


@dataclass
class IntakeDecision:
    input: str
    detected: str
    route: str
    url: str | None = None
    file_resolution: LocalFileResolution | None = None


def parsed_netloc(url: str) -> str:
    netloc = urllib.parse.urlparse(url).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    if ":" in netloc:
        netloc = netloc.split(":", 1)[0]
    return netloc


def is_url(value: str) -> bool:
    parsed = urllib.parse.urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def github_url_kind(value: str) -> str | None:
    parsed = urllib.parse.urlparse(value)
    if parsed_netloc(value) != "github.com":
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    if len(parts) == 2:
        return "github_repo_url"
    if len(parts) >= 4 and parts[2] == "tree":
        return "github_repo_url"
    if len(parts) >= 4 and parts[2] == "blob":
        return "github_blob_url"
    return "generic_web_url"


def classify_url(value: str) -> IntakeDecision:
    parsed = urllib.parse.urlparse(value)
    netloc = parsed_netloc(value)
    path = parsed.path.lower()
    query = urllib.parse.parse_qs(parsed.query)

    github_kind = github_url_kind(value)
    if github_kind == "github_repo_url":
        return IntakeDecision(value, github_kind, "repository extraction", url=value)
    if github_kind == "github_blob_url":
        return IntakeDecision(value, github_kind, "web/page extraction", url=value)

    if netloc in ("youtube.com", "m.youtube.com", "youtu.be") or netloc.endswith(".youtube.com"):
        if "list" in query and ("/playlist" in path or "v" not in query):
            return IntakeDecision(value, "youtube_playlist_url", "YouTube playlist extraction", url=value)
        return IntakeDecision(value, "youtube_video_url", "YouTube video transcript extraction", url=value)

    if netloc in ("chatgpt.com", "chat.openai.com") or netloc.endswith((".chatgpt.com", ".chat.openai.com")):
        if "/share/" in path or "/c/" in path:
            return IntakeDecision(value, "chatgpt_share_url", "ChatGPT extraction", url=value)

    if netloc in ("x.com", "twitter.com", "mobile.twitter.com") or netloc.endswith((".x.com", ".twitter.com")):
        if "/video/" in path:
            return IntakeDecision(value, "x_video_url", "X video transcript workflow", url=value)
        return IntakeDecision(value, "x_post_url", "X/Twitter post extraction", url=value)

    return IntakeDecision(value, "generic_web_url", "web/page extraction", url=value)


def classify_local(value: str) -> IntakeDecision:
    resolution = resolve_local_file(value)
    if resolution.status == "multiple":
        return IntakeDecision(value, "local_file", "ambiguous local file", file_resolution=resolution)
    if not resolution.ok:
        return IntakeDecision(value, "unknown", "no route", file_resolution=resolution)

    suffix = resolution.path.suffix.lower() if resolution.path else ""
    if suffix in PDF_EXTENSIONS:
        detected = "local_pdf"
        route = "MarkItDown -> OCR fallback if needed"
    elif suffix in IMAGE_EXTENSIONS:
        detected = "local_image"
        route = "OCR extraction"
    elif suffix in CODE_EXTENSIONS:
        detected = "local_code_file"
        route = "text/code Markdown wrapper"
    elif suffix in STRUCTURED_EXTENSIONS:
        detected = "local_structured_file"
        route = "text/code Markdown wrapper"
    else:
        detected = "local_file"
        route = "MarkItDown -> OCR fallback if needed"
    return IntakeDecision(value, detected, route, file_resolution=resolution)


def classify_input(value: str) -> IntakeDecision:
    if is_url(value):
        return classify_url(value)
    return classify_local(value)


def python_executable() -> str:
    venv_python = REPO_ROOT / ".venv" / "bin" / "python3"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable or "python3"


def print_decision(decision: IntakeDecision) -> None:
    print(f"[intake] Input: {decision.input}")
    print(f"[intake] Detected: {decision.detected}")
    print(f"[intake] Route: {decision.route}")


def run_script(script_name: str, args: list[str]) -> int:
    script = REPO_ROOT / "scripts" / script_name
    try:
        return subprocess.run([python_executable(), str(script), *args]).returncode
    except KeyboardInterrupt:
        if script_name == "ocr_extract.py":
            print("\n[abort] OCR interrupted by user.")
        else:
            print("\n[abort] Interrupted by user.")
        return 130


def run_web_url(url: str) -> int:
    sys.path.append(str(REPO_ROOT / "scripts"))
    import huashu_cli

    return 0 if huashu_cli.run_single_page_conversion(url) else 1


def route_pdf_or_general_file(path: Path) -> int:
    if path.suffix.lower() in PDF_EXTENSIONS:
        return route_pdf_file(path)

    sys.path.append(str(REPO_ROOT / "scripts"))
    import huashu_cli

    return huashu_cli.run_local_file_conversion(str(path))


def route_ocr(path: Path) -> int:
    print("[ocr] Running OCR. This may be slow and memory-heavy.")
    print("[ocr] For large PDFs, use --max-pages 1 to test first.")
    return run_script("ocr_extract.py", [str(path)])


def auto_ocr_enabled() -> bool:
    value = os.environ.get("HUASHU_AUTO_OCR", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def ocr_dependencies_available() -> bool:
    return all(importlib.util.find_spec(module_name) is not None for module_name in OCR_DEPENDENCY_MODULES)


def print_optional_ocr_guidance(reason: str) -> None:
    print(f"[pdf] Text extraction looks weak: {reason}")
    print("[ocr] This file appears to need OCR.")
    print("[ocr] OCR is optional and may be heavy on small laptops.")
    print("[ocr] To enable OCR:")
    print("      huashu setup-ocr")
    print("      or python -m pip install -r requirements-ocr.txt")
    print("[ocr] To allow automatic OCR fallback:")
    print('      HUASHU_AUTO_OCR=1 huashu "paper.pdf"')


def route_optional_ocr(path: Path, reason: str, source_label: str = "pdf") -> int:
    if not auto_ocr_enabled():
        if source_label == "pdf":
            print_optional_ocr_guidance(reason)
        else:
            print(f"[ocr] {path.name} appears to need OCR.")
            print("[ocr] OCR is optional and may be heavy on small laptops.")
            print("[ocr] To enable OCR:")
            print("      huashu setup-ocr")
            print("      or python -m pip install -r requirements-ocr.txt")
            print("[ocr] To allow automatic OCR from one-command mode:")
            print(f'      HUASHU_AUTO_OCR=1 huashu "{path}"')
        return 1

    if not ocr_dependencies_available():
        print("[ocr] Automatic OCR was requested with HUASHU_AUTO_OCR=1, but OCR dependencies are missing.")
        print("[ocr] Install them with:")
        print("      huashu setup-ocr")
        print("      or python -m pip install -r requirements-ocr.txt")
        return 2

    print("[ocr] Falling back to OCR...")
    return route_ocr(path)


def pdf_mode_from_env() -> str:
    mode = os.environ.get("HUASHU_PDF_MODE", "auto").strip().lower() or "auto"
    if mode not in {"auto", "text", "ocr"}:
        print(f"[warn] Unsupported HUASHU_PDF_MODE={mode!r}; using auto.")
        return "auto"
    return mode


def markdown_nonspace_count(markdown_text: str) -> int:
    return len(re.sub(r"\s+", "", markdown_text or ""))


def pdf_page_text_stats(pdf_path: Path) -> tuple[int | None, int | None]:
    try:
        import fitz  # type: ignore
    except ImportError:
        return None, None

    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return None, None

    low_text_pages = 0
    try:
        page_count = len(doc)
        for page in doc:
            text = page.get_text() or ""
            if markdown_nonspace_count(text) < 50:
                low_text_pages += 1
        return page_count, low_text_pages
    except Exception:
        return None, None
    finally:
        try:
            doc.close()
        except Exception:
            pass


def suspicious_artifact_ratio(markdown_text: str, chars: int) -> float:
    if chars <= 0:
        return 0.0
    artifact_matches = re.findall(r"(?:cid:\d+|�|□|▯|[^\S\r\n]{20,})", markdown_text or "", re.IGNORECASE)
    return len(artifact_matches) / chars


def looks_like_metadata_only(markdown_text: str, chars: int) -> bool:
    if chars >= 1200:
        return False
    lowered = (markdown_text or "").lower()
    body_signals = (
        "abstract",
        "introduction",
        "background",
        "method",
        "methods",
        "results",
        "discussion",
        "conclusion",
    )
    metadata_signals = ("title", "author", "doi", "references", "bibliography", "keywords")
    return any(signal in lowered for signal in metadata_signals) and not any(signal in lowered for signal in body_signals)


def analyze_pdf_text_quality(pdf_path: Path, markdown_text: str) -> dict[str, object]:
    chars = markdown_nonspace_count(markdown_text)
    nonempty_lines = [line.strip() for line in (markdown_text or "").splitlines() if line.strip()]
    line_count = len(nonempty_lines)
    page_count, low_text_pages = pdf_page_text_stats(pdf_path)
    chars_per_page = (chars / page_count) if page_count else None

    if chars == 0:
        score = 0.0
        reason = "no extracted text"
    elif chars_per_page is not None:
        if chars_per_page >= 1000:
            score = 0.92
            reason = "high text density"
        elif chars_per_page >= 500:
            score = 0.78
            reason = "adequate text density"
        elif chars_per_page >= 200:
            score = 0.52
            reason = "mixed text density"
        elif chars_per_page >= 50:
            score = 0.25
            reason = "too little text per page"
        else:
            score = 0.08
            reason = "too little text per page"
    elif chars >= 5000:
        score = 0.86
        reason = "substantial extracted text"
    elif chars >= 1000:
        score = 0.66
        reason = "moderate extracted text"
    elif chars >= 200:
        score = 0.42
        reason = "short extracted text"
    else:
        score = 0.08
        reason = "too little extracted text"

    artifact_ratio = suspicious_artifact_ratio(markdown_text, chars)
    if artifact_ratio > 0.03:
        score -= 0.25
        reason = "suspicious extraction artifacts"

    if line_count:
        very_short_lines = sum(1 for line in nonempty_lines if len(re.sub(r"\s+", "", line)) <= 2)
        if very_short_lines / line_count > 0.65:
            score -= 0.2
            reason = "fragmented extraction lines"

    if page_count and low_text_pages is not None and page_count > 1:
        low_ratio = low_text_pages / page_count
        if low_ratio >= 0.7:
            score -= 0.2
            reason = "most pages have very low extracted text"
        elif low_ratio >= 0.25 and score >= 0.45:
            score -= 0.1
            reason = "some pages have very low extracted text"

    if looks_like_metadata_only(markdown_text, chars):
        score -= 0.25
        reason = "output looks like metadata without body text"

    score = max(0.0, min(1.0, score))
    if score >= 0.70:
        mode = "text"
        usable = True
    elif score < 0.35:
        mode = "ocr"
        usable = False
    else:
        mode = "hybrid"
        usable = True

    return {
        "mode": mode,
        "usable": usable,
        "score": round(score, 2),
        "reason": reason,
        "page_count": page_count,
        "chars": chars,
        "chars_per_page": round(chars_per_page, 2) if chars_per_page is not None else None,
    }


def format_pdf_quality(label: str, quality: dict[str, object]) -> str:
    parts = [
        f"score={quality['score']}",
        f"chars={quality['chars']}",
    ]
    if quality.get("page_count") is not None:
        parts.append(f"pages={quality['page_count']}")
    if quality.get("chars_per_page") is not None:
        parts.append(f"chars/page={quality['chars_per_page']}")
    if quality.get("reason"):
        parts.append(f"reason={quality['reason']}")
    return f"[pdf] Text extraction quality: {label}, " + ", ".join(parts)


def run_markitdown_text_extraction(path: Path) -> tuple[int, str]:
    any_to_md_script = REPO_ROOT / "scripts" / "any_to_md.py"
    print("[web/file] Converting to clean Markdown...")
    with tempfile.TemporaryDirectory(prefix="huashu-pdf-text-") as tmp_dir:
        temp_md = Path(tmp_dir) / "standard.md"
        try:
            res = subprocess.run([python_executable(), str(any_to_md_script), str(path), "-o", str(temp_md), "--quiet"])
        except KeyboardInterrupt:
            print("\n[abort] Text extraction interrupted by user.")
            return 130, ""
        if res.returncode != 0:
            return res.returncode, ""
        try:
            markdown_text = temp_md.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"[error] Failed to read standard extraction output: {exc}")
            return 1, ""
    return 0, markdown_text


def write_text_extraction_output(path: Path, markdown_text: str) -> Path:
    out_path = markdown_output_path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown_text, encoding="utf-8")

    try:
        sys.path.append(str(REPO_ROOT / "scripts"))
        import output_router

        output_router.register_output(
            output_path=str(out_path),
            source=str(path),
            explicit_type="misc",
            title=path.name,
            status="success",
        )
    except Exception as exc:
        print(f"[warn] Failed to register output in manifest/index: {exc}")

    print("")
    print("Done.")
    print("Markdown:")
    print(out_path)
    return out_path


def route_pdf_file(path: Path) -> int:
    mode = pdf_mode_from_env()
    print(f"[pdf] PDF mode: {mode}")

    if mode == "ocr":
        print("[ocr] Running OCR directly...")
        return route_ocr(path)

    rc, markdown_text = run_markitdown_text_extraction(path)
    if rc != 0:
        if rc == 130 or mode == "text":
            return rc
        return route_optional_ocr(path, "text extraction failed")

    if mode == "text":
        quality = analyze_pdf_text_quality(path, markdown_text)
        print(format_pdf_quality("forced text", quality))
        print("[pdf] Using text extraction output.")
        write_text_extraction_output(path, markdown_text)
        return 0

    quality = analyze_pdf_text_quality(path, markdown_text)
    quality_mode = str(quality["mode"])
    if quality_mode == "text":
        print(format_pdf_quality("strong", quality))
        print("[pdf] Using text extraction output.")
        write_text_extraction_output(path, markdown_text)
        return 0

    if quality_mode == "ocr":
        print(format_pdf_quality("weak", quality))
        return route_optional_ocr(path, str(quality["reason"]))

    print(format_pdf_quality("hybrid", quality))
    print("[pdf] Hybrid page-level OCR is not implemented yet. Using text extraction output.")
    write_text_extraction_output(path, markdown_text)
    return 0


def markdown_output_path(source_path: Path) -> Path:
    sys.path.append(str(REPO_ROOT / "scripts"))
    import output_router

    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^A-Za-z0-9ก-๙._-]+", "-", source_path.stem).strip("-")[:90] or "file"
    return Path(output_router.route_output(str(source_path), f"{stamp}-{slug}.md", "misc"))


def write_text_file_markdown(path: Path) -> Path:
    suffix = path.suffix.lower()
    lang = FENCE_LANGS.get(suffix, "")
    type_label = TYPE_LABELS.get(suffix, "Text file")
    content = path.read_text(encoding="utf-8", errors="replace")
    out_path = markdown_output_path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fence = f"```{lang}".rstrip()
    markdown = (
        f"# {path.name}\n\n"
        f"Source: {path}\n"
        f"Type: {type_label}\n\n"
        f"{fence}\n"
        f"{content.rstrip()}\n"
        "```\n"
    )
    out_path.write_text(markdown, encoding="utf-8")

    try:
        sys.path.append(str(REPO_ROOT / "scripts"))
        import output_router

        output_router.register_output(
            output_path=str(out_path),
            source=str(path),
            explicit_type="misc",
            title=path.name,
            status="success",
        )
    except Exception as exc:
        print(f"[warn] Failed to register text file output: {exc}")

    print("")
    print("Done.")
    print("Markdown:")
    print(out_path)
    return out_path


def print_file_resolution_message(resolution: LocalFileResolution) -> None:
    if resolution.status == "resolved" and resolution.path:
        if resolution.original != str(resolution.path):
            print(f"[file] Resolved {resolution.original} -> {resolution.path}")
        return
    if resolution.status == "multiple":
        print("[file] Multiple matching files found. Please pass the full path:")
        for index, path in enumerate(resolution.matches, start=1):
            print(f"{index}. {path}")
        return
    print(f"[file] {resolution.message}")


def route_decision(decision: IntakeDecision, extra_args: list[str] | None = None) -> int:
    extra = extra_args or []
    if decision.detected == "github_repo_url" and decision.url:
        return run_script("github_repo_extract.py", [decision.url, *extra])
    if decision.detected == "github_blob_url" and decision.url:
        return run_web_url(decision.url)
    if decision.detected == "youtube_playlist_url" and decision.url:
        return run_script("youtube_playlist_extract.py", [decision.url, *extra])
    if decision.detected == "youtube_video_url" and decision.url:
        return run_script("youtube_extract.py", [decision.url, *extra])
    if decision.detected == "chatgpt_share_url" and decision.url:
        return run_script("chatgpt_extract.py", [decision.url, *extra])
    if decision.detected == "x_video_url" and decision.url:
        return run_script("x_video_download.py", [decision.url, *extra])
    if decision.detected == "x_post_url" and decision.url:
        return run_script("x_extract.py", [decision.url, *extra])
    if decision.detected == "generic_web_url" and decision.url:
        return run_web_url(decision.url)

    resolution = decision.file_resolution
    if resolution:
        print_file_resolution_message(resolution)
    if not resolution or not resolution.ok or resolution.path is None:
        return 2 if resolution and resolution.status == "multiple" else 1

    path = resolution.path
    if decision.detected == "local_image":
        return route_optional_ocr(path, "image input", source_label="image")
    if decision.detected in ("local_code_file", "local_structured_file"):
        write_text_file_markdown(path)
        return 0
    if decision.detected in ("local_pdf", "local_file"):
        return route_pdf_or_general_file(path)
    return 1


def run_intake(value: str, extra_args: list[str] | None = None) -> int:
    decision = classify_input(value)
    print_decision(decision)
    return route_decision(decision, extra_args=extra_args)
