import importlib
import os

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
