from __future__ import annotations

import json
from pathlib import Path

from agentpack.analysis.monorepo import (
    detect_workspace_dependency_edges,
    detect_workspace_roots,
    normalize_workspace,
    workspace_for_path,
    workspace_tokens,
)


def test_detect_package_json_workspaces(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"workspaces": ["apps/*", "packages/*"]}),
        encoding="utf-8",
    )
    for rel in ("apps/dashboard", "packages/core"):
        path = tmp_path / rel
        path.mkdir(parents=True)
        (path / "package.json").write_text("{}", encoding="utf-8")
    ignored = tmp_path / "packages" / "generated"
    ignored.mkdir(parents=True)

    assert detect_workspace_roots(tmp_path) == ["apps/dashboard", "packages/core"]


def test_detect_pnpm_and_cargo_workspaces(tmp_path: Path) -> None:
    (tmp_path / "pnpm-workspace.yaml").write_text("packages:\n  - 'apps/*'\n", encoding="utf-8")
    (tmp_path / "Cargo.toml").write_text('[workspace]\nmembers = ["crates/*"]\n', encoding="utf-8")
    for rel, marker in (("apps/web", "package.json"), ("crates/engine", "Cargo.toml")):
        path = tmp_path / rel
        path.mkdir(parents=True)
        (path / marker).write_text("{}", encoding="utf-8")

    assert detect_workspace_roots(tmp_path) == ["apps/web", "crates/engine"]


def test_workspace_for_path_uses_deepest_workspace() -> None:
    roots = ["apps", "apps/dashboard", "packages/core"]

    assert workspace_for_path("apps/dashboard/src/page.tsx", roots) == "apps/dashboard"
    assert workspace_for_path("packages/core/src/index.ts", roots) == "packages/core"
    assert workspace_for_path("README.md", roots) is None


def test_workspace_tokens_split_names() -> None:
    assert {"dashboard", "web"} <= workspace_tokens("apps/dashboard-web")


def test_detect_workspace_dependency_edges_from_package_json(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(json.dumps({"workspaces": ["apps/*", "packages/*"]}), encoding="utf-8")
    app = tmp_path / "apps" / "web"
    shared = tmp_path / "packages" / "shared"
    app.mkdir(parents=True)
    shared.mkdir(parents=True)
    app.joinpath("package.json").write_text(
        json.dumps({"name": "@acme/web", "dependencies": {"@acme/shared": "workspace:*"}}),
        encoding="utf-8",
    )
    shared.joinpath("package.json").write_text(json.dumps({"name": "@acme/shared"}), encoding="utf-8")

    roots = detect_workspace_roots(tmp_path)
    edges = detect_workspace_dependency_edges(tmp_path, roots)

    assert edges["apps/web"] == {"packages/shared"}


def test_normalize_workspace() -> None:
    assert normalize_workspace("/apps/web/") == "apps/web"
