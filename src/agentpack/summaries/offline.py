from __future__ import annotations

import ast
import re
from pathlib import Path

from agentpack.core.models import FileSummary, Symbol
from agentpack.analysis.symbols import extract_python_symbols, extract_js_symbols
from agentpack.analysis.python_imports import extract_imports as py_imports
from agentpack.analysis.js_ts_imports import extract_imports as js_imports


def summarize(path: str, abs_path: Path, language: str | None, file_hash: str) -> FileSummary:
    if language == "python":
        return _python_summary(path, abs_path, file_hash)
    if language in ("javascript", "typescript"):
        return _js_summary(path, abs_path, language, file_hash)
    return _generic_summary(path, abs_path, language, file_hash)


def _python_summary(path: str, abs_path: Path, file_hash: str) -> FileSummary:
    imports = py_imports(abs_path)
    symbols = extract_python_symbols(abs_path)

    top_level_imports = [i for i in imports if not i.startswith(".")][:8]
    exposed = [s.name for s in symbols if s.kind in ("class", "function")][:8]

    parts = [f"Language: Python"]
    if exposed:
        parts.append(f"Exposes: {', '.join(exposed)}")
    if top_level_imports:
        parts.append(f"Imports: {', '.join(top_level_imports)}")
    parts.append(f"Likely responsibility: {_infer_responsibility(path, exposed)}")

    return FileSummary(
        path=path,
        hash=file_hash,
        language="python",
        provider="offline",
        schema_version=1,
        summary="\n- ".join([""] + parts).lstrip("\n- ") if parts else "",
        imports=imports[:20],
        symbols=symbols,
    )


def _js_summary(path: str, abs_path: Path, language: str, file_hash: str) -> FileSummary:
    imports = js_imports(abs_path)
    symbols = extract_js_symbols(abs_path)

    rel_imports = [i for i in imports if not i.startswith(".")][:8]
    exposed = [s.name for s in symbols][:8]

    parts = [f"Language: {language.capitalize()}"]
    if exposed:
        parts.append(f"Exposes: {', '.join(exposed)}")
    if rel_imports:
        parts.append(f"Imports: {', '.join(rel_imports)}")
    parts.append(f"Likely responsibility: {_infer_responsibility(path, exposed)}")

    return FileSummary(
        path=path,
        hash=file_hash,
        language=language,
        provider="offline",
        schema_version=1,
        summary="\n- ".join([""] + parts).lstrip("\n- ") if parts else "",
        imports=imports[:20],
        symbols=symbols,
    )


def _generic_summary(path: str, abs_path: Path, language: str | None, file_hash: str) -> FileSummary:
    try:
        lines = abs_path.read_text(errors="replace").splitlines()[:30]
        snippet = "\n".join(lines)
    except OSError:
        snippet = ""

    return FileSummary(
        path=path,
        hash=file_hash,
        language=language,
        provider="offline",
        schema_version=1,
        summary=f"Language: {language or 'unknown'}\nFirst lines:\n{snippet[:300]}",
        imports=[],
        symbols=[],
    )


def _infer_responsibility(path: str, symbols: list[str]) -> str:
    path_lower = path.lower()
    hint = Path(path).stem.replace("_", " ")
    if symbols:
        return f"{hint} based on path and symbols ({', '.join(symbols[:3])})"
    return f"{hint} based on path"
