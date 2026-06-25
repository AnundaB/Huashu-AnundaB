import importlib
import os
import sys

import pytest

import huashu_cli
import intake_router
import ocr_extract


def test_load_paddleocr_missing_dependency(monkeypatch):
    def fake_import(name):
        if name == "paddleocr":
            raise ImportError("missing")
        return importlib.import_module(name)

    monkeypatch.setattr(ocr_extract.importlib, "import_module", fake_import)

    with pytest.raises(RuntimeError) as excinfo:
        ocr_extract.load_paddleocr_class()

    assert "OCR dependencies are missing" in str(excinfo.value)
    assert "requirements-ocr.txt" in str(excinfo.value)
    assert "default lightweight install" in str(excinfo.value)
    assert "huashu doctor" in str(excinfo.value)


def test_main_missing_ocr_dependency_gives_clear_error(tmp_path, monkeypatch, capsys):
    image_path = tmp_path / "scan.png"
    image_path.write_bytes(b"fake image")

    def fake_load():
        raise RuntimeError(ocr_extract.PADDLEOCR_INSTALL_HELP)

    monkeypatch.setattr(ocr_extract, "load_paddleocr_class", fake_load)

    rc = ocr_extract.main([str(image_path), "--quiet"])

    captured = capsys.readouterr()
    assert rc == 2
    assert "OCR dependencies are missing" in captured.err
    assert "requirements-ocr.txt" in captured.err
    assert "default lightweight install" in captured.err
    assert "huashu doctor" in captured.err


def test_ocr_success_writes_markdown_through_auto_router(tmp_path, monkeypatch):
    auto_dir = tmp_path / "auto"
    monkeypatch.setenv("HUASHU_AUTO_DIR", str(auto_dir))

    import output_router

    importlib.reload(output_router)

    image_path = tmp_path / "receipt.png"
    image_path.write_bytes(b"fake image")

    class FakePaddleOCR:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def predict(self, input):
            return [
                [
                    [[[0, 0], [1, 0], [1, 1], [0, 1]], ("Total", 0.98)],
                    [[[0, 2], [1, 2], [1, 3], [0, 3]], ("$12.50", 0.92)],
                ]
            ]

    monkeypatch.setattr(ocr_extract, "load_paddleocr_class", lambda: FakePaddleOCR)

    output_path = ocr_extract.run(
        source=str(image_path),
        engine="paddleocr",
        output=None,
        lang="en",
        pdf_dpi=300,
    )

    assert output_path.parent == auto_dir / "misc"
    markdown = output_path.read_text(encoding="utf-8")
    assert "# OCR Extract" in markdown
    assert "- OCR engine: `paddleocr`" in markdown
    assert "- Status: `success`" in markdown
    assert "Total\n$12.50" in markdown
    assert (auto_dir / "manifest.csv").exists()
    assert (auto_dir / "index.md").exists()


def test_pdf_missing_renderer_is_reported(tmp_path, monkeypatch):
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    class FakePaddleOCR:
        def __init__(self, **kwargs):
            pass

    def fake_import(name):
        if name == "fitz":
            raise ImportError("missing")
        return importlib.import_module(name)

    monkeypatch.setattr(ocr_extract, "load_paddleocr_class", lambda: FakePaddleOCR)
    monkeypatch.setattr(ocr_extract.importlib, "import_module", fake_import)

    with pytest.raises(RuntimeError) as excinfo:
        ocr_extract.extract_with_paddleocr(pdf_path, lang="en", pdf_dpi=300)

    assert "OCR dependencies are missing" in str(excinfo.value)
    assert "requirements-ocr.txt" in str(excinfo.value)
    assert "default lightweight install" in str(excinfo.value)


def test_file_uri_is_normalized_for_ocr_input(tmp_path):
    pdf_path = tmp_path / "Research Paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    uri = pdf_path.as_uri()

    assert ocr_extract.normalize_source_path(uri) == pdf_path.resolve()


def test_ocr_parse_args_accepts_max_pages():
    args = ocr_extract.parse_args(["scan.pdf", "--max-pages", "1"])

    assert args.max_pages == 1


def test_ocr_run_accepts_file_uri(tmp_path, monkeypatch):
    auto_dir = tmp_path / "auto"
    monkeypatch.setenv("HUASHU_AUTO_DIR", str(auto_dir))

    import output_router

    importlib.reload(output_router)

    image_path = tmp_path / "screen shot.png"
    image_path.write_bytes(b"fake image")

    class FakePaddleOCR:
        def __init__(self, **kwargs):
            pass

        def predict(self, input):
            assert input == str(image_path.resolve())
            return [[[[[0, 0], [1, 0], [1, 1], [0, 1]], ("Visible text", 0.9)]]]

    monkeypatch.setattr(ocr_extract, "load_paddleocr_class", lambda: FakePaddleOCR)

    output_path = ocr_extract.run(
        source=image_path.as_uri(),
        engine="paddleocr",
        output=None,
        lang="en",
        pdf_dpi=300,
    )

    assert output_path.exists()
    assert "Visible text" in output_path.read_text(encoding="utf-8")


def test_huashu_cli_accepts_ocr_route(monkeypatch, capsys):
    calls = []

    class FakeCompletedProcess:
        returncode = 0

    def fake_run(cmd):
        calls.append(cmd)
        return FakeCompletedProcess()

    monkeypatch.setattr(huashu_cli.sys, "argv", ["huashu_cli.py", "-ocr", "scan.png"])
    monkeypatch.setattr(huashu_cli.subprocess, "run", fake_run)

    rc = huashu_cli.main()
    captured = capsys.readouterr()

    assert rc == 0
    assert "Running OCR. This may be slow and memory-heavy." in captured.out
    assert len(calls) == 1
    assert calls[0][0] == (huashu_cli.sys.executable or "python3")
    assert calls[0][1].endswith(os.path.join("scripts", "ocr_extract.py"))
    assert calls[0][2:] == ["scan.png"]


def test_huashu_cli_ocr_keyboard_interrupt_is_graceful(monkeypatch, capsys):
    def fake_run(cmd):
        raise KeyboardInterrupt()

    monkeypatch.setattr(huashu_cli.sys, "argv", ["huashu_cli.py", "-ocr", "scan.pdf"])
    monkeypatch.setattr(huashu_cli.subprocess, "run", fake_run)

    rc = huashu_cli.main()

    captured = capsys.readouterr()
    assert rc == 130
    assert "[abort] OCR interrupted by user." in captured.out


def test_huashu_cli_pdf_mode_flag_routes_through_intake(monkeypatch):
    calls = []

    def fake_run_intake(value, extra_args=None):
        calls.append((value, extra_args))
        return 0

    monkeypatch.delenv("HUASHU_PDF_MODE", raising=False)
    monkeypatch.setattr(huashu_cli.sys, "argv", ["huashu_cli.py", "--pdf-mode", "ocr", "paper.pdf"])
    monkeypatch.setattr(intake_router, "run_intake", fake_run_intake)

    rc = huashu_cli.main()

    assert rc == 0
    assert os.environ["HUASHU_PDF_MODE"] == "ocr"
    assert calls == [("paper.pdf", [])]


@pytest.mark.parametrize("markdown_text", ["", "   \n\t  ", "short text"])
def test_local_file_short_or_empty_extraction_triggers_ocr(tmp_path, monkeypatch, capsys, markdown_text):
    source_path = tmp_path / "scan.pdf"
    source_path.write_bytes(b"%PDF-1.4")
    calls = []

    class FakeCompletedProcess:
        def __init__(self, returncode):
            self.returncode = returncode

    def fake_run(cmd):
        calls.append(cmd)
        script = cmd[1] if len(cmd) > 1 else ""
        if script.endswith("any_to_md.py"):
            output_path = cmd[cmd.index("-o") + 1]
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(markdown_text)
            return FakeCompletedProcess(0)
        if script.endswith("ocr_extract.py"):
            return FakeCompletedProcess(0)
        return FakeCompletedProcess(0)

    monkeypatch.setenv("HUASHU_AUTO_OCR", "1")
    monkeypatch.setattr(huashu_cli.subprocess, "run", fake_run)

    rc = huashu_cli.run_local_file_conversion(str(source_path))

    captured = capsys.readouterr()
    assert rc == 0
    assert "[ocr] Falling back to OCR..." in captured.out
    assert any(cmd[1].endswith("any_to_md.py") for cmd in calls)
    assert any(cmd[1].endswith("ocr_extract.py") for cmd in calls)


def test_local_file_long_extraction_does_not_trigger_ocr(tmp_path, monkeypatch, capsys):
    auto_dir = tmp_path / "auto"
    monkeypatch.setenv("HUASHU_AUTO_DIR", str(auto_dir))

    import output_router

    importlib.reload(output_router)

    source_path = tmp_path / "normal-text.pdf"
    source_path.write_bytes(b"%PDF-1.4")
    long_markdown = "This PDF has meaningful extracted text. " * 20
    calls = []

    class FakeCompletedProcess:
        def __init__(self, returncode):
            self.returncode = returncode

    def fake_run(cmd):
        calls.append(cmd)
        if len(cmd) > 1 and cmd[1].endswith("any_to_md.py"):
            output_path = cmd[cmd.index("-o") + 1]
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(long_markdown)
            return FakeCompletedProcess(0)
        return FakeCompletedProcess(0)

    monkeypatch.setattr(huashu_cli.subprocess, "run", fake_run)

    rc = huashu_cli.run_local_file_conversion(str(source_path))

    captured = capsys.readouterr()
    assert rc == 0
    assert "[ocr] No usable text detected" not in captured.out
    assert "Done." in captured.out
    assert "Markdown:" in captured.out
    assert any(cmd[1].endswith("any_to_md.py") for cmd in calls)
    assert not any(len(cmd) > 1 and cmd[1].endswith("ocr_extract.py") for cmd in calls)
    saved_files = list((auto_dir / "misc").glob("*.md"))
    assert len(saved_files) == 1
    assert saved_files[0].read_text(encoding="utf-8") == long_markdown
    assert (auto_dir / "manifest.csv").exists()


def test_local_file_ocr_missing_dependency_is_graceful(tmp_path, monkeypatch, capsys):
    source_path = tmp_path / "scan.pdf"
    source_path.write_bytes(b"%PDF-1.4")

    class FakeCompletedProcess:
        def __init__(self, returncode):
            self.returncode = returncode

    def fake_run(cmd):
        script = cmd[1] if len(cmd) > 1 else ""
        if script.endswith("any_to_md.py"):
            output_path = cmd[cmd.index("-o") + 1]
            with open(output_path, "w", encoding="utf-8") as f:
                f.write("")
            return FakeCompletedProcess(0)
        if script.endswith("ocr_extract.py"):
            print(ocr_extract.OCR_INSTALL_HELP, file=sys.stderr)
            return FakeCompletedProcess(2)
        return FakeCompletedProcess(0)

    monkeypatch.setenv("HUASHU_AUTO_OCR", "1")
    monkeypatch.setattr(huashu_cli.subprocess, "run", fake_run)

    rc = huashu_cli.run_local_file_conversion(str(source_path))

    captured = capsys.readouterr()
    assert rc == 2
    assert "[ocr] Falling back to OCR..." in captured.out
    assert "OCR dependencies are missing" in captured.err
    assert "requirements-ocr.txt" in captured.err
    assert "default lightweight install" in captured.err


def test_huashu_cli_plain_local_file_uses_auto_fallback_path(tmp_path, monkeypatch):
    source_path = tmp_path / "scan.pdf"
    source_path.write_bytes(b"%PDF-1.4")
    calls = []

    def fake_run_intake(value, extra_args=None):
        calls.append((value, extra_args))
        return 0

    monkeypatch.setattr(huashu_cli.sys, "argv", ["huashu_cli.py", str(source_path)])
    monkeypatch.setattr(intake_router, "run_intake", fake_run_intake)

    rc = huashu_cli.main()

    assert rc == 0
    assert calls == [(str(source_path), [])]


def test_huashu_cli_unresolved_unknown_prints_safe_error(monkeypatch, capsys):
    monkeypatch.setattr(huashu_cli.sys, "argv", ["huashu_cli.py", "not-a-local-file"])

    rc = huashu_cli.main()

    captured = capsys.readouterr()
    assert rc == 1
    assert "[intake] Detected: unknown" in captured.out
    assert "No matching local file found" in captured.out


def test_should_fallback_to_ocr_threshold():
    assert huashu_cli.should_fallback_to_ocr("")
    assert huashu_cli.should_fallback_to_ocr(" \n\t ")
    assert huashu_cli.should_fallback_to_ocr("x" * 199)
    assert not huashu_cli.should_fallback_to_ocr("x" * 200)


def test_huashu_doctor_route(monkeypatch, capsys):
    monkeypatch.setattr(huashu_cli.sys, "argv", ["huashu_cli.py", "doctor"])
    monkeypatch.setattr(huashu_cli, "module_available", lambda module_name: True)
    monkeypatch.setattr(huashu_cli.shutil, "which", lambda name: f"/usr/bin/{name}")

    rc = huashu_cli.main()

    captured = capsys.readouterr()
    assert rc == 0
    assert "Huashu doctor" in captured.out
    assert "OCR: optional" in captured.out
    assert "[ok] PaddleOCR" in captured.out
    assert "[ok] PyMuPDF / fitz" in captured.out


def test_huashu_doctor_missing_ocr_does_not_fail_core_health(monkeypatch, capsys):
    def fake_module_available(module_name):
        return module_name not in {"paddleocr", "paddle", "fitz"}

    monkeypatch.setattr(huashu_cli.sys, "argv", ["huashu_cli.py", "doctor"])
    monkeypatch.setattr(huashu_cli, "module_available", fake_module_available)
    monkeypatch.setattr(huashu_cli.shutil, "which", lambda name: f"/usr/bin/{name}")

    rc = huashu_cli.main()

    captured = capsys.readouterr()
    assert rc == 0
    assert "OCR: optional" in captured.out
    assert "OCR dependencies: missing" in captured.out
    assert "Core Huashu is ready. OCR is optional and not installed." in captured.out


def test_huashu_setup_ocr_route(monkeypatch):
    calls = []

    class FakeCompletedProcess:
        returncode = 0

    def fake_run(cmd):
        calls.append(cmd)
        return FakeCompletedProcess()

    monkeypatch.setattr(huashu_cli.sys, "argv", ["huashu_cli.py", "setup-ocr"])
    monkeypatch.setattr(huashu_cli.subprocess, "run", fake_run)

    rc = huashu_cli.main()

    assert rc == 0
    assert calls
    assert calls[0][0] == (huashu_cli.sys.executable or "python3")
    assert calls[0][-2:] == ["-r", f"{huashu_cli.REPO_ROOT}/requirements-ocr.txt"]
