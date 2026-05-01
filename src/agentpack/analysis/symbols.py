from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Literal

from agentpack.core.models import Symbol


def extract_python_symbols(path: Path) -> list[Symbol]:
    try:
        source = path.read_text(errors="replace")
        tree = ast.parse(source)
    except (SyntaxError, OSError):
        return []

    symbols: list[Symbol] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            sig = f"class {node.name}"
            if node.bases:
                bases = ", ".join(ast.unparse(b) for b in node.bases)
                sig += f"({bases})"
            doc = ast.get_docstring(node)
            symbols.append(
                Symbol(
                    name=node.name,
                    kind="class",
                    start_line=node.lineno,
                    end_line=node.end_lineno or node.lineno,
                    signature=sig,
                    summary=doc[:120] if doc else None,
                    body=ast.get_source_segment(source, node),
                )
            )
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    msig = f"def {item.name}({_args_str(item.args)})"
                    mdoc = ast.get_docstring(item)
                    symbols.append(
                        Symbol(
                            name=f"{node.name}.{item.name}",
                            kind="method",
                            start_line=item.lineno,
                            end_line=item.end_lineno or item.lineno,
                            signature=msig,
                            summary=mdoc[:120] if mdoc else None,
                            body=ast.get_source_segment(source, item),
                        )
                    )

    # top-level functions
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            sig = f"def {node.name}({_args_str(node.args)})"
            doc = ast.get_docstring(node)
            symbols.append(
                Symbol(
                    name=node.name,
                    kind="function",
                    start_line=node.lineno,
                    end_line=node.end_lineno or node.lineno,
                    signature=sig,
                    summary=doc[:120] if doc else None,
                    body=ast.get_source_segment(source, node),
                )
            )

    return symbols


def _args_str(args: ast.arguments) -> str:
    parts: list[str] = []
    for arg in args.args:
        parts.append(arg.arg)
    if args.vararg:
        parts.append(f"*{args.vararg.arg}")
    for arg in args.kwonlyargs:
        parts.append(arg.arg)
    if args.kwarg:
        parts.append(f"**{args.kwarg.arg}")
    return ", ".join(parts)



_JS_FUNC = re.compile(
    r"(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(",
)
# Require => on the same line to avoid matching non-arrow assignments like:
#   const result = (a + b)
_JS_ARROW = re.compile(
    r"(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>",
)
_JS_CLASS = re.compile(r"(?:export\s+)?class\s+(\w+)")


def extract_js_symbols(path: Path) -> list[Symbol]:
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return []

    symbols: list[Symbol] = []
    brace_depth = 0
    open_syms: list[tuple[str, str, int]] = []

    for i, line in enumerate(lines, 1):
        brace_depth += line.count("{") - line.count("}")
        for pattern, kind in [
            (_JS_CLASS, "class"),
            (_JS_FUNC, "function"),
            (_JS_ARROW, "function"),
        ]:
            m = pattern.search(line)
            if m:
                open_syms.append((m.group(1), kind, i))

    # close any unclosed syms at end of file
    end_line = len(lines)
    for name, kind, start in open_syms:
        symbols.append(
            Symbol(
                name=name,
                kind=kind,  # type: ignore[arg-type]
                start_line=start,
                end_line=end_line,
                signature=lines[start - 1].strip()[:120],
                body="\n".join(lines[start - 1 : min(start + 49, end_line)]),
            )
        )
    return symbols


def extract_symbols(path: Path, language: str | None) -> list[Symbol]:
    if language == "python":
        return extract_python_symbols(path)
    if language in ("javascript", "typescript"):
        return extract_js_symbols(path)
    return []


def filter_symbols_by_keywords(symbols: list[Symbol], keywords: set[str]) -> list[Symbol]:
    """Return symbols whose name or summary matches any keyword."""
    if not keywords:
        return symbols
    result = []
    for s in symbols:
        name_lower = s.name.lower()
        summary_lower = (s.summary or "").lower()
        if any(kw in name_lower or kw in summary_lower for kw in keywords):
            result.append(s)
    return result
