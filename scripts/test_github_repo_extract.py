import importlib
import json
import os

import pytest

import github_repo_extract
import huashu_cli


def test_parse_github_repo_url_accepts_repo_roots_and_tree_refs():
    spec = github_repo_extract.parse_github_repo_url("https://github.com/YiJia-Xiao/TradingAgents")
    assert spec is not None
    assert spec.owner == "YiJia-Xiao"
    assert spec.repo == "TradingAgents"
    assert spec.ref is None

    spec = github_repo_extract.parse_github_repo_url("https://github.com/owner/repo/tree/main")
    assert spec is not None
    assert spec.owner == "owner"
    assert spec.repo == "repo"
    assert spec.ref == "main"

    assert github_repo_extract.parse_github_repo_url("https://github.com/owner/repo/blob/main/a.py") is None
    assert github_repo_extract.parse_github_repo_url("https://example.com/owner/repo") is None


def test_extract_repo_writes_index_combined_tree_metadata_and_files(tmp_path, monkeypatch):
    auto_dir = tmp_path / "auto"
    monkeypatch.setenv("HUASHU_AUTO_DIR", str(auto_dir))

    import output_router

    importlib.reload(output_router)

    metadata = {
        "html_url": "https://github.com/owner/repo",
        "description": "Example repo",
        "default_branch": "main",
        "language": "Python",
        "stargazers_count": 7,
        "forks_count": 2,
        "license": {"spdx_id": "MIT"},
    }
    tree = [
        {"path": "README.md", "type": "blob", "size": 12},
        {"path": "requirements.txt", "type": "blob", "size": 8},
        {"path": "package.json", "type": "blob", "size": 15},
        {"path": "pnpm-lock.yaml", "type": "blob", "size": 9},
        {"path": "Cargo.toml", "type": "blob", "size": 10},
        {"path": "go.mod", "type": "blob", "size": 7},
        {"path": "src", "type": "tree"},
        {"path": "src/app.py", "type": "blob", "size": 15},
        {"path": "src/engine.py", "type": "blob", "size": 21},
        {"path": "src/main.py", "type": "blob", "size": 19},
        {"path": "src/risk", "type": "tree"},
        {"path": "src/risk/__init__.py", "type": "blob", "size": 0},
        {"path": "src/risk/kernel.py", "type": "blob", "size": 25},
        {"path": "src/view.tsx", "type": "blob", "size": 16},
        {"path": "tests", "type": "tree"},
        {"path": "tests/test_app.py", "type": "blob", "size": 20},
        {"path": "docs", "type": "tree"},
        {"path": "docs/guide.md", "type": "blob", "size": 22},
        {"path": "config", "type": "tree"},
        {"path": "config/settings.yaml", "type": "blob", "size": 25},
        {"path": "assets/logo.png", "type": "blob", "size": 2048},
    ]
    raw = {
        "README.md": b"# Repo\n",
        "requirements.txt": b"pytest\n",
        "package.json": b'{"scripts":{}}\n',
        "pnpm-lock.yaml": b"lockfile\n",
        "Cargo.toml": b"[package]\n",
        "go.mod": b"module x\n",
        "src/app.py": b"import os\nfrom engine import run\nfrom risk import kernel\n",
        "src/engine.py": b"from risk.kernel import RiskKernel\n\nasync def run():\n    return RiskKernel()\n",
        "src/main.py": b"import app as application\nfrom engine import run\n\ndef main(): pass\n",
        "src/risk/__init__.py": b"",
        "src/risk/kernel.py": (
            b"import json\n\n"
            b"class RiskKernel:\n"
            b"    def score(self):\n"
            b"        return 1\n\n"
            b"    async def async_score(self):\n"
            b"        return 2\n"
        ),
        "src/view.tsx": b"export const x=1\n",
        "tests/test_app.py": b"def test_app(): pass\n",
        "docs/guide.md": b"# Guide\n",
        "config/settings.yaml": b"debug: false\n",
    }

    monkeypatch.setattr(github_repo_extract, "load_repo_metadata", lambda spec: dict(metadata))
    monkeypatch.setattr(github_repo_extract, "load_repo_tree", lambda spec, ref: list(tree))
    monkeypatch.setattr(
        github_repo_extract,
        "fetch_bytes",
        lambda url: raw[url.rsplit("/", 1)[-1] if url.endswith("README.md") else url.split("/main/", 1)[1]],
    )

    result = github_repo_extract.extract_repo(
        "https://github.com/owner/repo",
        output_dir=None,
        max_files=20,
        max_file_size_kb=100,
    )

    assert result.run_dir.parent == auto_dir / "github"
    assert (result.run_dir / "repository_index.md").exists()
    assert (result.run_dir / "architecture.md").exists()
    assert (result.run_dir / "dependency_graph.md").exists()
    assert (result.run_dir / "imports.csv").exists()
    assert (result.run_dir / "symbols.md").exists()
    assert (result.run_dir / "symbols.jsonl").exists()
    assert (result.run_dir / "combined.md").exists()
    assert (result.run_dir / "tree.txt").exists()
    assert (result.run_dir / "repo_metadata.md").exists()
    assert (result.run_dir / "semantic_index").exists()
    assert (result.run_dir / "semantic_index" / "chunks.jsonl").exists()
    assert (result.run_dir / "semantic_index" / "vectors.npy").exists()
    assert (result.run_dir / "semantic_index" / "ids.npy").exists()
    assert (result.run_dir / "semantic_index" / "index_manifest.json").exists()
    assert (result.run_dir / "files" / "README.md").read_text(encoding="utf-8") == "# Repo\n"
    assert "from engine import run" in (result.run_dir / "files" / "src" / "app.py").read_text(encoding="utf-8")
    assert not (result.run_dir / "files" / "assets" / "logo.png").exists()

    index = (result.run_dir / "repository_index.md").read_text(encoding="utf-8")
    assert "## Repository Metadata" in index
    assert "## File Counts by Extension" in index
    assert "- `.py`: 6" in index
    assert "- `.md`: 2" in index
    assert "- `.tsx`: 1" in index
    assert "## Directory Summaries" in index
    assert "## Full File Tree" in index
    assert "|-- assets" in index
    assert "`-- logo.png" in index

    combined = (result.run_dir / "combined.md").read_text(encoding="utf-8")
    assert "---\nFILE: README.md\n---" in combined
    assert "---\nFILE: src/app.py\n---" in combined
    assert "---\nFILE: src/view.tsx\n---" in combined
    assert (auto_dir / "manifest.csv").exists()

    imports_csv = (result.run_dir / "imports.csv").read_text(encoding="utf-8")
    assert imports_csv.splitlines()[0] == "source,target,type"
    assert "src/app.py,src/engine.py,from" in imports_csv
    assert "src/app.py,src/risk/kernel.py,from" in imports_csv
    assert "src/main.py,src/app.py,import" in imports_csv
    assert "src/main.py,src/engine.py,from" in imports_csv
    assert "json" not in imports_csv
    assert "os" not in imports_csv

    graph = (result.run_dir / "dependency_graph.md").read_text(encoding="utf-8")
    assert "## Summary Statistics" in graph
    assert "- Python files analyzed: `6`" in graph
    assert "## Most Imported Modules" in graph
    assert "- `engine`: 2" in graph
    assert "## Top Dependency Hubs" in graph
    assert "- `src/engine.py`: imported by 2 file(s)" in graph
    assert "## Adjacency Lists" in graph
    assert "### src/app.py" in graph
    assert "- src/engine.py" in graph
    assert "- src/risk/kernel.py" in graph
    assert "### src/main.py" in graph

    symbol_records = [
        json.loads(line)
        for line in (result.run_dir / "symbols.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    symbol_keys = {(record["path"], record["name"], record["kind"], record["parent_class"]) for record in symbol_records}
    assert ("src/risk/kernel.py", "RiskKernel", "class", None) in symbol_keys
    assert ("src/risk/kernel.py", "score", "method", "RiskKernel") in symbol_keys
    assert ("src/risk/kernel.py", "async_score", "async_method", "RiskKernel") in symbol_keys
    assert ("src/engine.py", "run", "async_function", None) in symbol_keys
    assert ("src/main.py", "main", "function", None) in symbol_keys
    score_record = next(record for record in symbol_records if record["name"] == "score")
    assert score_record["repo"] == "owner/repo"
    assert score_record["line"] == 4
    assert score_record["preview"] == "def score(self):"

    symbols_md = (result.run_dir / "symbols.md").read_text(encoding="utf-8")
    assert "# Python Symbols: owner/repo" in symbols_md
    assert "## Summary" in symbols_md
    assert "- Total symbols: `6`" in symbols_md
    assert "- Classes: `1`" in symbols_md
    assert "- Functions: `2`" in symbols_md
    assert "- Async functions: `1`" in symbols_md
    assert "- Methods: `1`" in symbols_md
    assert "- Async methods: `1`" in symbols_md
    assert "### `src/risk/kernel.py`" in symbols_md
    assert "L3: `class` `RiskKernel`" in symbols_md
    assert "L4: `method` `RiskKernel`.`score`" in symbols_md
    assert "L7: `async_method` `RiskKernel`.`async_score`" in symbols_md

    architecture = (result.run_dir / "architecture.md").read_text(encoding="utf-8")
    assert "# Architecture Analysis: owner/repo" in architecture
    assert "## Repository Summary" in architecture
    assert "## Top-Level Directory Descriptions" in architecture
    assert "## File Counts by Extension" in architecture
    assert "## Largest Files" in architecture
    assert "## Probable Entrypoints" in architecture
    assert "## Probable Test Directories" in architecture
    assert "## Probable Configuration Files" in architecture
    assert "## Dependency-Related Files" in architecture
    assert "## Documentation Files" in architecture
    assert "- Python: `requirements.txt`" in architecture
    assert "- Node: `package.json`, `pnpm-lock.yaml`" in architecture
    assert "- Rust: `Cargo.toml`" in architecture
    assert "- Go: `go.mod`" in architecture
    assert "- `src/app.py`" in architecture
    assert "- `src/main.py`" in architecture
    assert "- `tests`" in architecture
    assert "- `config/settings.yaml`" in architecture
    assert "- `requirements.txt`" in architecture
    assert "- `README.md`" in architecture
    assert "- `docs/guide.md`" in architecture
    assert "| `assets/logo.png` | 2048 |" in architecture

    github_repo_extract.write_architecture(result)
    assert (result.run_dir / "architecture.md").read_text(encoding="utf-8") == architecture

    chunks = [
        json.loads(line)
        for line in (result.run_dir / "semantic_index" / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert chunks
    app_chunk = next(chunk for chunk in chunks if chunk["path"] == "src/app.py")
    assert app_chunk["repo"] == "owner/repo"
    assert app_chunk["extension"] == ".py"
    assert app_chunk["chunk_index"] == 0
    assert {"repo", "path", "extension", "chunk_index"}.issubset(app_chunk.keys())
    assert any(chunk["path"] == "architecture.md" for chunk in chunks)
    assert any(chunk["path"] == "symbols.md" for chunk in chunks)

    manifest = json.loads((result.run_dir / "semantic_index" / "index_manifest.json").read_text(encoding="utf-8"))
    assert manifest["repo"] == "owner/repo"
    assert manifest["dimension"] == 128
    assert manifest["total_chunks"] == len(chunks)

    search_results = github_repo_extract.search_repo_semantic_index(result.run_dir, "app.py", top_k=3)
    assert search_results
    assert search_results[0]["chunk"]["path"] == "src/app.py"
    assert search_results[0]["filename_boost"] > 0

    symbol_results = github_repo_extract.search_repo_semantic_index(result.run_dir, "main", top_k=3)
    assert any(item["symbol_boost"] > 0 for item in symbol_results)


def test_extract_python_symbols_from_source_detects_python_symbols():
    source = """
class Outer:
    def method(self, value):
        return value

    async def async_method(self):
        return 1

async def top_async():
    return None

def top_function(a, b=1):
    return a + b
"""

    records = github_repo_extract.extract_python_symbols_from_source("owner/repo", "pkg/mod.py", source)
    keys = {(record.name, record.kind, record.parent_class) for record in records}

    assert ("Outer", "class", None) in keys
    assert ("method", "method", "Outer") in keys
    assert ("async_method", "async_method", "Outer") in keys
    assert ("top_async", "async_function", None) in keys
    assert ("top_function", "function", None) in keys
    assert next(record for record in records if record.name == "top_function").preview == "def top_function(a, b=1):"


def test_extract_python_symbols_from_source_ignores_syntax_errors():
    assert github_repo_extract.extract_python_symbols_from_source("owner/repo", "bad.py", "def nope(:\n") == []


def test_repo_search_output_includes_required_fields(capsys):
    github_repo_extract.print_repo_search_results(
        "risk",
        [
            {
                "score": 1.25,
                "chunk": {
                    "repo": "owner/repo",
                    "path": "src/risk.py",
                    "extension": ".py",
                    "chunk_index": 0,
                    "text": "class RiskKernel: pass",
                },
            }
        ],
    )

    captured = capsys.readouterr()
    assert "Score: 1.2500" in captured.out
    assert "Repository: owner/repo" in captured.out
    assert "File: src/risk.py" in captured.out
    assert 'Preview: "class RiskKernel: pass"' in captured.out


def test_extract_repo_respects_max_files_and_file_size(tmp_path, monkeypatch):
    monkeypatch.setattr(
        github_repo_extract,
        "load_repo_metadata",
        lambda spec: {"html_url": "https://github.com/owner/repo", "default_branch": "main"},
    )
    monkeypatch.setattr(
        github_repo_extract,
        "load_repo_tree",
        lambda spec, ref: [
            {"path": "a.py", "type": "blob", "size": 10},
            {"path": "b.py", "type": "blob", "size": 10},
            {"path": "big.md", "type": "blob", "size": 4096},
        ],
    )
    monkeypatch.setattr(github_repo_extract, "fetch_bytes", lambda url: b"x = 1\n")

    result = github_repo_extract.extract_repo(
        "https://github.com/owner/repo",
        output_dir=str(tmp_path),
        max_files=1,
        max_file_size_kb=1,
    )

    assert len(result.extracted_files) == 1
    skipped = {item["path"]: item["reason"] for item in result.skipped_files}
    assert skipped["b.py"] == "max-files limit reached"
    assert skipped["big.md"] == "max-file-size-kb limit exceeded"


def test_is_github_repo_url_detects_only_repo_urls():
    assert huashu_cli.is_github_repo_url("https://github.com/owner/repo")
    assert huashu_cli.is_github_repo_url("https://github.com/owner/repo/tree/main")
    assert not huashu_cli.is_github_repo_url("https://github.com/owner/repo/blob/main/file.py")
    assert not huashu_cli.is_github_repo_url("https://github.com/owner/repo/issues/1")
    assert not huashu_cli.is_github_repo_url("https://example.com/owner/repo")


def test_huashu_cli_repo_route(monkeypatch):
    calls = []

    class FakeCompletedProcess:
        returncode = 0

    def fake_run(cmd):
        calls.append(cmd)
        return FakeCompletedProcess()

    monkeypatch.setattr(
        huashu_cli.sys,
        "argv",
        ["huashu_cli.py", "-repo", "https://github.com/owner/repo", "--max-files", "3"],
    )
    monkeypatch.setattr(huashu_cli.subprocess, "run", fake_run)

    rc = huashu_cli.main()

    assert rc == 0
    assert len(calls) == 1
    assert calls[0][1].endswith(os.path.join("scripts", "github_repo_extract.py"))
    assert calls[0][2:] == ["https://github.com/owner/repo", "--max-files", "3"]


def test_huashu_cli_plain_github_repo_url_auto_routes(monkeypatch):
    calls = []

    class FakeCompletedProcess:
        returncode = 0

    def fake_run(cmd):
        calls.append(cmd)
        return FakeCompletedProcess()

    monkeypatch.setattr(huashu_cli.sys, "argv", ["huashu_cli.py", "https://github.com/owner/repo"])
    monkeypatch.setattr(huashu_cli.subprocess, "run", fake_run)

    rc = huashu_cli.main()

    assert rc == 0
    assert len(calls) == 1
    assert calls[0][1].endswith(os.path.join("scripts", "github_repo_extract.py"))
    assert calls[0][2:] == ["https://github.com/owner/repo"]


def test_huashu_cli_repo_search_route(monkeypatch, tmp_path):
    calls = []

    def fake_repo_search(query, run_dir=None, top_k=5):
        calls.append((query, run_dir, top_k))
        return 0

    monkeypatch.setattr(huashu_cli.sys, "argv", ["huashu_cli.py", "-repo-search", "risk kernel", "--repo-dir", str(tmp_path), "-k", "7"])
    monkeypatch.setattr(github_repo_extract, "repo_search", fake_repo_search)

    rc = huashu_cli.main()

    assert rc == 0
    assert calls == [("risk kernel", str(tmp_path), 7)]
