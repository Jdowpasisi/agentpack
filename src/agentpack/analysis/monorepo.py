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
    """Return workspace -> workspace dependency edges from common package manifests."""
    edges: dict[str, set[str]] = {workspace: set() for workspace in workspace_roots}
    _add_package_json_edges(root, workspace_roots, edges)
    _add_cargo_edges(root, workspace_roots, edges)
    _add_go_edges(root, workspace_roots, edges)
    return edges


def _add_package_json_edges(root: Path, workspace_roots: list[str], edges: dict[str, set[str]]) -> None:
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


def _add_cargo_edges(root: Path, workspace_roots: list[str], edges: dict[str, set[str]]) -> None:
    for workspace in workspace_roots:
        manifest = root / workspace / "Cargo.toml"
        if not manifest.exists():
            continue
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]
        try:
            data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        for section in ("dependencies", "dev-dependencies", "build-dependencies"):
            raw = data.get(section)
            if isinstance(raw, dict):
                _add_cargo_section_edges(root, workspace, raw, workspace_roots, edges)
        target = data.get("target")
        if isinstance(target, dict):
            for target_data in target.values():
                if not isinstance(target_data, dict):
                    continue
                for section in ("dependencies", "dev-dependencies", "build-dependencies"):
                    raw = target_data.get(section)
                    if isinstance(raw, dict):
                        _add_cargo_section_edges(root, workspace, raw, workspace_roots, edges)


def _add_cargo_section_edges(
    root: Path,
    workspace: str,
    dependencies: dict[str, object],
    workspace_roots: list[str],
    edges: dict[str, set[str]],
) -> None:
    workspace_dir = root / workspace
    for spec in dependencies.values():
        if not isinstance(spec, dict):
            continue
        raw_path = spec.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            continue
        dep_workspace = _workspace_from_relative_path(root, workspace_dir / raw_path, workspace_roots)
        if dep_workspace and dep_workspace != workspace:
            edges.setdefault(workspace, set()).add(dep_workspace)


def _add_go_edges(root: Path, workspace_roots: list[str], edges: dict[str, set[str]]) -> None:
    module_to_workspace: dict[str, str] = {}
    replacements_by_workspace: dict[str, dict[str, str]] = {}
    requires_by_workspace: dict[str, set[str]] = {}
    for workspace in workspace_roots:
        go_mod = root / workspace / "go.mod"
        if not go_mod.exists():
            continue
        try:
            text = go_mod.read_text(encoding="utf-8")
        except OSError:
            continue
        module = _go_module_name(text)
        if module:
            module_to_workspace[module] = workspace
        replacements_by_workspace[workspace] = _go_replacements(root, root / workspace, text, workspace_roots)
        requires_by_workspace[workspace] = _go_requires(text)

    for workspace, requires in requires_by_workspace.items():
        replacements = replacements_by_workspace.get(workspace, {})
        for module in requires:
            dep_workspace = replacements.get(module) or module_to_workspace.get(module)
            if dep_workspace and dep_workspace != workspace:
                edges.setdefault(workspace, set()).add(dep_workspace)


def _go_module_name(text: str) -> str | None:
    match = re.search(r"^module\s+(\S+)", text, flags=re.MULTILINE)
    return match.group(1) if match else None


def _go_requires(text: str) -> set[str]:
    modules: set[str] = set()
    in_block = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if line == "require (":
            in_block = True
            continue
        if in_block and line == ")":
            in_block = False
            continue
        if line.startswith("require "):
            modules.add(line.split()[1])
        elif in_block:
            modules.add(line.split()[0])
    return modules


def _go_replacements(root: Path, workspace_dir: Path, text: str, workspace_roots: list[str]) -> dict[str, str]:
    replacements: dict[str, str] = {}
    in_block = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if line == "replace (":
            in_block = True
            continue
        if in_block and line == ")":
            in_block = False
            continue
        if line.startswith("replace "):
            _add_go_replacement(root, workspace_dir, line.removeprefix("replace ").strip(), workspace_roots, replacements)
        elif in_block:
            _add_go_replacement(root, workspace_dir, line, workspace_roots, replacements)
    return replacements


def _add_go_replacement(
    root: Path,
    workspace_dir: Path,
    line: str,
    workspace_roots: list[str],
    replacements: dict[str, str],
) -> None:
    if "=>" not in line:
        return
    left, right = [part.strip() for part in line.split("=>", 1)]
    module = left.split()[0]
    target = right.split()[0]
    if not target.startswith((".", "/")):
        return
    target_path = Path(target)
    candidate = target_path if target_path.is_absolute() else workspace_dir / target_path
    dep_workspace = _workspace_from_relative_path(root, candidate, workspace_roots)
    if dep_workspace:
        replacements[module] = dep_workspace


def _workspace_from_relative_path(root: Path, candidate: Path, workspace_roots: list[str]) -> str | None:
    try:
        rel = candidate.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return None
    return workspace_for_path(rel, workspace_roots)


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
