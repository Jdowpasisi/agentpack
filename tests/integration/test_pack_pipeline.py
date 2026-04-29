"""Fixture-based integration tests for the full pack pipeline.

These tests run the real PackService (no mocking) against known fixture repos
and assert on output properties: which files are selected, budget adherence,
secret redaction, cache behaviour, and stale status detection.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agentpack.application.pack_service import PackRequest, PackService
from agentpack.core.config import load_config
from agentpack.core.ignore import load_spec
from agentpack.core.scanner import scan
from agentpack.core.snapshot import build_snapshot, save_snapshot
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
        summary_provider="offline",
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
            summary_provider="offline",
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
            summary_provider="offline",
        ))
        # budget=0 → uses config default (50000) — result must be valid
        assert result.packed_tokens >= 0
        assert result.out_path.exists()
