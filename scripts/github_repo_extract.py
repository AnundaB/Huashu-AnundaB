#!/usr/bin/env python3
"""
github_repo_extract.py - Extract text source files from a public GitHub repo.

The extractor uses unauthenticated GitHub API and raw file endpoints. It keeps
binary assets out by default and writes a local folder preserving repo paths.
"""
from __future__ import annotations

import argparse
import ast
import csv
import datetime as _dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = "huashu-md-html/0.1"
TEXT_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".md",
    ".txt",
    ".sh",
    ".sql",
    ".html",
    ".css",
}
DEFAULT_MAX_FILES = 1000
DEFAULT_MAX_FILE_SIZE_KB = 512
DEFAULT_CHUNK_SIZE = 180
DEFAULT_CHUNK_OVERLAP = 40
SEMANTIC_INDEX_DIRNAME = "semantic_index"
PROJECT_MARKERS = {
    "Python": {"setup.py", "pyproject.toml", "requirements.txt"},
    "Node": {"package.json", "pnpm-lock.yaml"},
    "Rust": {"Cargo.toml"},
    "Go": {"go.mod"},
}
ENTRYPOINT_FILENAMES = {"main.py", "app.py", "server.py", "index.ts", "main.ts", "cli.py"}
CONFIG_FILENAMES = {
    ".env.example",
    ".flake8",
    ".prettierrc",
    ".prettierrc.json",
    ".prettierrc.yaml",
    ".prettierrc.yml",
    "Cargo.toml",
    "Dockerfile",
    "go.mod",
    "package.json",
    "pnpm-lock.yaml",
    "pyproject.toml",
    "requirements.txt",
    "setup.cfg",
    "setup.py",
    "tsconfig.json",
}
DEPENDENCY_FILENAMES = {
    "Cargo.lock",
    "Cargo.toml",
    "go.mod",
    "go.sum",
    "package-lock.json",
    "package.json",
    "pnpm-lock.yaml",
    "poetry.lock",
    "pyproject.toml",
    "requirements-dev.txt",
    "requirements.txt",
    "setup.py",
    "yarn.lock",
}
TEST_DIR_NAMES = {"__tests__", "e2e", "spec", "test", "tests"}
DOC_FILENAMES = {
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "LICENSE.md",
    "README.md",
    "SECURITY.md",
}
TOP_LEVEL_DIRECTORY_DESCRIPTIONS = {
    ".github": "GitHub automation, issue templates, or workflow configuration.",
    "app": "Application code or framework routes.",
    "assets": "Static assets and project media.",
    "bin": "Executable helper scripts.",
    "config": "Configuration files and environment defaults.",
    "docs": "Project documentation.",
    "examples": "Example usage, demos, or sample inputs.",
    "lib": "Library code shared by the project.",
    "packages": "Package/workspace modules.",
    "scripts": "Automation and utility scripts.",
    "src": "Primary source code.",
    "test": "Automated tests.",
    "tests": "Automated tests.",
}
STDLIB_MODULES = set(getattr(sys, "stdlib_module_names", set())) | set(sys.builtin_module_names)


@dataclass(frozen=True)
class RepoSpec:
    owner: str
    repo: str
    ref: str | None = None

    @property
    def slug(self) -> str:
        return slugify(f"{self.owner}-{self.repo}")

    @property
    def html_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}"


@dataclass
class ExtractedFile:
    path: str
    extension: str
    size: int
    local_path: Path


@dataclass
class RepoExtractionResult:
    spec: RepoSpec
    metadata: dict[str, Any]
    ref: str
    run_dir: Path
    tree_entries: list[dict[str, Any]]
    text_candidates: list[dict[str, Any]]
    extracted_files: list[ExtractedFile] = field(default_factory=list)
    skipped_files: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return slug[:90] or "repo"


def parse_github_repo_url(url: str) -> RepoSpec | None:
    parsed = urllib.parse.urlparse(url.strip())
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    if parsed.scheme not in ("http", "https") or netloc != "github.com":
        return None

    parts = [urllib.parse.unquote(p) for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        return None

    owner = parts[0]
    repo = parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]

    non_repo_sections = {
        "blob",
        "commit",
        "commits",
        "issues",
        "pull",
        "pulls",
        "releases",
        "actions",
        "wiki",
        "settings",
        "projects",
        "security",
        "network",
        "graphs",
    }
    if len(parts) >= 3 and parts[2] in non_repo_sections:
        return None

    ref = None
    if len(parts) >= 4 and parts[2] == "tree":
        ref = "/".join(parts[3:])
    elif len(parts) >= 3 and parts[2] != "tree":
        return None

    if not owner or not repo:
        return None
    return RepoSpec(owner=owner, repo=repo, ref=ref)


def fetch_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def github_api_url(path: str) -> str:
    return "https://api.github.com" + path


def load_repo_metadata(spec: RepoSpec) -> dict[str, Any]:
    owner = urllib.parse.quote(spec.owner, safe="")
    repo = urllib.parse.quote(spec.repo, safe="")
    return fetch_json(github_api_url(f"/repos/{owner}/{repo}"))


def load_repo_tree(spec: RepoSpec, ref: str) -> list[dict[str, Any]]:
    owner = urllib.parse.quote(spec.owner, safe="")
    repo = urllib.parse.quote(spec.repo, safe="")
    quoted_ref = urllib.parse.quote(ref, safe="")
    data = fetch_json(github_api_url(f"/repos/{owner}/{repo}/git/trees/{quoted_ref}?recursive=1"))
    if data.get("truncated"):
        raise RuntimeError("GitHub returned a truncated repository tree. Try a smaller branch or clone manually.")
    tree = data.get("tree")
    if not isinstance(tree, list):
        raise RuntimeError("GitHub tree response did not include a tree list.")
    return tree


def is_text_candidate(entry: dict[str, Any]) -> bool:
    if entry.get("type") != "blob":
        return False
    path = str(entry.get("path", ""))
    return Path(path).suffix.lower() in TEXT_EXTENSIONS


def is_within_directory(base: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def safe_repo_path(base: Path, repo_path: str) -> Path:
    pure = PurePosixPath(repo_path)
    if pure.is_absolute() or any(part == ".." for part in pure.parts):
        raise ValueError(f"Unsafe repository path: {repo_path}")
    dest = base.joinpath(*pure.parts)
    if not is_within_directory(base, dest):
        raise ValueError(f"Unsafe repository path: {repo_path}")
    return dest


def raw_file_url(spec: RepoSpec, ref: str, repo_path: str) -> str:
    owner = urllib.parse.quote(spec.owner, safe="")
    repo = urllib.parse.quote(spec.repo, safe="")
    quoted_ref = urllib.parse.quote(ref, safe="")
    quoted_path = urllib.parse.quote(repo_path, safe="/")
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{quoted_ref}/{quoted_path}"


def resolve_run_dir(spec: RepoSpec, output_dir: str | None) -> Path:
    if output_dir:
        base = Path(output_dir).expanduser().resolve()
    else:
        sys.path.append(str(REPO_ROOT / "scripts"))
        import output_router

        base = Path(output_router.AUTO_DIR) / "github"

    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return base / f"{stamp}-{spec.slug}"


def build_tree_text(paths: list[str]) -> str:
    root: dict[str, Any] = {}
    for path in paths:
        cursor = root
        for part in PurePosixPath(path).parts:
            cursor = cursor.setdefault(part, {})

    lines = ["."]

    def walk(node: dict[str, Any], prefix: str = "") -> None:
        items = sorted(node.items(), key=lambda item: (bool(item[1]), item[0].lower()))
        for index, (name, child) in enumerate(items):
            last = index == len(items) - 1
            connector = "`-- " if last else "|-- "
            lines.append(f"{prefix}{connector}{name}")
            if child:
                extension = "    " if last else "|   "
                walk(child, prefix + extension)

    walk(root)
    return "\n".join(lines) + "\n"


def directory_summaries(files: list[ExtractedFile]) -> dict[str, dict[str, int]]:
    summaries: dict[str, dict[str, int]] = defaultdict(lambda: {"files": 0, "bytes": 0})
    for item in files:
        directory = str(PurePosixPath(item.path).parent)
        if directory == ".":
            directory = "/"
        summaries[directory]["files"] += 1
        summaries[directory]["bytes"] += item.size
    return dict(sorted(summaries.items(), key=lambda item: item[0]))


def blob_entries(tree_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [entry for entry in tree_entries if entry.get("type") == "blob" and entry.get("path")],
        key=lambda entry: str(entry.get("path", "")).lower(),
    )


def tree_paths(tree_entries: list[dict[str, Any]]) -> list[str]:
    return sorted(
        [str(entry.get("path", "")) for entry in tree_entries if entry.get("path")],
        key=str.lower,
    )


def top_level_directory_summaries(result: RepoExtractionResult) -> dict[str, dict[str, Any]]:
    summaries: dict[str, dict[str, Any]] = {}
    for entry in result.tree_entries:
        path = str(entry.get("path", ""))
        if not path:
            continue
        parts = PurePosixPath(path).parts
        if len(parts) < 2:
            continue
        top = parts[0]
        item = summaries.setdefault(top, {"entries": 0, "files": 0, "text_files": 0, "bytes": 0})
        item["entries"] += 1
        if entry.get("type") == "blob":
            item["files"] += 1
            item["bytes"] += int(entry.get("size") or 0)
            if is_text_candidate(entry):
                item["text_files"] += 1
    return dict(sorted(summaries.items(), key=lambda item: item[0].lower()))


def describe_top_level_directory(name: str, stats: dict[str, Any]) -> str:
    base = TOP_LEVEL_DIRECTORY_DESCRIPTIONS.get(name.lower())
    if base:
        return base
    return f"Directory with {stats['files']} files and {stats['entries']} total tree entries."


def detect_project_structures(paths: list[str]) -> dict[str, list[str]]:
    path_set = {path for path in paths}
    basenames: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        basenames[PurePosixPath(path).name].append(path)

    detected: dict[str, list[str]] = {}
    for name, markers in sorted(PROJECT_MARKERS.items()):
        matches = sorted(
            [path for marker in markers for path in (path_set if "/" in marker else basenames.get(marker, [])) if path == marker or path.endswith("/" + marker)],
            key=str.lower,
        )
        if matches:
            detected[name] = matches
    return detected


def find_probable_entrypoints(paths: list[str]) -> list[str]:
    return sorted(
        [path for path in paths if PurePosixPath(path).name in ENTRYPOINT_FILENAMES],
        key=str.lower,
    )


def find_probable_test_directories(paths: list[str]) -> list[str]:
    directories: set[str] = set()
    for path in paths:
        parts = PurePosixPath(path).parts
        for index, part in enumerate(parts[:-1]):
            if part.lower() in TEST_DIR_NAMES:
                directories.add("/".join(parts[: index + 1]))
    return sorted(directories, key=str.lower)


def find_probable_config_files(paths: list[str]) -> list[str]:
    config_paths = []
    for path in paths:
        pure = PurePosixPath(path)
        name = pure.name
        lower_name = name.lower()
        lower_path = path.lower()
        lower_parts = [part.lower() for part in pure.parts]
        if (
            name in CONFIG_FILENAMES
            or "config" in lower_name
            or "config" in lower_parts[:-1]
            or lower_path.startswith(".github/workflows/")
        ):
            config_paths.append(path)
    return sorted(set(config_paths), key=str.lower)


def find_dependency_files(paths: list[str]) -> list[str]:
    return sorted(
        [path for path in paths if PurePosixPath(path).name in DEPENDENCY_FILENAMES],
        key=str.lower,
    )


def find_documentation_files(paths: list[str]) -> list[str]:
    docs = []
    for path in paths:
        pure = PurePosixPath(path)
        name = pure.name
        lower_parts = [part.lower() for part in pure.parts]
        if name in DOC_FILENAMES or "docs" in lower_parts or pure.suffix.lower() in {".md", ".txt"}:
            docs.append(path)
    return sorted(set(docs), key=str.lower)


def largest_blob_entries(tree_entries: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    blobs = blob_entries(tree_entries)
    return sorted(blobs, key=lambda entry: (-int(entry.get("size") or 0), str(entry.get("path", "")).lower()))[:limit]


def append_path_list(lines: list[str], paths: list[str]) -> None:
    if not paths:
        lines.append("- None detected")
        return
    for path in paths:
        lines.append(f"- `{path}`")


def repo_identifier(result: RepoExtractionResult) -> str:
    return f"{result.spec.owner}/{result.spec.repo}"


def read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def python_module_name_for_path(path: str) -> str | None:
    pure = PurePosixPath(path)
    if pure.suffix != ".py":
        return None
    parts = list(pure.with_suffix("").parts)
    if not parts:
        return None
    if parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts:
        return None
    if parts[0] in {"src", "lib"} and len(parts) > 1:
        parts = parts[1:]
    return ".".join(parts)


def build_python_module_map(files: list[ExtractedFile]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in sorted(files, key=lambda file: file.path.lower()):
        if item.extension != ".py":
            continue
        module_name = python_module_name_for_path(item.path)
        if module_name:
            mapping[module_name] = item.path
        stem = PurePosixPath(item.path).stem
        if stem != "__init__":
            mapping.setdefault(stem, item.path)
    return dict(sorted(mapping.items(), key=lambda entry: entry[0]))


def imported_modules_from_python(source_path: Path) -> list[tuple[str, str, tuple[str, ...]]]:
    try:
        tree = ast.parse(read_text_file(source_path), filename=str(source_path))
    except SyntaxError:
        return []

    imports: list[tuple[str, str, tuple[str, ...]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name:
                    imports.append((alias.name, "import", ()))
        elif isinstance(node, ast.ImportFrom):
            if node.level and not node.module:
                continue
            module = "." * int(node.level or 0) + (node.module or "")
            if module:
                imported_names = tuple(alias.name for alias in node.names if alias.name and alias.name != "*")
                imports.append((module, "from", imported_names))
    return sorted(set(imports), key=lambda item: (item[0], item[1]))


def is_stdlib_import(module_name: str) -> bool:
    root = module_name.lstrip(".").split(".", 1)[0]
    return root in STDLIB_MODULES


def resolve_import_to_file(module_name: str, module_map: dict[str, str]) -> str | None:
    clean = module_name.lstrip(".")
    if not clean:
        return None
    candidates = [clean]
    parts = clean.split(".")
    while len(parts) > 1:
        parts = parts[:-1]
        candidates.append(".".join(parts))
    candidates.append(clean.split(".", 1)[0])

    for candidate in candidates:
        if candidate in module_map:
            return module_map[candidate]
    return None


def build_python_dependency_edges(result: RepoExtractionResult) -> tuple[list[dict[str, str]], Counter[str], list[str]]:
    module_map = build_python_module_map(result.extracted_files)
    py_files = [item for item in sorted(result.extracted_files, key=lambda file: file.path.lower()) if item.extension == ".py"]
    edges: list[dict[str, str]] = []
    imported_modules: Counter[str] = Counter()
    parse_warnings: list[str] = []

    for item in py_files:
        imports = imported_modules_from_python(item.local_path)
        if not imports and read_text_file(item.local_path).strip():
            try:
                ast.parse(read_text_file(item.local_path), filename=str(item.local_path))
            except SyntaxError as exc:
                parse_warnings.append(f"{item.path}: {exc.msg}")
        for module_name, import_type, imported_names in imports:
            if is_stdlib_import(module_name):
                continue
            imported_modules[module_name.lstrip(".")] += 1
            candidates = [module_name]
            if import_type == "from":
                candidates = [f"{module_name}.{name}" for name in imported_names] + [module_name]
            target = None
            for candidate in candidates:
                target = resolve_import_to_file(candidate, module_map)
                if target:
                    break
            if target and target != item.path:
                edges.append({"source": item.path, "target": target, "type": import_type})

    unique_edges = {
        (edge["source"], edge["target"], edge["type"]): edge
        for edge in edges
    }
    return (
        [unique_edges[key] for key in sorted(unique_edges.keys(), key=lambda key: (key[0].lower(), key[1].lower(), key[2]))],
        imported_modules,
        sorted(parse_warnings, key=str.lower),
    )


def write_imports_csv(result: RepoExtractionResult, edges: list[dict[str, str]]) -> Path:
    path = result.run_dir / "imports.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["source", "target", "type"])
        writer.writeheader()
        for edge in edges:
            writer.writerow(edge)
    return path


def write_dependency_graph(result: RepoExtractionResult) -> Path:
    edges, imported_modules, parse_warnings = build_python_dependency_edges(result)
    write_imports_csv(result, edges)

    path = result.run_dir / "dependency_graph.md"
    py_files = [item for item in result.extracted_files if item.extension == ".py"]
    in_degree = Counter(edge["target"] for edge in edges)
    out_degree = Counter(edge["source"] for edge in edges)
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        adjacency[edge["source"]].append(edge["target"])

    lines = [
        f"# Dependency Graph: {result.spec.owner}/{result.spec.repo}",
        "",
        "## Summary Statistics",
        f"- Python files analyzed: `{len(py_files)}`",
        f"- Internal dependency edges: `{len(edges)}`",
        f"- Unique non-stdlib imported modules: `{len(imported_modules)}`",
        f"- Files with outgoing dependencies: `{len(out_degree)}`",
        f"- Files imported by other files: `{len(in_degree)}`",
        "",
        "## Most Imported Modules",
        "",
    ]

    if imported_modules:
        for module, count in sorted(imported_modules.items(), key=lambda item: (-item[1], item[0].lower()))[:20]:
            lines.append(f"- `{module}`: {count}")
    else:
        lines.append("- None detected")

    lines.extend(["", "## Top Dependency Hubs", ""])
    if in_degree:
        for target, count in sorted(in_degree.items(), key=lambda item: (-item[1], item[0].lower()))[:20]:
            lines.append(f"- `{target}`: imported by {count} file(s)")
    else:
        lines.append("- None detected")

    lines.extend(["", "## Adjacency Lists", ""])
    if adjacency:
        for source in sorted(adjacency.keys(), key=str.lower):
            lines.append(f"### {source}")
            lines.append("imports:")
            for target in sorted(set(adjacency[source]), key=str.lower):
                lines.append(f"- {target}")
            lines.append("")
    else:
        lines.append("No internal Python dependencies detected.")
        lines.append("")

    if parse_warnings:
        lines.extend(["## Parse Warnings", ""])
        for warning in parse_warnings:
            lines.append(f"- {warning}")
        lines.append("")

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def build_repo_semantic_index(
    result: RepoExtractionResult,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> Path:
    """
    Builds a repository-local semantic index under semantic_index/.
    Reuses the research ingestion deterministic embedding and chunking code.
    """
    sys.path.append(str(REPO_ROOT / "scripts"))
    import research_memory_index

    semantic_dir = result.run_dir / SEMANTIC_INDEX_DIRNAME
    semantic_dir.mkdir(parents=True, exist_ok=True)

    repo = repo_identifier(result)
    source_items: list[tuple[str, str, Path]] = []
    for item in sorted(result.extracted_files, key=lambda file: file.path.lower()):
        source_items.append((item.path, item.extension, item.local_path))

    architecture_path = result.run_dir / "architecture.md"
    if architecture_path.exists():
        source_items.append(("architecture.md", ".md", architecture_path))

    chunks_data: list[dict[str, Any]] = []
    vectors_list: list[np.ndarray] = []
    chunk_id = 1

    for repo_path, extension, local_path in source_items:
        text = read_text_file(local_path)
        chunks = research_memory_index.chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        for chunk_index, chunk in enumerate(chunks):
            vectors_list.append(research_memory_index.text_to_vector_128(chunk))
            chunks_data.append({
                "chunk_id": chunk_id,
                "repo": repo,
                "path": repo_path,
                "extension": extension,
                "chunk_index": chunk_index,
                "text": chunk,
                "source_url": result.spec.html_url,
                "ref": result.ref,
                "repo_owner": result.spec.owner,
                "repo_name": result.spec.repo,
            })
            chunk_id += 1

    chunks_jsonl_path = semantic_dir / "chunks.jsonl"
    with chunks_jsonl_path.open("w", encoding="utf-8") as f:
        for chunk in chunks_data:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    id_map_path = semantic_dir / "id_map.jsonl"
    with id_map_path.open("w", encoding="utf-8") as f:
        for chunk in chunks_data:
            f.write(json.dumps({
                "chunk_id": chunk["chunk_id"],
                "repo": chunk["repo"],
                "path": chunk["path"],
                "extension": chunk["extension"],
                "chunk_index": chunk["chunk_index"],
            }, ensure_ascii=False) + "\n")

    if chunks_data:
        vectors = np.vstack(vectors_list).astype(np.float32)
        ids = np.array([chunk["chunk_id"] for chunk in chunks_data], dtype=np.uint64)
        np.save(semantic_dir / "vectors.npy", vectors)
        np.save(semantic_dir / "ids.npy", ids)

        if research_memory_index.HAS_TURBOVEC:
            index = research_memory_index.IdMapIndex(dim=128, bit_width=4)
            index.add_with_ids(vectors, ids)
            index.write(str(semantic_dir / "index.tvim"))
    else:
        vectors = np.empty((0, 128), dtype=np.float32)
        ids = np.array([], dtype=np.uint64)
        np.save(semantic_dir / "vectors.npy", vectors)
        np.save(semantic_dir / "ids.npy", ids)

    manifest = {
        "repo": repo,
        "source_url": result.spec.html_url,
        "ref": result.ref,
        "dimension": 128,
        "total_chunks": len(chunks_data),
        "engine": "turbovec" if research_memory_index.HAS_TURBOVEC else "numpy_fallback",
        "created_at": _dt.datetime.now().isoformat(),
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "sources_indexed": [path for path, _, _ in source_items],
    }
    (semantic_dir / "index_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return semantic_dir


def repo_semantic_index_exists(run_dir: Path) -> bool:
    semantic_dir = run_dir / SEMANTIC_INDEX_DIRNAME
    return (semantic_dir / "chunks.jsonl").exists() and (semantic_dir / "vectors.npy").exists() and (semantic_dir / "ids.npy").exists()


def find_latest_repo_run() -> Path | None:
    sys.path.append(str(REPO_ROOT / "scripts"))
    import output_router

    github_dir = Path(output_router.AUTO_DIR) / "github"
    if not github_dir.exists():
        return None
    candidates = [
        path for path in github_dir.iterdir()
        if path.is_dir() and repo_semantic_index_exists(path)
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda path: path.name)[-1]


def load_repo_chunks(semantic_dir: Path) -> dict[int, dict[str, Any]]:
    chunks_jsonl_path = semantic_dir / "chunks.jsonl"
    chunks_by_id: dict[int, dict[str, Any]] = {}
    with chunks_jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                chunk = json.loads(line)
                chunks_by_id[int(chunk["chunk_id"])] = chunk
    return chunks_by_id


def query_terms(query: str) -> list[str]:
    return [term.lower() for term in re.findall(r"[A-Za-z_][A-Za-z0-9_./-]*", query)]


def filename_match_boost(query: str, chunk: dict[str, Any]) -> float:
    path = str(chunk.get("path", ""))
    basename = PurePosixPath(path).name.lower()
    stem = PurePosixPath(path).stem.lower()
    query_lower = query.lower().strip()
    terms = query_terms(query)
    if query_lower in {basename, stem}:
        return 2.0
    if basename in terms or stem in terms:
        return 1.5
    if any(term == basename or term == stem for term in terms):
        return 1.5
    return 0.0


def symbol_match_boost(query: str, chunk: dict[str, Any]) -> float:
    text = str(chunk.get("text", ""))
    path = str(chunk.get("path", ""))
    boost = 0.0
    for term in query_terms(query):
        if len(term) < 3 or "/" in term or "." in term:
            continue
        pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])", re.IGNORECASE)
        if pattern.search(text):
            boost += 0.35
        if pattern.search(path):
            boost += 0.2
    return min(boost, 1.2)


def search_repo_semantic_index(run_dir: Path, query: str, top_k: int = 5) -> list[dict[str, Any]]:
    sys.path.append(str(REPO_ROOT / "scripts"))
    import research_memory_index

    semantic_dir = run_dir / SEMANTIC_INDEX_DIRNAME
    if not repo_semantic_index_exists(run_dir):
        raise FileNotFoundError(f"semantic_index not found under {run_dir}")

    chunks_by_id = load_repo_chunks(semantic_dir)
    if not chunks_by_id:
        return []

    query_vec = research_memory_index.text_to_vector_128(query)
    vectors = np.load(semantic_dir / "vectors.npy")
    ids = np.load(semantic_dir / "ids.npy")
    if vectors.shape[0] == 0:
        return []
    scores = np.dot(vectors, query_vec)
    semantic_pairs = [(float(scores[index]), int(ids[index])) for index in range(len(ids))]

    ranked = []
    for semantic_score, chunk_id in semantic_pairs:
        chunk = chunks_by_id.get(chunk_id)
        if not chunk:
            continue
        fname_boost = filename_match_boost(query, chunk)
        sym_boost = symbol_match_boost(query, chunk)
        final_score = semantic_score + fname_boost + sym_boost
        ranked.append({
            "score": final_score,
            "semantic_score": semantic_score,
            "filename_boost": fname_boost,
            "symbol_boost": sym_boost,
            "chunk": chunk,
        })

    ranked.sort(key=lambda item: (-item["score"], str(item["chunk"].get("path", "")), int(item["chunk"].get("chunk_index", 0))))
    return ranked[:top_k]


def print_repo_search_results(query: str, results: list[dict[str, Any]]) -> None:
    print(f"\nRepository search results for query: '{query}'\n" + "=" * 80)
    if not results:
        print("No results.")
        return

    for index, item in enumerate(results, start=1):
        chunk = item["chunk"]
        preview = str(chunk.get("text", "")).replace("\n", " ").strip()
        if len(preview) > 250:
            preview = preview[:247] + "..."
        print(
            f"{index}. Score: {item['score']:.4f} | Repository: {chunk.get('repo')} | "
            f"File: {chunk.get('path')}"
        )
        print(f"   Chunk: {chunk.get('chunk_index')} | Extension: {chunk.get('extension')}")
        print(f"   Preview: \"{preview}\"")
        print("-" * 80)


def repo_search(query: str, run_dir: str | None = None, top_k: int = 5) -> int:
    target_run = Path(run_dir).expanduser().resolve() if run_dir else find_latest_repo_run()
    if target_run is None:
        print("[error] No repository semantic index found. Run huashu -repo <github_repo_url> first.", file=sys.stderr)
        return 1
    try:
        results = search_repo_semantic_index(target_run, query, top_k=top_k)
    except Exception as exc:
        print(f"[error] Repository search failed: {exc}", file=sys.stderr)
        return 1
    print_repo_search_results(query, results)
    return 0


def format_metadata(metadata: dict[str, Any], spec: RepoSpec, ref: str) -> list[str]:
    license_info = metadata.get("license") or {}
    return [
        f"- Repository: `{spec.owner}/{spec.repo}`",
        f"- Source URL: {metadata.get('html_url') or spec.html_url}",
        f"- Branch/ref: `{ref}`",
        f"- Description: {metadata.get('description') or ''}",
        f"- Default branch: `{metadata.get('default_branch') or ''}`",
        f"- Language: `{metadata.get('language') or ''}`",
        f"- Stars: `{metadata.get('stargazers_count', '')}`",
        f"- Forks: `{metadata.get('forks_count', '')}`",
        f"- License: `{license_info.get('spdx_id') or license_info.get('name') or ''}`",
        f"- Fetched at: `{_dt.datetime.now().isoformat(timespec='seconds')}`",
    ]


def write_repo_metadata(result: RepoExtractionResult) -> Path:
    path = result.run_dir / "repo_metadata.md"
    lines = [
        f"# Repository Metadata: {result.spec.owner}/{result.spec.repo}",
        "",
        *format_metadata(result.metadata, result.spec, result.ref),
        "",
        "## Extraction Limits",
        f"- Max files: `{result.metadata.get('_huashu_max_files')}`",
        f"- Max file size KB: `{result.metadata.get('_huashu_max_file_size_kb')}`",
        "",
        "## Extraction Summary",
        f"- Tree entries: `{len(result.tree_entries)}`",
        f"- Text candidates: `{len(result.text_candidates)}`",
        f"- Extracted files: `{len(result.extracted_files)}`",
        f"- Skipped files: `{len(result.skipped_files)}`",
        f"- Errors: `{len(result.errors)}`",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_tree(result: RepoExtractionResult) -> Path:
    path = result.run_dir / "tree.txt"
    tree_paths = [str(entry.get("path", "")) for entry in result.tree_entries if entry.get("path")]
    path.write_text(build_tree_text(tree_paths), encoding="utf-8")
    return path


def write_combined(result: RepoExtractionResult) -> Path:
    path = result.run_dir / "combined.md"
    chunks = [f"# Combined Repository Files: {result.spec.owner}/{result.spec.repo}", ""]
    for item in sorted(result.extracted_files, key=lambda file: file.path):
        content = item.local_path.read_text(encoding="utf-8", errors="replace")
        chunks.extend([
            "---",
            f"FILE: {item.path}",
            "---",
            "",
            content.rstrip(),
            "",
        ])
    path.write_text("\n".join(chunks).rstrip() + "\n", encoding="utf-8")
    return path


def write_repository_index(result: RepoExtractionResult) -> Path:
    path = result.run_dir / "repository_index.md"
    ext_counts = Counter(file.extension for file in result.extracted_files)
    summaries = directory_summaries(result.extracted_files)
    tree_text = (result.run_dir / "tree.txt").read_text(encoding="utf-8")

    lines = [
        f"# Repository Index: {result.spec.owner}/{result.spec.repo}",
        "",
        "## Repository Metadata",
        *format_metadata(result.metadata, result.spec, result.ref),
        "",
        "## Extraction Summary",
        f"- Tree entries: `{len(result.tree_entries)}`",
        f"- Text candidates: `{len(result.text_candidates)}`",
        f"- Extracted files: `{len(result.extracted_files)}`",
        f"- Skipped files: `{len(result.skipped_files)}`",
        f"- Errors: `{len(result.errors)}`",
        "",
        "## File Counts by Extension",
        "",
    ]

    if ext_counts:
        for extension, count in sorted(ext_counts.items()):
            lines.append(f"- `{extension}`: {count}")
    else:
        lines.append("- None")

    lines.extend(["", "## Directory Summaries", ""])
    if summaries:
        lines.extend(["| Directory | Files | Bytes |", "| --- | ---: | ---: |"])
        for directory, stats in summaries.items():
            lines.append(f"| `{directory}` | {stats['files']} | {stats['bytes']} |")
    else:
        lines.append("No text files were extracted.")

    lines.extend(["", "## Full File Tree", "", "```text", tree_text.rstrip(), "```", ""])

    if result.skipped_files:
        lines.extend(["## Skipped Files", ""])
        lines.extend(["| Path | Reason |", "| --- | --- |"])
        for skipped in result.skipped_files:
            lines.append(f"| `{skipped.get('path', '')}` | {skipped.get('reason', '')} |")
        lines.append("")

    if result.errors:
        lines.extend(["## Errors", ""])
        for error in result.errors:
            lines.append(f"- {error}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_architecture(result: RepoExtractionResult) -> Path:
    path = result.run_dir / "architecture.md"
    paths = tree_paths(blob_entries(result.tree_entries))
    ext_counts = Counter(file.extension for file in result.extracted_files)
    top_dirs = top_level_directory_summaries(result)
    project_structures = detect_project_structures(paths)
    entrypoints = find_probable_entrypoints(paths)
    test_dirs = find_probable_test_directories(paths)
    config_files = find_probable_config_files(paths)
    dependency_files = find_dependency_files(paths)
    documentation_files = find_documentation_files(paths)
    largest_files = largest_blob_entries(result.tree_entries)

    lines = [
        f"# Architecture Analysis: {result.spec.owner}/{result.spec.repo}",
        "",
        "## Repository Summary",
        f"- Repository: `{result.spec.owner}/{result.spec.repo}`",
        f"- Description: {result.metadata.get('description') or ''}",
        f"- Primary language: `{result.metadata.get('language') or ''}`",
        f"- Branch/ref: `{result.ref}`",
        f"- Tree entries: `{len(result.tree_entries)}`",
        f"- Extracted text files: `{len(result.extracted_files)}`",
        f"- Top-level directories: `{len(top_dirs)}`",
        "",
        "## Detected Project Structures",
        "",
    ]

    if project_structures:
        for structure, markers in project_structures.items():
            lines.append(f"- {structure}: " + ", ".join(f"`{marker}`" for marker in markers))
    else:
        lines.append("- None detected")

    lines.extend(["", "## Top-Level Directory Descriptions", ""])
    if top_dirs:
        lines.extend(["| Directory | Description | Files | Text files | Bytes |", "| --- | --- | ---: | ---: | ---: |"])
        for directory, stats in top_dirs.items():
            lines.append(
                f"| `{directory}` | {describe_top_level_directory(directory, stats)} | "
                f"{stats['files']} | {stats['text_files']} | {stats['bytes']} |"
            )
    else:
        lines.append("No top-level directories detected.")

    lines.extend(["", "## File Counts by Extension", ""])
    if ext_counts:
        for extension, count in sorted(ext_counts.items()):
            lines.append(f"- `{extension}`: {count}")
    else:
        lines.append("- None")

    lines.extend(["", "## Largest Files", ""])
    if largest_files:
        lines.extend(["| Path | Size bytes |", "| --- | ---: |"])
        for entry in largest_files:
            lines.append(f"| `{entry.get('path', '')}` | {int(entry.get('size') or 0)} |")
    else:
        lines.append("No files detected.")

    lines.extend(["", "## Probable Entrypoints", ""])
    append_path_list(lines, entrypoints)

    lines.extend(["", "## Probable Test Directories", ""])
    append_path_list(lines, test_dirs)

    lines.extend(["", "## Probable Configuration Files", ""])
    append_path_list(lines, config_files)

    lines.extend(["", "## Dependency-Related Files", ""])
    append_path_list(lines, dependency_files)

    lines.extend(["", "## Documentation Files", ""])
    append_path_list(lines, documentation_files)
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def register_repository_index(index_path: Path, result: RepoExtractionResult) -> None:
    try:
        sys.path.append(str(REPO_ROOT / "scripts"))
        import output_router

        output_router.register_output(
            output_path=str(index_path),
            source=result.spec.html_url,
            explicit_type="github",
            title=f"GitHub repo: {result.spec.owner}/{result.spec.repo}",
            status="success" if not result.errors else "partial",
        )
    except Exception as exc:
        print(f"[warn] Failed to register GitHub repo output: {exc}")


def extract_repo(
    repo_url: str,
    output_dir: str | None = None,
    max_files: int = DEFAULT_MAX_FILES,
    max_file_size_kb: int = DEFAULT_MAX_FILE_SIZE_KB,
) -> RepoExtractionResult:
    spec = parse_github_repo_url(repo_url)
    if spec is None:
        raise ValueError(f"Not a supported GitHub repository URL: {repo_url}")

    metadata = load_repo_metadata(spec)
    ref = spec.ref or metadata.get("default_branch") or "main"
    metadata["_huashu_max_files"] = "unlimited" if max_files <= 0 else max_files
    metadata["_huashu_max_file_size_kb"] = "unlimited" if max_file_size_kb <= 0 else max_file_size_kb

    tree_entries = load_repo_tree(spec, ref)
    text_candidates = [entry for entry in tree_entries if is_text_candidate(entry)]
    run_dir = resolve_run_dir(spec, output_dir)
    files_dir = run_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)

    result = RepoExtractionResult(
        spec=spec,
        metadata=metadata,
        ref=ref,
        run_dir=run_dir,
        tree_entries=tree_entries,
        text_candidates=text_candidates,
    )

    for entry in sorted(text_candidates, key=lambda item: str(item.get("path", "")).lower()):
        repo_path = str(entry.get("path", ""))
        size = int(entry.get("size") or 0)
        if max_file_size_kb > 0 and size > max_file_size_kb * 1024:
            result.skipped_files.append({"path": repo_path, "reason": "max-file-size-kb limit exceeded"})
            continue
        if max_files > 0 and len(result.extracted_files) >= max_files:
            result.skipped_files.append({"path": repo_path, "reason": "max-files limit reached"})
            continue

        try:
            data = fetch_bytes(raw_file_url(spec, ref, repo_path))
            text = data.decode("utf-8", errors="replace")
            local_path = safe_repo_path(files_dir, repo_path)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_text(text, encoding="utf-8")
            result.extracted_files.append(
                ExtractedFile(
                    path=repo_path,
                    extension=Path(repo_path).suffix.lower(),
                    size=len(data),
                    local_path=local_path,
                )
            )
        except Exception as exc:
            result.errors.append(f"{repo_path}: {exc}")

    write_tree(result)
    write_repo_metadata(result)
    write_combined(result)
    write_architecture(result)
    write_dependency_graph(result)
    build_repo_semantic_index(result)
    index_path = write_repository_index(result)
    register_repository_index(index_path, result)
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract text source files from a public GitHub repository.")
    parser.add_argument("repo_url", help="GitHub repository URL, for example https://github.com/owner/repo")
    parser.add_argument("--output-dir", default=None, help="Base output directory. Defaults to outputs/auto/github.")
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES, help="Maximum text files to download; 0 means unlimited.")
    parser.add_argument(
        "--max-file-size-kb",
        type=int,
        default=DEFAULT_MAX_FILE_SIZE_KB,
        help="Skip text files larger than this size; 0 means unlimited.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = extract_repo(
            repo_url=args.repo_url,
            output_dir=args.output_dir,
            max_files=args.max_files,
            max_file_size_kb=args.max_file_size_kb,
        )
    except ValueError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    except urllib.error.HTTPError as exc:
        print(f"[error] GitHub request failed: HTTP {exc.code} {exc.reason}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"[error] GitHub request failed: {exc.reason}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - network and GitHub errors vary.
        print(f"[error] GitHub repository extraction failed: {exc}", file=sys.stderr)
        return 1

    print(f"[ok] Extracted GitHub repo: {result.spec.owner}/{result.spec.repo}")
    print(f"Output folder: {result.run_dir}")
    print(f"repository_index.md: {result.run_dir / 'repository_index.md'}")
    print(f"combined.md: {result.run_dir / 'combined.md'}")
    print(f"tree.txt: {result.run_dir / 'tree.txt'}")
    print(f"repo_metadata.md: {result.run_dir / 'repo_metadata.md'}")
    print(f"architecture.md: {result.run_dir / 'architecture.md'}")
    print(f"dependency_graph.md: {result.run_dir / 'dependency_graph.md'}")
    print(f"imports.csv: {result.run_dir / 'imports.csv'}")
    print(f"semantic_index: {result.run_dir / SEMANTIC_INDEX_DIRNAME}")
    print(f"Text files extracted: {len(result.extracted_files)}")
    print(f"Skipped files: {len(result.skipped_files)}")
    if result.errors:
        print(f"Errors: {len(result.errors)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
