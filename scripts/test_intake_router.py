import importlib
from pathlib import Path

import pytest

import intake_router
import local_file_resolver


def test_classifies_url_inputs():
    cases = [
        ("https://github.com/owner/repo", "github_repo_url"),
        ("https://github.com/owner/repo/tree/main", "github_repo_url"),
        ("https://github.com/owner/repo/blob/main/file.py", "github_blob_url"),
        ("https://youtube.com/playlist?list=PL123", "youtube_playlist_url"),
        ("https://www.youtube.com/watch?v=abc12345678", "youtube_video_url"),
        ("https://chatgpt.com/share/abc", "chatgpt_share_url"),
        ("https://x.com/user/status/123", "x_post_url"),
        ("https://x.com/user/status/123/video/1", "x_video_url"),
        ("https://example.com", "generic_web_url"),
    ]

    for value, expected in cases:
        assert intake_router.classify_input(value).detected == expected


def test_classifies_local_files_absolute_and_file_uri(tmp_path):
    pdf = tmp_path / "paper.pdf"
    image = tmp_path / "screenshot.png"
    code = tmp_path / "script.py"
    data = tmp_path / "data.json"
    for path in (pdf, image, code, data):
        path.write_text("x", encoding="utf-8")

    assert intake_router.classify_input(str(pdf)).detected == "local_pdf"
    assert intake_router.classify_input(pdf.as_uri()).detected == "local_pdf"
    assert intake_router.classify_input(str(image)).detected == "local_image"
    assert intake_router.classify_input(str(code)).detected == "local_code_file"
    assert intake_router.classify_input(str(data)).detected == "local_structured_file"


def test_filename_only_lookup_resolves_unique_match(tmp_path, monkeypatch, capsys):
    root = tmp_path / "safe"
    root.mkdir()
    target = root / "paper.pdf"
    target.write_text("x", encoding="utf-8")
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    monkeypatch.setenv("HUASHU_FILE_ROOTS", str(root))

    resolution = local_file_resolver.resolve_local_file("paper.pdf")

    assert resolution.ok
    assert resolution.path == target.resolve()

    decision = intake_router.classify_input("paper.pdf")
    intake_router.print_file_resolution_message(decision.file_resolution)
    captured = capsys.readouterr()
    assert f"[file] Resolved paper.pdf -> {target.resolve()}" in captured.out


def test_current_directory_exact_match_wins_over_safe_root_matches(tmp_path, monkeypatch):
    cwd = tmp_path / "cwd"
    safe = tmp_path / "safe"
    cwd.mkdir()
    safe.mkdir()
    local_readme = cwd / "README.md"
    safe_readme = safe / "README.md"
    local_readme.write_text("local", encoding="utf-8")
    safe_readme.write_text("safe", encoding="utf-8")
    monkeypatch.chdir(cwd)
    monkeypatch.setenv("HUASHU_FILE_ROOTS", str(safe))

    resolution = local_file_resolver.resolve_local_file("README.md")

    assert resolution.ok
    assert resolution.path == local_readme.resolve()


def test_multiple_filename_matches_fail_safely(tmp_path, monkeypatch, capsys):
    root1 = tmp_path / "one"
    root2 = tmp_path / "two"
    root1.mkdir()
    root2.mkdir()
    (root1 / "paper.pdf").write_text("a", encoding="utf-8")
    (root2 / "paper.pdf").write_text("b", encoding="utf-8")
    monkeypatch.setenv("HUASHU_FILE_ROOTS", f"{root1}:{root2}")

    decision = intake_router.classify_input("paper.pdf")
    rc = intake_router.route_decision(decision)

    captured = capsys.readouterr()
    assert rc == 2
    assert "Multiple matching files found" in captured.out
    assert str(root1 / "paper.pdf") in captured.out
    assert str(root2 / "paper.pdf") in captured.out


def test_no_file_match_prints_useful_guidance(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HUASHU_FILE_ROOTS", str(tmp_path / "missing-root"))

    decision = intake_router.classify_input("missing.pdf")
    rc = intake_router.route_decision(decision)

    captured = capsys.readouterr()
    assert rc == 1
    assert "No matching local file found" in captured.out
    assert "HUASHU_FILE_ROOTS" in captured.out


def test_routes_common_url_inputs(monkeypatch):
    calls = []

    def fake_run_script(script_name, args):
        calls.append((script_name, args))
        return 0

    monkeypatch.setattr(intake_router, "run_script", fake_run_script)

    assert intake_router.run_intake("https://github.com/owner/repo") == 0
    assert intake_router.run_intake("https://youtube.com/playlist?list=PL123") == 0
    assert intake_router.run_intake("https://www.youtube.com/watch?v=abc12345678") == 0

    assert calls[0] == ("github_repo_extract.py", ["https://github.com/owner/repo"])
    assert calls[1] == ("youtube_playlist_extract.py", ["https://youtube.com/playlist?list=PL123"])
    assert calls[2] == ("youtube_extract.py", ["https://www.youtube.com/watch?v=abc12345678"])


def test_routes_file_uri_to_ocr_with_resolved_path(tmp_path, monkeypatch):
    image = tmp_path / "screen shot.png"
    image.write_text("x", encoding="utf-8")
    calls = []

    def fake_route_ocr(path):
        calls.append(path)
        return 0

    monkeypatch.setenv("HUASHU_AUTO_OCR", "1")
    monkeypatch.setattr(intake_router, "ocr_dependencies_available", lambda: True)
    monkeypatch.setattr(intake_router, "route_ocr", fake_route_ocr)

    assert intake_router.run_intake(image.as_uri()) == 0
    assert calls == [image.resolve()]


def test_routes_pdf_to_markitdown_then_fallback_path(tmp_path, monkeypatch):
    pdf = tmp_path / "paper.pdf"
    pdf.write_text("x", encoding="utf-8")
    calls = []

    def fake_route_pdf(path):
        calls.append(path)
        return 0

    monkeypatch.setattr(intake_router, "route_pdf_or_general_file", fake_route_pdf)

    assert intake_router.run_intake(str(pdf)) == 0
    assert calls == [pdf.resolve()]


def test_code_file_writes_markdown_with_fenced_block(tmp_path, monkeypatch):
    auto_dir = tmp_path / "auto"
    monkeypatch.setenv("HUASHU_AUTO_DIR", str(auto_dir))

    import output_router

    importlib.reload(output_router)

    script = tmp_path / "script.py"
    script.write_text("def main():\n    return 1\n", encoding="utf-8")

    assert intake_router.run_intake(str(script)) == 0

    outputs = list((auto_dir / "misc").glob("*.md"))
    assert len(outputs) == 1
    markdown = outputs[0].read_text(encoding="utf-8")
    assert "# script.py" in markdown
    assert f"Source: {script.resolve()}" in markdown
    assert "Type: Python source" in markdown
    assert "```python\ndef main():" in markdown


def test_github_blob_routes_to_web_extraction(monkeypatch):
    calls = []

    def fake_run_web(url):
        calls.append(url)
        return 0

    monkeypatch.setattr(intake_router, "run_web_url", fake_run_web)

    url = "https://github.com/owner/repo/blob/main/file.py"
    assert intake_router.run_intake(url) == 0
    assert calls == [url]


def test_pdf_quality_high_chars_per_page_is_strong(tmp_path, monkeypatch):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    markdown = "This is a dense digital PDF body. " * 1200
    monkeypatch.setattr(intake_router, "pdf_page_text_stats", lambda path: (12, 0))

    quality = intake_router.analyze_pdf_text_quality(pdf, markdown)

    assert quality["mode"] == "text"
    assert quality["usable"] is True
    assert quality["score"] >= 0.7
    assert quality["page_count"] == 12
    assert quality["chars_per_page"] > 1000


def test_pdf_route_strong_text_does_not_call_ocr(tmp_path, monkeypatch):
    pdf = tmp_path / "normal.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    markdown = "Meaningful extracted text. " * 500
    written = []

    monkeypatch.delenv("HUASHU_PDF_MODE", raising=False)
    monkeypatch.setattr(intake_router, "pdf_page_text_stats", lambda path: (5, 0))
    monkeypatch.setattr(intake_router, "run_markitdown_text_extraction", lambda path: (0, markdown))
    monkeypatch.setattr(intake_router, "write_text_extraction_output", lambda path, text: written.append((path, text)))
    monkeypatch.setattr(intake_router, "route_ocr", lambda path: pytest.fail("OCR should not run"))

    assert intake_router.route_pdf_file(pdf) == 0
    assert written == [(pdf, markdown)]


@pytest.mark.parametrize("markdown", ["", "   \n\t ", "short text"])
def test_pdf_route_weak_text_does_not_auto_ocr_by_default(tmp_path, monkeypatch, capsys, markdown):
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    calls = []

    monkeypatch.delenv("HUASHU_PDF_MODE", raising=False)
    monkeypatch.delenv("HUASHU_AUTO_OCR", raising=False)
    monkeypatch.setattr(intake_router, "pdf_page_text_stats", lambda path: (8, 8))
    monkeypatch.setattr(intake_router, "run_markitdown_text_extraction", lambda path: (0, markdown))
    monkeypatch.setattr(intake_router, "route_ocr", lambda path: calls.append(path) or 0)

    assert intake_router.route_pdf_file(pdf) == 1
    captured = capsys.readouterr()
    assert calls == []
    assert "This file appears to need OCR" in captured.out
    assert "HUASHU_AUTO_OCR=1" in captured.out


def test_pdf_route_weak_text_calls_ocr_when_auto_ocr_enabled(tmp_path, monkeypatch):
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    calls = []

    monkeypatch.delenv("HUASHU_PDF_MODE", raising=False)
    monkeypatch.setenv("HUASHU_AUTO_OCR", "1")
    monkeypatch.setattr(intake_router, "ocr_dependencies_available", lambda: True)
    monkeypatch.setattr(intake_router, "pdf_page_text_stats", lambda path: (8, 8))
    monkeypatch.setattr(intake_router, "run_markitdown_text_extraction", lambda path: (0, "short text"))
    monkeypatch.setattr(intake_router, "route_ocr", lambda path: calls.append(path) or 0)

    assert intake_router.route_pdf_file(pdf) == 0
    assert calls == [pdf]


def test_pdf_mode_text_forces_text_path(tmp_path, monkeypatch):
    pdf = tmp_path / "forced.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    markdown = "short"
    written = []

    monkeypatch.setenv("HUASHU_PDF_MODE", "text")
    monkeypatch.setattr(intake_router, "pdf_page_text_stats", lambda path: (4, 4))
    monkeypatch.setattr(intake_router, "run_markitdown_text_extraction", lambda path: (0, markdown))
    monkeypatch.setattr(intake_router, "write_text_extraction_output", lambda path, text: written.append((path, text)))
    monkeypatch.setattr(intake_router, "route_ocr", lambda path: pytest.fail("OCR should not run in text mode"))

    assert intake_router.route_pdf_file(pdf) == 0
    assert written == [(pdf, markdown)]


def test_pdf_mode_ocr_forces_ocr_without_markitdown(tmp_path, monkeypatch):
    pdf = tmp_path / "forced.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    calls = []

    monkeypatch.setenv("HUASHU_PDF_MODE", "ocr")
    monkeypatch.setattr(
        intake_router,
        "run_markitdown_text_extraction",
        lambda path: pytest.fail("MarkItDown should not run in OCR mode"),
    )
    monkeypatch.setattr(intake_router, "route_ocr", lambda path: calls.append(path) or 0)

    assert intake_router.route_pdf_file(pdf) == 0
    assert calls == [pdf]
