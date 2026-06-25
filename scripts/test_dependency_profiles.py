from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def requirement_lines(path: str) -> list[str]:
    return [
        line.strip()
        for line in (REPO_ROOT / path).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_requirement_profiles_exist():
    assert (REPO_ROOT / "requirements.txt").exists()
    assert (REPO_ROOT / "requirements-core.txt").exists()
    assert (REPO_ROOT / "requirements-ocr.txt").exists()


def test_default_requirements_include_core_and_ocr_profiles():
    lines = requirement_lines("requirements.txt")
    assert "-r requirements-core.txt" in lines
    assert "-r requirements-ocr.txt" in lines


def test_core_requirements_do_not_include_ocr_stack():
    text = (REPO_ROOT / "requirements-core.txt").read_text(encoding="utf-8").lower()
    assert "markitdown" in text
    assert "numpy" in text
    assert "yt-dlp" in text
    assert "paddleocr" not in text
    assert "paddlepaddle" not in text
    assert "pymupdf" not in text


def test_ocr_requirements_include_full_ocr_stack():
    lines = {line.lower() for line in requirement_lines("requirements-ocr.txt")}
    assert "paddleocr" in lines
    assert "paddlepaddle" in lines
    assert "pymupdf" in lines
