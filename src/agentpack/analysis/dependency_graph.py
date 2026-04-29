from __future__ import annotations

from pathlib import Path

from agentpack.core.models import FileInfo
from agentpack.analysis.python_imports import extract_imports as py_imports
from agentpack.analysis.python_imports import resolve_relative_import as py_resolve
from agentpack.analysis.js_ts_imports import extract_imports as js_imports
from agentpack.analysis.js_ts_imports import resolve_relative_import as js_resolve
from agentpack.analysis.go_imports import extract_imports as go_imports
from agentpack.analysis.rust_imports import extract_imports as rust_imports
from agentpack.analysis.java_imports import extract_imports as java_imports


def build(
    files: list[FileInfo],
    root: Path,
    summaries: dict | None = None,
) -> dict[str, dict]:
    """Build an import/imported-by graph over packable files.

    Args:
        files: Packable (non-ignored, non-binary) FileInfo objects.
        root: Repository root for resolving relative imports.
        summaries: Optional pre-built summary cache; cached imports avoid re-parsing.

    Returns:
        Mapping of path → {imports, imported_by, tests} where tests starts empty
        (caller fills it via find_related_tests).
    """
    graph: dict[str, dict] = {fi.path: {"imports": [], "imported_by": [], "tests": []} for fi in files}
    path_set = {fi.path for fi in files}

    for fi in files:
        if summaries and fi.path in summaries:
            cached_imports = summaries[fi.path].get("imports", [])
            if cached_imports:
                graph[fi.path]["imports"] = cached_imports
                for dep in cached_imports:
                    if dep in graph:
                        graph[dep]["imported_by"].append(fi.path)
                continue

        raw_imports: list[str] = []
        lang = fi.language
        cached = fi.content

        if lang == "python":
            raw_imports = py_imports(fi.abs_path, cached)
        elif lang in ("javascript", "typescript"):
            raw_imports = js_imports(fi.abs_path, cached)
        elif lang == "go":
            raw_imports = go_imports(fi.abs_path, cached)
        elif lang == "rust":
            raw_imports = rust_imports(fi.abs_path, cached)
        elif lang in ("java", "kotlin"):
            raw_imports = java_imports(fi.abs_path, cached)

        resolved: list[str] = []
        for imp in raw_imports:
            if imp.startswith("."):
                if lang == "python":
                    r = py_resolve(fi.path, imp, root)
                elif lang in ("javascript", "typescript"):
                    r = js_resolve(fi.path, imp, root)
                else:
                    r = None
                if r and r in path_set:
                    resolved.append(r)
            else:
                resolved.append(imp)

        graph[fi.path]["imports"] = resolved
        for dep in resolved:
            if dep in graph:
                graph[dep]["imported_by"].append(fi.path)

    return graph
