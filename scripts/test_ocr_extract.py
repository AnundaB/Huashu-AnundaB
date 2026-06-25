import importlib
import os
import sys

import pytest

import huashu_cli
import ocr_extract


def test_load_paddleocr_missing_dependency(monkeypatch):
    def fake_import(name):
        if name == "paddleocr":
            raise ImportError("missing")
        return importlib.import_module(name)

    monkeypatch.setattr(ocr_extract.importlib, "import_module", fake_import)

    with pytest.raises(RuntimeError) as excinfo:
        ocr_extract.load_paddleocr_class()

    assert "PaddleOCR is not installed" in str(excinfo.value)
    assert "pip install paddleocr" in str(excinfo.value)


def test_main_missing_ocr_dependency_gives_clear_error(tmp_path, monkeypatch, capsys):
    image_path = tmp_path / "scan.png"
    image_path.write_bytes(b"fake image")

    def fake_load():
        raise RuntimeError(ocr_extract.PADDLEOCR_INSTALL_HELP)

    monkeypatch.setattr(ocr_extract, "load_paddleocr_class", fake_load)

    rc = ocr_extract.main([str(image_path), "--quiet"])

    captured = capsys.readouterr()
    assert rc == 2
    assert "PaddleOCR is not installed" in captured.err
    assert "pip install paddleocr" in captured.err


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

    assert "PDF OCR needs a local PDF page renderer" in str(excinfo.value)
    assert "pip install pymupdf" in str(excinfo.value)


def test_huashu_cli_accepts_ocr_route(monkeypatch):
    calls = []

    class FakeCompletedProcess:
        returncode = 0

    def fake_run(cmd):
        calls.append(cmd)
        return FakeCompletedProcess()

    monkeypatch.setattr(huashu_cli.sys, "argv", ["huashu_cli.py", "-ocr", "scan.png"])
    monkeypatch.setattr(huashu_cli.subprocess, "run", fake_run)

    rc = huashu_cli.main()

    assert rc == 0
    assert len(calls) == 1
    assert calls[0][0] == (huashu_cli.sys.executable or "python3")
    assert calls[0][1].endswith(os.path.join("scripts", "ocr_extract.py"))
    assert calls[0][2:] == ["scan.png"]


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

    monkeypatch.setattr(huashu_cli.subprocess, "run", fake_run)

    rc = huashu_cli.run_local_file_conversion(str(source_path))

    captured = capsys.readouterr()
    assert rc == 0
    assert "[ocr] No usable text detected. Falling back to OCR..." in captured.out
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
            print("PaddleOCR is not installed", file=sys.stderr)
            return FakeCompletedProcess(2)
        return FakeCompletedProcess(0)

    monkeypatch.setattr(huashu_cli.subprocess, "run", fake_run)

    rc = huashu_cli.run_local_file_conversion(str(source_path))

    captured = capsys.readouterr()
    assert rc == 2
    assert "[ocr] No usable text detected. Falling back to OCR..." in captured.out
    assert "PaddleOCR is not installed" in captured.err


def test_huashu_cli_plain_local_file_uses_auto_fallback_path(tmp_path, monkeypatch):
    source_path = tmp_path / "scan.pdf"
    source_path.write_bytes(b"%PDF-1.4")
    calls = []

    def fake_local_conversion(filename):
        calls.append(filename)
        return 0

    monkeypatch.setattr(huashu_cli.sys, "argv", ["huashu_cli.py", str(source_path)])
    monkeypatch.setattr(huashu_cli, "run_local_file_conversion", fake_local_conversion)

    rc = huashu_cli.main()

    assert rc == 0
    assert calls == [str(source_path)]


def test_huashu_cli_unresolved_unknown_preserves_legacy_fallback(monkeypatch):
    calls = []

    class FakeCompletedProcess:
        returncode = 0

    def fake_run(cmd):
        calls.append(cmd)
        return FakeCompletedProcess()

    monkeypatch.setattr(huashu_cli.sys, "argv", ["huashu_cli.py", "not-a-local-file"])
    monkeypatch.setattr(huashu_cli, "run_local_file_conversion", lambda filename: -1)
    monkeypatch.setattr(huashu_cli.os.path, "exists", lambda path: path == "/Users/AnundaB/bin/huashu")
    monkeypatch.setattr(huashu_cli.subprocess, "run", fake_run)

    rc = huashu_cli.main()

    assert rc == 0
    assert calls == [["bash", "/Users/AnundaB/bin/huashu", "not-a-local-file"]]


def test_should_fallback_to_ocr_threshold():
    assert huashu_cli.should_fallback_to_ocr("")
    assert huashu_cli.should_fallback_to_ocr(" \n\t ")
    assert huashu_cli.should_fallback_to_ocr("x" * 199)
    assert not huashu_cli.should_fallback_to_ocr("x" * 200)
