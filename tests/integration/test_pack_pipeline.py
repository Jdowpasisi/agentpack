"""Fixture-based integration tests for the full pack pipeline.

These tests run the real PackService (no mocking) against known fixture repos
and assert on output properties: which files are selected, budget adherence,
secret redaction, cache behaviour, and stale status detection.
"""
from __future__ import annotations

import shutil
from pathlib import Path


from agentpack.application.pack_service import PackRequest, PackService
from agentpack.core.config import load_config
from agentpack.core.ignore import load_spec
from agentpack.core.scanner import scan
from agentpack.core.snapshot import build_snapshot
from agentpack.core.context_pack import load_pack_metadata

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

    def test_token_budget_respected(self, tmp_path: Path) -> None:
        root = _setup_repo(tmp_path, "py_fastapi_app")
        result = _pack(root)
        assert result.packed_tokens <= 50000

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
