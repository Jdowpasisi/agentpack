from __future__ import annotations

import ast
from pathlib import Path

from agentpack.analysis.python_ast import parse_python_source


def extract_imports(path: Path, text: str | None = None) -> list[str]:
    try:
        source = text if text is not None else path.read_text(errors="replace")
        tree = parse_python_source(source, path)
    except SyntaxError:
        return []

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            level = node.level or 0
            prefix = "." * level
            imports.append(f"{prefix}{module}" if module else prefix)
    return imports


def resolve_relative_import(importer: str, import_str: str, root: Path) -> str | None:
    """Resolve a relative Python import to a file path relative to root."""
    if not import_str.startswith("."):
        return None

    dots = len(import_str) - len(import_str.lstrip("."))
    module = import_str[dots:].replace(".", "/")

    base = Path(importer).parent
    for _ in range(dots - 1):
        base = base.parent

    candidate = base / module
    for suffix in (".py", "/__init__.py"):
        full = root / (str(candidate) + suffix)
        if full.exists():
            return str((candidate).with_suffix(".py") if suffix == ".py" else candidate / "__init__.py")

    return None
