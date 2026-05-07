from __future__ import annotations

import hashlib
from pathlib import Path

import pathspec

from agentpack.core.ignore import load_spec, is_ignored
from agentpack.core.models import FileInfo, ScanResult
from agentpack.core.token_estimator import estimate_tokens, estimate_tokens_bytes

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

ALWAYS_SKIP = {".git", ".agentpack", ".claude"}


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
    previous_snapshot: dict | None = None,
) -> ScanResult:
    packable: list[FileInfo] = []
    ignored: list[FileInfo] = []
    binary: list[FileInfo] = []

    prev_files: dict[str, dict] = (previous_snapshot or {}).get("files", {})

    for abs_path in root.rglob("*"):
        if not abs_path.is_file():
            continue

        rel = abs_path.relative_to(root)
        parts = rel.parts

        if any(p in ALWAYS_SKIP for p in parts):
            continue

        rel_str = str(rel)

        if is_ignored(ignore_spec, rel_str):
            ignored.append(
                FileInfo(
                    path=rel_str,
                    abs_path=abs_path,
                    size_bytes=abs_path.stat().st_size,
                    estimated_tokens=0,
                    ignored=True,
                )
            )
            continue

        if _is_binary(abs_path):
            size = abs_path.stat().st_size
            lang = LANGUAGE_MAP.get(abs_path.suffix.lower())
            binary.append(
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

        size = abs_path.stat().st_size
        lang = LANGUAGE_MAP.get(abs_path.suffix.lower())
        fhash = file_hash(abs_path)

        # Unchanged file: reuse cached token count, skip content read.
        # Content is loaded lazily by context_pack.select_files() when needed.
        prev = prev_files.get(rel_str)
        if prev and prev.get("hash") == fhash:
            cached_tokens = prev.get("estimated_tokens", estimate_tokens_bytes(size))
            too_large = cached_tokens > max_file_tokens
            packable.append(
                FileInfo(
                    path=rel_str,
                    abs_path=abs_path,
                    language=lang,
                    size_bytes=size,
                    estimated_tokens=cached_tokens,
                    hash=fhash,
                    too_large=too_large,
                    content=None,
                )
            )
            continue

        try:
            text = abs_path.read_text(errors="replace")
        except OSError:
            continue

        tokens = estimate_tokens(text)
        too_large = tokens > max_file_tokens

        packable.append(
            FileInfo(
                path=rel_str,
                abs_path=abs_path,
                language=lang,
                size_bytes=size,
                estimated_tokens=tokens,
                hash=fhash,
                too_large=too_large,
                content=text,
            )
        )

    return ScanResult(packable=packable, ignored=ignored, binary=binary)
