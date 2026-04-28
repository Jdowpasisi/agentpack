from __future__ import annotations

import hashlib
from pathlib import Path

import pathspec

from agentpack.core.ignore import load_spec, is_ignored
from agentpack.core.models import FileInfo
from agentpack.core.token_estimator import estimate_tokens

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg",
    ".pdf", ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".bin",
    ".mp3", ".mp4", ".wav", ".avi", ".mov",
    ".ttf", ".woff", ".woff2", ".eot",
    ".pyc", ".pyo", ".class",
    ".db", ".sqlite", ".sqlite3",
}

LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".md": "markdown",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".sql": "sql",
    ".tf": "terraform",
    ".xml": "xml",
}

ALWAYS_SKIP = {".git", ".agentpack"}


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_binary(path: Path) -> bool:
    if path.suffix.lower() in BINARY_EXTENSIONS:
        return True
    try:
        chunk = path.read_bytes()[:1024]
        return b"\x00" in chunk
    except OSError:
        return True


def scan(
    root: Path,
    ignore_spec: pathspec.PathSpec,
    max_file_tokens: int = 4000,
) -> list[FileInfo]:
    files: list[FileInfo] = []
    for abs_path in root.rglob("*"):
        if not abs_path.is_file():
            continue

        rel = abs_path.relative_to(root)
        parts = rel.parts

        if any(p in ALWAYS_SKIP for p in parts):
            continue

        rel_str = str(rel)

        if is_ignored(ignore_spec, rel_str):
            files.append(
                FileInfo(
                    path=rel_str,
                    abs_path=abs_path,
                    size_bytes=abs_path.stat().st_size,
                    estimated_tokens=0,
                    ignored=True,
                )
            )
            continue

        binary = _is_binary(abs_path)
        size = abs_path.stat().st_size
        lang = LANGUAGE_MAP.get(abs_path.suffix.lower())

        if binary:
            files.append(
                FileInfo(
                    path=rel_str,
                    abs_path=abs_path,
                    language=lang,
                    size_bytes=size,
                    estimated_tokens=0,
                    binary=True,
                )
            )
            continue

        try:
            text = abs_path.read_text(errors="replace")
        except OSError:
            continue

        tokens = estimate_tokens(text)
        too_large = tokens > max_file_tokens

        files.append(
            FileInfo(
                path=rel_str,
                abs_path=abs_path,
                language=lang,
                size_bytes=size,
                estimated_tokens=tokens,
                hash=file_hash(abs_path),
                too_large=too_large,
            )
        )

    return files
