from __future__ import annotations

import json
import re
from pathlib import Path


_WORKSPACE_MARKERS = (
    "package.json",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
)


def detect_workspace_roots(root: Path) -> list[str]:
    """Detect package/workspace roots in common monorepo layouts."""
    roots: set[str] = set()
    roots.update(_package_json_workspaces(root))
    roots.update(_pnpm_workspace_roots(root))
    roots.update(_cargo_workspace_roots(root))
    roots.update(_go_work_roots(root))
    return sorted(roots, key=lambda item: (len(Path(item).parts), item))


def detect_workspace_dependency_edges(root: Path, workspace_roots: list[str]) -> dict[str, set[str]]:
    """Return workspace -> workspace dependency edges from package.json files."""
    package_names: dict[str, str] = {}
    for workspace in workspace_roots:
        package_json = root / workspace / "package.json"
        if not package_json.exists():
            continue
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        name = data.get("name")
        if isinstance(name, str) and name:
            package_names[name] = workspace

    edges: dict[str, set[str]] = {workspace: set() for workspace in workspace_roots}
    for workspace in workspace_roots:
        package_json = root / workspace / "package.json"
        if not package_json.exists():
            continue
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        dep_names: set[str] = set()
        for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
            raw = data.get(section)
            if isinstance(raw, dict):
                dep_names.update(str(name) for name in raw)
        for name in dep_names:
            dep_workspace = package_names.get(name)
            if dep_workspace and dep_workspace != workspace:
                edges.setdefault(workspace, set()).add(dep_workspace)
    return edges


def workspace_for_path(path: str, workspace_roots: list[str]) -> str | None:
    """Return deepest workspace root that contains path."""
    norm = path.replace("\\", "/")
    best: str | None = None
    for workspace in workspace_roots:
        prefix = workspace.rstrip("/") + "/"
        if norm == workspace or norm.startswith(prefix):
            if best is None or len(workspace) > len(best):
                best = workspace
    return best


def workspace_tokens(workspace: str) -> set[str]:
    tokens: set[str] = set()
    for part in Path(workspace).parts:
        tokens.update(tok for tok in re.split(r"[^a-zA-Z0-9]+", part.lower()) if len(tok) >= 3)
    return tokens


def normalize_workspace(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().strip("/").replace("\\", "/")
    return normalized or None


def _package_json_workspaces(root: Path) -> set[str]:
    package_json = root / "package.json"
    if not package_json.exists():
        return set()
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    raw = data.get("workspaces")
    if isinstance(raw, dict):
        patterns = raw.get("packages") or []
    else:
        patterns = raw or []
    if not isinstance(patterns, list):
        return set()
    return _expand_workspace_patterns(root, [str(pattern) for pattern in patterns])


def _pnpm_workspace_roots(root: Path) -> set[str]:
    path = root / "pnpm-workspace.yaml"
    if not path.exists():
        return set()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return set()
    patterns: list[str] = []
    in_packages = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("packages:"):
            in_packages = True
            continue
        if in_packages and line.startswith("-"):
            patterns.append(line[1:].strip().strip("'\""))
        elif in_packages and not raw.startswith((" ", "\t")):
            break
    return _expand_workspace_patterns(root, patterns)


def _cargo_workspace_roots(root: Path) -> set[str]:
    path = root / "Cargo.toml"
    if not path.exists():
        return set()
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return set()
    members = data.get("workspace", {}).get("members", [])
    if not isinstance(members, list):
        return set()
    return _expand_workspace_patterns(root, [str(member) for member in members])


def _go_work_roots(root: Path) -> set[str]:
    path = root / "go.work"
    if not path.exists():
        return set()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return set()
    roots: set[str] = set()
    for match in re.finditer(r"^\s*(?:use\s+)?(\./[^\s)]+)", text, flags=re.MULTILINE):
        rel = match.group(1).removeprefix("./")
        candidate = root / rel
        if candidate.is_dir():
            roots.add(rel.replace("\\", "/"))
    return roots


def _expand_workspace_patterns(root: Path, patterns: list[str]) -> set[str]:
    roots: set[str] = set()
    for raw in patterns:
        pattern = raw.strip().strip("/")
        if not pattern or pattern.startswith("!"):
            continue
        for candidate in root.glob(pattern):
            if candidate.is_dir() and _looks_like_workspace(candidate):
                roots.add(candidate.relative_to(root).as_posix())
    return roots


def _looks_like_workspace(path: Path) -> bool:
    return any((path / marker).exists() for marker in _WORKSPACE_MARKERS)
