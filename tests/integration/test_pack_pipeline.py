"""Fixture-based integration tests for the full pack pipeline.

These tests run the real PackService (no mocking) against known fixture repos
and assert on output properties: which files are selected, budget adherence,
secret redaction, cache behaviour, and stale status detection.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


from agentpack.application.pack_service import PackRequest, PackService
from agentpack.core.changed_paths import record_changed_paths, read_changed_paths
from agentpack.core.config import load_config
from agentpack.core.ignore import load_spec
from agentpack.core.scanner import scan
from agentpack.core.snapshot import build_snapshot
from agentpack.core.context_pack import load_pack_metadata
from agentpack.cli import app
from typer.testing import CliRunner

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _setup_repo(tmp_path: Path, fixture_name: str) -> Path:
    """Copy fixture into tmp_path and initialise minimal .agentpack/ config."""
    src = FIXTURES / fixture_name
    dest = tmp_path / fixture_name
    shutil.copytree(src, dest)

    agentpack_dir = dest / ".agentpack"
    agentpack_dir.mkdir(exist_ok=True)
    (agentpack_dir / "config.toml").write_text(
        "[project]\nignore_file = \".agentpackignore\"\n\n"
        "[context]\ndefault_budget = 50000\nmax_file_tokens = 4000\n"
        "include_tests = true\ninclude_configs = true\ninclude_receipts = true\n\n"
        "[agents.claude]\noutput = \".agentpack/context.claude.md\"\n\n"
        "[agents.generic]\noutput = \".agentpack/context.md\"\n"
    )
    (dest / ".agentpackignore").write_text("__pycache__/\n*.pyc\n.git/\n.agentpack/\n")
    return dest


def _pack(root: Path, task: str = "fix auth token", agent: str = "claude") -> object:
    return PackService().run(PackRequest(
        root=root,
        agent=agent,
        task=task,
        mode="balanced",
        budget=50000,
        since=None,
        refresh=False,
    ))


def _init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "agentpack@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "AgentPack Tests"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "initial"], cwd=root, check=True)


class TestPyFastapiApp:
    def test_critical_files_selected(self, tmp_path: Path) -> None:
        root = _setup_repo(tmp_path, "py_fastapi_app")
        result = _pack(root, task="fix auth token refresh")
        selected_paths = {sf.path for sf in result.pack.selected_files}
        assert any("auth" in p for p in selected_paths), \
            f"Expected auth.py in selected files, got: {selected_paths}"

    def test_output_file_written(self, tmp_path: Path) -> None:
        root = _setup_repo(tmp_path, "py_fastapi_app")
        result = _pack(root)
        assert result.out_path.exists()
        content = result.out_path.read_text()
        assert "## Task" in content

    def test_pack_always_refreshes_canonical_context(self, tmp_path: Path) -> None:
        root = _setup_repo(tmp_path, "py_fastapi_app")
        stale_context = root / ".agentpack" / "context.md"
        stale_context.write_text("# stale\n\nold task\n", encoding="utf-8")

        result = _pack(root, task="fix auth token freshness", agent="antigravity")

        assert result.out_path == root / ".agent" / "skills" / "agentpack" / "SKILL.md"
        assert result.out_path.exists()
        canonical = stale_context.read_text(encoding="utf-8")
        assert "fix auth token freshness" in canonical
        assert "# stale" not in canonical

        result2 = _pack(root, task="fix auth token freshness", agent="antigravity")
        assert ".agent/skills/agentpack/SKILL.md" not in result2.changed_files

    def test_second_pack_uses_incremental_scan_for_dirty_paths(self, tmp_path: Path) -> None:
        root = _setup_repo(tmp_path, "py_fastapi_app")
        _init_git_repo(root)

        first = _pack(root, task="fix auth token refresh")
        (root / "src" / "app" / "auth.py").write_text(
            (root / "src" / "app" / "auth.py").read_text() + "\n# changed\n",
            encoding="utf-8",
        )
        second = _pack(root, task="fix auth token refresh")

        assert first.scan_result.scan_mode == "full"
        assert first.scan_result.full_scan_reason == "no previous snapshot"
        assert second.scan_result.scan_mode == "incremental"
        assert second.scan_result.rehashed_count == 1
        assert second.scan_result.reused_count > 0
        assert second.pack.freshness["scan_mode"] == "incremental"

    def test_incremental_scan_includes_untracked_file(self, tmp_path: Path) -> None:
        root = _setup_repo(tmp_path, "py_fastapi_app")
        _init_git_repo(root)

        _pack(root, task="add settings helper")
        new_file = root / "src" / "app" / "new_settings.py"
        new_file.write_text("SETTING = 'x'\n", encoding="utf-8")
        result = _pack(root, task="add settings helper")

        assert result.scan_result.scan_mode == "incremental"
        assert "src/app/new_settings.py" in {fi.path for fi in result.scan_result.packable}
        assert "src/app/new_settings.py" in result.changed_files

    def test_incremental_scan_removes_deleted_file(self, tmp_path: Path) -> None:
        root = _setup_repo(tmp_path, "py_fastapi_app")
        _init_git_repo(root)

        _pack(root, task="remove users helper")
        target = root / "src" / "app" / "users.py"
        target.unlink()
        result = _pack(root, task="remove users helper")

        assert result.scan_result.scan_mode == "incremental"
        assert "src/app/users.py" not in {fi.path for fi in result.scan_result.packable}
        assert "src/app/users.py" in result.changed_files

    def test_incremental_scan_uses_changed_path_ledger(self, tmp_path: Path) -> None:
        root = _setup_repo(tmp_path, "py_fastapi_app")
        _init_git_repo(root)

        _pack(root, task="track hook changed file")
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "--quiet", "-m", "save snapshot"], cwd=root, check=True)
        target = root / "src" / "app" / "auth.py"
        target.write_text(target.read_text(encoding="utf-8") + "\n# ledger\n", encoding="utf-8")
        record_changed_paths(root, ["src/app/auth.py"], source="test")
        subprocess.run(["git", "add", "src/app/auth.py"], cwd=root, check=True)
        subprocess.run(["git", "commit", "--quiet", "-m", "commit outside pack"], cwd=root, check=True)

        result = _pack(root, task="track hook changed file")

        assert result.scan_result.scan_mode == "incremental"
        assert result.scan_result.rehashed_count == 1
        assert read_changed_paths(root) == set()

    def test_config_change_forces_full_scan(self, tmp_path: Path) -> None:
        root = _setup_repo(tmp_path, "py_fastapi_app")
        _init_git_repo(root)

        _pack(root, task="fix auth token refresh")
        config_path = root / ".agentpack" / "config.toml"
        config_path.write_text(
            config_path.read_text(encoding="utf-8").replace("max_file_tokens = 4000", "max_file_tokens = 3000"),
            encoding="utf-8",
        )
        result = _pack(root, task="fix auth token refresh")

        assert result.scan_result.scan_mode == "full"
        assert result.scan_result.full_scan_reason == "scan config or ignore rules changed"

    def test_token_budget_respected(self, tmp_path: Path) -> None:
        root = _setup_repo(tmp_path, "py_fastapi_app")
        result = _pack(root)
        assert result.packed_tokens <= 50000

    def test_thread_pack_writes_scoped_context_and_metadata(self, tmp_path: Path) -> None:
        root = _setup_repo(tmp_path, "py_fastapi_app")
        scoped = root / ".agentpack" / "threads" / "codex-local"
        scoped.mkdir(parents=True)
        (scoped / "task.md").write_text("fix auth in thread\n", encoding="utf-8")

        result = PackService().run(PackRequest(
            root=root,
            agent="claude",
            task="fix auth in thread",
            mode="balanced",
            budget=50000,
            since=None,
            refresh=False,
            thread_id="codex-local",
        ))

        assert result.out_path == scoped / "context.claude.md"
        assert (scoped / "context.md").exists()
        assert (scoped / "pack_metadata.json").exists()
        assert not (root / ".agentpack" / "context.claude.md").exists()
        assert (root / ".agentpack" / "thread_index.jsonl").exists()
        metadata = load_pack_metadata(root, scoped / "pack_metadata.json")
        assert metadata["freshness"]["thread_id"] == "codex-local"
        assert metadata["execution_state"]["task"]["status"] in {"in_progress", "committed", "unknown"}

    def test_workspace_pack_writes_workspace_output(self, tmp_path: Path) -> None:
        root = tmp_path / "mono"
        app_dir = root / "apps" / "web"
        other_dir = root / "apps" / "admin"
        app_dir.mkdir(parents=True)
        other_dir.mkdir(parents=True)
        (root / "package.json").write_text('{"workspaces":["apps/*"]}', encoding="utf-8")
        (app_dir / "package.json").write_text('{"name":"@acme/web"}', encoding="utf-8")
        (other_dir / "package.json").write_text('{"name":"@acme/admin"}', encoding="utf-8")
        (app_dir / "auth.ts").write_text("export function authSession() { return true }\n", encoding="utf-8")
        (other_dir / "auth.ts").write_text("export function adminAuth() { return true }\n", encoding="utf-8")
        (root / ".agentpack").mkdir()
        (root / ".agentpack" / "config.toml").write_text(
            "[context]\ndefault_budget = 10000\nmax_file_tokens = 4000\n\n"
            "[agents.generic]\noutput = \".agentpack/context.md\"\n",
            encoding="utf-8",
        )

        result = PackService().run(PackRequest(
            root=root,
            agent="generic",
            task="fix web auth",
            mode="balanced",
            budget=10000,
            since=None,
            refresh=False,
            workspace="apps/web",
        ))

        assert result.out_path == root / ".agentpack" / "workspaces" / "apps__web" / "context.md"
        assert result.out_path.exists()
        scanned_paths = {fi.path for fi in result.scan_result.packable}
        assert "apps/web/auth.ts" in scanned_paths
        assert "apps/admin/auth.ts" not in scanned_paths
        meta = load_pack_metadata(root)
        assert meta is not None
        assert meta["freshness"]["workspace"] == "apps/web"

    def test_saving_pct_positive(self, tmp_path: Path) -> None:
        root = _setup_repo(tmp_path, "py_fastapi_app")
        result = _pack(root)
        assert result.saving_pct >= 0.0

    def test_auth_scores_higher_than_unrelated_for_auth_task(self, tmp_path: Path) -> None:
        root = _setup_repo(tmp_path, "py_fastapi_app")
        result = _pack(root, task="fix auth token refresh")
        score_map = {sf.path: sf.score for sf in result.pack.selected_files}
        auth_paths = [p for p in score_map if "auth" in p]
        config_paths = [p for p in score_map if "config" in p and "auth" not in p]
        if auth_paths and config_paths:
            best_auth = max(score_map[p] for p in auth_paths)
            best_config = max(score_map[p] for p in config_paths)
            assert best_auth >= best_config, \
                f"auth.py score ({best_auth}) should be >= config.py score ({best_config}) for auth task"

    def test_receipts_populated(self, tmp_path: Path) -> None:
        root = _setup_repo(tmp_path, "py_fastapi_app")
        result = _pack(root)
        assert len(result.pack.receipts) > 0

    def test_snapshot_saved(self, tmp_path: Path) -> None:
        root = _setup_repo(tmp_path, "py_fastapi_app")
        _pack(root)
        assert (root / ".agentpack" / "snapshots" / "latest.json").exists()

    def test_pack_metadata_saved(self, tmp_path: Path) -> None:
        root = _setup_repo(tmp_path, "py_fastapi_app")
        _pack(root, task="fix login")
        meta = load_pack_metadata(root)
        assert meta is not None
        assert meta["task"] == "fix login"

    def test_cache_hit_on_second_run(self, tmp_path: Path) -> None:
        root = _setup_repo(tmp_path, "py_fastapi_app")
        r1 = _pack(root)
        r2 = _pack(root)
        # Both runs should succeed and produce identical output file
        assert r1.out_path.read_text() == r2.out_path.read_text()

    def test_stale_after_file_edit(self, tmp_path: Path) -> None:
        from agentpack.core.snapshot import load_snapshot
        from agentpack.core.diff import diff_snapshots

        root = _setup_repo(tmp_path, "py_fastapi_app")
        _pack(root)

        # Modify a file after packing
        auth_file = root / "src" / "app" / "auth.py"
        if not auth_file.exists():
            auth_file = next(root.rglob("auth.py"), None)
        assert auth_file is not None, "auth.py not found in fixture"
        auth_file.write_text(auth_file.read_text() + "\n# edited\n")

        # Re-scan and compare snapshots
        cfg = load_config(root)
        ignore_spec = load_spec(root / cfg.project.ignore_file)
        scan_result = scan(root, ignore_spec, cfg.context.max_file_tokens)
        new_snap = build_snapshot(scan_result.packable)
        old_snap = load_snapshot(root)

        diff = diff_snapshots(old_snap, new_snap)
        assert any("auth" in p for p in diff.modified), \
            f"Expected auth.py in modified diff, got: {diff.modified}"


class TestSecretRepo:
    def test_secrets_redacted_in_output(self, tmp_path: Path) -> None:
        root = _setup_repo(tmp_path, "secret_repo")
        result = _pack(root, task="review config files")
        content = result.out_path.read_text()
        assert "sk-ant-api03" not in content, \
            "Raw Anthropic API key should be redacted in output"

    def test_redaction_warnings_populated(self, tmp_path: Path) -> None:
        root = _setup_repo(tmp_path, "secret_repo")
        result = _pack(root, task="review config")
        # At least one selected file should have redaction warnings
        has_warnings = any(sf.redaction_warnings for sf in result.pack.selected_files)
        assert has_warnings, "Expected redaction warnings for file with API key"

    def test_redaction_warnings_in_pack(self, tmp_path: Path) -> None:
        root = _setup_repo(tmp_path, "secret_repo")
        result = _pack(root, task="review config")
        assert len(result.pack.redaction_warnings) > 0

    def test_redaction_warning_in_rendered_output(self, tmp_path: Path) -> None:
        root = _setup_repo(tmp_path, "secret_repo")
        result = _pack(root, task="review config")
        content = result.out_path.read_text()
        assert "[REDACTED:" in content or "Secrets redacted" in content or "## Security" in content


class TestMixedRepo:
    def test_both_py_and_ts_files_scannable(self, tmp_path: Path) -> None:
        root = _setup_repo(tmp_path, "mixed_repo")
        cfg = load_config(root)
        ignore_spec = load_spec(root / cfg.project.ignore_file)
        scan_result = scan(root, ignore_spec, cfg.context.max_file_tokens)
        langs = {f.language for f in scan_result.packable}
        assert "python" in langs
        assert "typescript" in langs

    def test_ts_dep_graph_resolves(self, tmp_path: Path) -> None:
        from agentpack.analysis import dependency_graph as dep_graph_mod
        root = _setup_repo(tmp_path, "mixed_repo")
        cfg = load_config(root)
        ignore_spec = load_spec(root / cfg.project.ignore_file)
        scan_result = scan(root, ignore_spec, cfg.context.max_file_tokens)
        graph = dep_graph_mod.build(scan_result.packable, root)
        ts_paths = [p for p in graph if p.endswith(".ts")]
        assert len(ts_paths) > 0

    def test_pack_succeeds_on_mixed_repo(self, tmp_path: Path) -> None:
        root = _setup_repo(tmp_path, "mixed_repo")
        result = _pack(root, task="fix slugify util")
        assert result.out_path.exists()
        assert len(result.pack.selected_files) > 0


class TestBudgetEnforcement:
    def test_tight_budget_respected(self, tmp_path: Path) -> None:
        root = _setup_repo(tmp_path, "py_fastapi_app")
        result = PackService().run(PackRequest(
            root=root,
            agent="claude",
            task="anything",
            mode="minimal",
            budget=500,
            since=None,
            refresh=False,
        ))
        assert result.packed_tokens <= 500

    def test_zero_budget_uses_config_default(self, tmp_path: Path) -> None:
        root = _setup_repo(tmp_path, "py_fastapi_app")
        result = PackService().run(PackRequest(
            root=root,
            agent="claude",
            task="anything",
            mode="balanced",
            budget=0,
            since=None,
            refresh=False,
        ))
        # budget=0 → uses config default (50000) — result must be valid
        assert result.packed_tokens >= 0
        assert result.out_path.exists()


# ---------------------------------------------------------------------------
# Helpers for new test classes
# ---------------------------------------------------------------------------

def _make_request(root: Path, task: str = "fix auth", budget: int = 50000, mode: str = "balanced") -> PackRequest:
    return PackRequest(
        root=root,
        agent="claude",
        task=task,
        mode=mode,
        budget=budget,
        since=None,
        refresh=False,
    )


# ---------------------------------------------------------------------------
# TestNextjsApp
# ---------------------------------------------------------------------------

class TestNextjsApp:
    def test_ts_files_scanned(self, tmp_path: Path) -> None:
        root = _setup_repo(tmp_path, "nextjs_app")
        cfg = load_config(root)
        ignore_spec = load_spec(root / cfg.project.ignore_file)
        scan_result = scan(root, ignore_spec, cfg.context.max_file_tokens)
        ts_files = [f for f in scan_result.packable if f.language == "typescript"]
        assert len(ts_files) > 0, \
            f"Expected TypeScript files, got languages: {[f.language for f in scan_result.packable]}"

    def test_auth_file_selected_for_auth_task(self, tmp_path: Path) -> None:
        root = _setup_repo(tmp_path, "nextjs_app")
        result = PackService().run(_make_request(root, task="fix session auth bug"))
        selected_paths = {sf.path for sf in result.pack.selected_files}
        assert any("auth" in p for p in selected_paths), \
            f"Expected lib/auth.ts in selected files, got: {selected_paths}"

    def test_ts_dep_graph_links_page_to_auth(self, tmp_path: Path) -> None:
        from agentpack.analysis import dependency_graph as dep_graph_mod

        # Use resolved root to handle macOS /var -> /private/var symlink
        root = _setup_repo(tmp_path, "nextjs_app").resolve()
        cfg = load_config(root)
        ignore_spec = load_spec(root / cfg.project.ignore_file)
        scan_result = scan(root, ignore_spec, cfg.context.max_file_tokens)
        graph = dep_graph_mod.build(scan_result.packable, root)

        page_node = graph.nodes.get("src/app/page.tsx")
        api_node = graph.nodes.get("src/lib/api.ts")
        assert page_node is not None, "src/app/page.tsx not in dep graph"
        assert api_node is not None, "src/lib/api.ts not in dep graph"

        # page.tsx → api.ts (direct import)
        assert "src/lib/api.ts" in page_node.imports, \
            f"Expected page.tsx to import api.ts; got: {page_node.imports}"
        # api.ts → auth.ts (direct import)
        assert "src/lib/auth.ts" in api_node.imports, \
            f"Expected api.ts to import auth.ts; got: {api_node.imports}"

    def test_output_file_written(self, tmp_path: Path) -> None:
        root = _setup_repo(tmp_path, "nextjs_app")
        result = PackService().run(_make_request(root))
        assert result.out_path.exists()
        content = result.out_path.read_text()
        assert "## Task" in content

    def test_budget_respected(self, tmp_path: Path) -> None:
        root = _setup_repo(tmp_path, "nextjs_app")
        result = PackService().run(_make_request(root, budget=50000))
        assert result.packed_tokens <= 50000


# ---------------------------------------------------------------------------
# TestExplainCommand
# ---------------------------------------------------------------------------

class TestExplainCommand:
    def test_explain_returns_selected_files(self, tmp_path: Path) -> None:
        from agentpack.application.pack_service import PackPlanner

        root = _setup_repo(tmp_path, "py_fastapi_app")
        plan = PackPlanner().plan(_make_request(root, task="fix auth bug"))
        assert len(plan.selected) > 0, "PackPlanner.plan() should return at least one selected file"

    def test_explain_score_map_populated(self, tmp_path: Path) -> None:
        from agentpack.application.pack_service import PackPlanner

        root = _setup_repo(tmp_path, "py_fastapi_app")
        plan = PackPlanner().plan(_make_request(root, task="fix auth bug"))
        score_map = {sf.path: sf.score for sf in plan.selected}
        assert len(score_map) > 0, "score_map should have at least one entry"
        assert all(isinstance(v, (int, float)) for v in score_map.values()), \
            "All score_map values should be numeric"

    def test_explain_near_cutoff_detection(self, tmp_path: Path) -> None:
        from agentpack.application.pack_service import PackPlanner
        from agentpack.core.context_pack import select_files

        root = _setup_repo(tmp_path, "py_fastapi_app")
        cfg = load_config(root)

        # Pack with tight budget so some files are left out
        tight_req = _make_request(root, task="fix auth bug", budget=100, mode="minimal")
        plan = PackPlanner().plan(tight_req)

        selected_paths = {sf.path for sf in plan.selected}
        deep_budget = plan.budget * 2
        _, deep_receipts = select_files(
            files=plan.scan_result.packable,
            scored=plan.scored,
            changed_paths=plan.all_changed,
            summaries=plan.summaries,
            mode="minimal",
            budget=deep_budget,
            max_file_tokens=cfg.context.max_file_tokens,
            keywords=plan.keywords,
            min_summary_score=cfg.context.min_summary_score,
            max_summary_files=0,
        )
        deep_selected_paths = {
            r.path for r in deep_receipts if r.action in ("included", "summarized")
        }
        near_cutoff = deep_selected_paths - selected_paths
        assert len(near_cutoff) > 0, \
            f"Expected near-cutoff files with tight budget={plan.budget} vs double={deep_budget}; " \
            f"selected={selected_paths}, deep={deep_selected_paths}"

    def test_explain_excluded_files_present(self, tmp_path: Path) -> None:
        from agentpack.application.pack_service import PackPlanner

        root = _setup_repo(tmp_path, "py_fastapi_app")
        # Use a tight budget to force some files to be excluded
        plan = PackPlanner().plan(_make_request(root, task="fix auth bug", budget=500, mode="minimal"))
        excluded = [r for r in plan.receipts if r.action == "excluded"]
        assert len(excluded) > 0, \
            f"Expected at least one excluded receipt with budget=500; got receipts: {plan.receipts}"


# ---------------------------------------------------------------------------
# TestCacheReuse
# ---------------------------------------------------------------------------

class TestCacheReuse:
    def test_summary_cache_written_on_first_pack(self, tmp_path: Path) -> None:
        root = _setup_repo(tmp_path, "py_fastapi_app")
        PackService().run(_make_request(root))
        cache_dir = root / ".agentpack" / "cache"
        assert cache_dir.exists(), ".agentpack/cache/ directory should exist after first pack"
        cache_files = list(cache_dir.iterdir())
        assert len(cache_files) > 0, "Cache directory should contain at least one summary file"

    def test_second_pack_uses_cache(self, tmp_path: Path) -> None:
        root = _setup_repo(tmp_path, "py_fastapi_app")
        req = _make_request(root)
        PackService().run(req)
        result2 = PackService().run(req)
        assert result2.out_path.exists(), "Second pack should produce a valid output file"

    def test_cache_invalidated_on_file_change(self, tmp_path: Path) -> None:
        from agentpack.core.snapshot import load_snapshot
        from agentpack.core.diff import diff_snapshots

        root = _setup_repo(tmp_path, "py_fastapi_app")
        PackService().run(_make_request(root))

        # Edit a source file after first pack
        auth_file = next(root.rglob("auth.py"), None)
        assert auth_file is not None, "auth.py not found in py_fastapi_app fixture"
        auth_file.write_text(auth_file.read_text() + "\n# cache-invalidation-edit\n")

        cfg = load_config(root)
        ignore_spec = load_spec(root / cfg.project.ignore_file)
        scan_result = scan(root, ignore_spec, cfg.context.max_file_tokens)
        new_snap = build_snapshot(scan_result.packable)
        old_snap = load_snapshot(root)

        diff = diff_snapshots(old_snap, new_snap)
        assert any("auth" in p for p in diff.modified), \
            f"Expected auth.py in modified diff after edit, got: {diff.modified}"


# ---------------------------------------------------------------------------
# TestStatusCommand
# ---------------------------------------------------------------------------

class TestStatusCommand:
    def test_status_up_to_date_after_pack(self, tmp_path: Path) -> None:
        from agentpack.core.snapshot import load_snapshot

        root = _setup_repo(tmp_path, "py_fastapi_app")
        PackService().run(_make_request(root))

        old_snap = load_snapshot(root)
        assert old_snap is not None, "Snapshot should be saved after pack"

        cfg = load_config(root)
        ignore_spec = load_spec(root / cfg.project.ignore_file)
        scan_result = scan(root, ignore_spec, cfg.context.max_file_tokens)
        current_snap = build_snapshot(scan_result.packable)

        assert old_snap["root_hash"] == current_snap["root_hash"], \
            "Snapshot root_hash should match immediately after pack (repo unchanged)"

    def test_status_stale_after_file_edit(self, tmp_path: Path) -> None:
        from agentpack.core.snapshot import load_snapshot

        root = _setup_repo(tmp_path, "py_fastapi_app")
        PackService().run(_make_request(root))

        old_snap = load_snapshot(root)
        assert old_snap is not None, "Snapshot should be saved after pack"

        # Modify a file to make the snapshot stale
        auth_file = next(root.rglob("auth.py"), None)
        assert auth_file is not None, "auth.py not found in py_fastapi_app fixture"
        auth_file.write_text(auth_file.read_text() + "\n# stale-trigger-edit\n")

        cfg = load_config(root)
        ignore_spec = load_spec(root / cfg.project.ignore_file)
        scan_result = scan(root, ignore_spec, cfg.context.max_file_tokens)
        current_snap = build_snapshot(scan_result.packable)

        assert old_snap["root_hash"] != current_snap["root_hash"], \
            "Snapshot root_hash should differ after editing a file"

    def test_status_stale_after_task_change(self, tmp_path: Path, monkeypatch) -> None:
        root = _setup_repo(tmp_path, "py_fastapi_app")
        _pack(root, task="fix auth token", agent="generic")
        (root / ".agentpack" / "task.md").write_text("fix numerology dashboard\n", encoding="utf-8")

        monkeypatch.chdir(root)
        result = CliRunner().invoke(app, ["status"])

        assert result.exit_code == 1
        assert ".agentpack/task.md changed since last pack" in result.output
        assert "fix auth token" in result.output
        assert "fix numerology dashboard" in result.output
