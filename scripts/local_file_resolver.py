#!/usr/bin/env python3
"""Local file resolution for Huashu intake routing."""
from __future__ import annotations

import os
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_SAFE_ROOTS = (
    Path.cwd,
    lambda: Path.home() / "Downloads",
    lambda: Path.home() / "Documents",
    lambda: Path.home() / "Desktop",
    lambda: Path.home() / "Downloads" / "Research",
    lambda: Path.home() / "Downloads" / "Research" / "Papers",
)


@dataclass
class LocalFileResolution:
    original: str
    normalized: str
    status: str
    path: Path | None = None
    matches: list[Path] = field(default_factory=list)
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "resolved" and self.path is not None


def normalize_local_path(value: str) -> str:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme == "file":
        if parsed.netloc and parsed.netloc not in ("localhost", "127.0.0.1"):
            path_text = f"//{parsed.netloc}{parsed.path}"
        else:
            path_text = parsed.path
        return urllib.parse.unquote(path_text)
    return value


def safe_roots(cwd: Path | None = None, env: str | None = None) -> list[Path]:
    roots: list[Path] = []
    for factory in DEFAULT_SAFE_ROOTS:
        try:
            root = Path(cwd).resolve() if factory is Path.cwd and cwd else factory()
            roots.append(root.expanduser().resolve())
        except Exception:
            continue

    env_value = os.environ.get("HUASHU_FILE_ROOTS") if env is None else env
    if env_value:
        for raw in env_value.split(os.pathsep):
            if raw.strip():
                roots.append(Path(raw).expanduser().resolve())

    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def has_path_separators(value: str) -> bool:
    return "/" in value or "\\" in value


def resolve_local_file(value: str, cwd: Path | None = None, env: str | None = None) -> LocalFileResolution:
    normalized = normalize_local_path(value)
    base_cwd = Path.cwd().resolve() if cwd is None else Path(cwd).expanduser().resolve()
    candidate = Path(normalized).expanduser()

    if candidate.is_absolute():
        resolved = candidate.resolve()
        if resolved.exists() and resolved.is_file():
            return LocalFileResolution(value, normalized, "resolved", path=resolved)
        return LocalFileResolution(value, normalized, "not_found", message=f"File not found: {resolved}")

    cwd_candidate = (base_cwd / candidate).resolve()
    if cwd_candidate.exists() and cwd_candidate.is_file():
        return LocalFileResolution(value, normalized, "resolved", path=cwd_candidate)

    if has_path_separators(normalized):
        return LocalFileResolution(value, normalized, "not_found", message=f"File not found: {cwd_candidate}")

    matches: list[Path] = []
    for root in safe_roots(base_cwd, env=env):
        if not root.exists() or not root.is_dir():
            continue
        direct = root / normalized
        if direct.exists() and direct.is_file():
            matches.append(direct.resolve())
        try:
            for found in root.rglob(normalized):
                if found.is_file():
                    matches.append(found.resolve())
        except (OSError, PermissionError):
            continue

    unique_matches = sorted({str(path): path for path in matches}.values(), key=lambda path: str(path))
    if len(unique_matches) == 1:
        return LocalFileResolution(value, normalized, "resolved", path=unique_matches[0], matches=unique_matches)
    if len(unique_matches) > 1:
        return LocalFileResolution(value, normalized, "multiple", matches=unique_matches)
    return LocalFileResolution(
        value,
        normalized,
        "not_found",
        message=(
            "No matching local file found. Pass a full path, a file:// URI, "
            "or set HUASHU_FILE_ROOTS for additional safe lookup roots."
        ),
    )
