from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agentpack.commands.hook_cmd import (
    _mcp_installed,
    _load_top_files,
    _load_pack_task,
    _current_root_hash,
    _run_user_prompt_submit,
    _looks_like_coding_prompt,
    _looks_like_task_switch,
    _resolve_task,
)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    agentpack_dir = tmp_path / ".agentpack"
    agentpack_dir.mkdir()
    snapshots_dir = agentpack_dir / "snapshots"
    snapshots_dir.mkdir()
    return tmp_path


def _write_snapshot(repo: Path, root_hash: str = "abc123") -> None:
    snap = repo / ".agentpack" / "snapshots" / "latest.json"
    snap.write_text(json.dumps({"root_hash": root_hash, "files": {}}))


def _write_metrics(repo: Path, selected_paths: list[str]) -> None:
    rec = {"ts": "2026-01-01T00:00:00Z", "task": "test", "selected_paths": selected_paths}
    (repo / ".agentpack" / "metrics.jsonl").write_text(json.dumps(rec) + "\n")


def _write_metadata(repo: Path, task: str = "fix login") -> None:
    meta = {"task": task, "token_estimate": 5000}
    (repo / ".agentpack" / "pack_metadata.json").write_text(json.dumps(meta))


class TestMcpInstalled:
    def test_local_mcp_json(self, repo: Path) -> None:
        (repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"agentpack": {"command": "agentpack", "args": ["mcp"]}}}))
        assert _mcp_installed(repo) is True

    def test_no_mcp(self, repo: Path) -> None:
        assert _mcp_installed(repo) is False

    def test_mcp_json_no_agentpack_entry(self, repo: Path) -> None:
        (repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"other": {}}}))
        assert _mcp_installed(repo) is False


class TestLoadTopFiles:
    def test_returns_top_n(self, repo: Path) -> None:
        paths = [f"src/file{i}.py" for i in range(10)]
        _write_metrics(repo, paths)
        result = _load_top_files(repo, n=5)
        assert len(result) == 5
        assert result[0]["path"] == "src/file0.py"

    def test_no_metrics(self, repo: Path) -> None:
        assert _load_top_files(repo) == []


class TestLoadPackTask:
    def test_reads_task(self, repo: Path) -> None:
        _write_metadata(repo, task="fix auth")
        assert _load_pack_task(repo) == "fix auth"

    def test_missing(self, repo: Path) -> None:
        assert _load_pack_task(repo) == ""


class TestCurrentRootHash:
    def test_reads_hash(self, repo: Path) -> None:
        _write_snapshot(repo, "deadbeef")
        assert _current_root_hash(repo) == "deadbeef"

    def test_missing(self, repo: Path) -> None:
        assert _current_root_hash(repo) is None


class TestRunUserPromptSubmit:
    def _capture_output(self, repo: Path, stdin_data: dict, monkeypatch) -> dict:
        import io
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(stdin_data)))
        outputs = []
        monkeypatch.setattr("builtins.print", lambda x: outputs.append(x))
        with patch("subprocess.Popen"):
            _run_user_prompt_submit(repo)
        assert outputs, "No output printed"
        return json.loads(outputs[0])

    def test_mcp_installed_hint_format(self, repo: Path, monkeypatch) -> None:
        _write_snapshot(repo, "hash1")
        _write_metrics(repo, ["src/a.py", "src/b.py"])
        _write_metadata(repo, task="fix login")
        (repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"agentpack": {}}}))

        out = self._capture_output(repo, {"prompt": "fix the login bug"}, monkeypatch)
        ctx = out["hookSpecificOutput"]["additionalContext"]

        assert "agentpack_pack_context" in ctx
        assert "src/a.py" in ctx
        assert len(ctx) < 1000  # tiny hint, not full injection

    def test_no_mcp_capped_fallback(self, repo: Path, monkeypatch) -> None:
        _write_snapshot(repo, "hash1")
        _write_metrics(repo, ["src/a.py", "src/b.py"])
        _write_metadata(repo, task="fix login")

        out = self._capture_output(repo, {"prompt": "fix login"}, monkeypatch)
        ctx = out["hookSpecificOutput"]["additionalContext"]

        assert len(ctx) <= 3000
        assert "src/a.py" in ctx
        assert "agentpack install" in ctx  # nudge toward MCP

    def test_hard_cap_enforced(self, repo: Path, monkeypatch) -> None:
        _write_snapshot(repo, "hash1")
        # Many files to potentially produce long output
        paths = [f"src/module_{i}/very_long_filename_{i}.py" for i in range(50)]
        _write_metrics(repo, paths)
        _write_metadata(repo, task="x" * 200)

        out = self._capture_output(repo, {"prompt": "test"}, monkeypatch)
        ctx = out["hookSpecificOutput"]["additionalContext"]
        assert len(ctx) <= 3000

    def test_repo_changed_triggers_repack(self, repo: Path, monkeypatch) -> None:
        _write_snapshot(repo, "newhash")
        # Sentinel has old hash
        (repo / ".agentpack" / ".mcp_reminded").write_text("oldhash")

        import io
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"prompt": "fix login bug"})))
        outputs = []
        monkeypatch.setattr("builtins.print", lambda x: outputs.append(x))

        with patch("subprocess.Popen") as mock_popen, \
             patch("agentpack.commands.hook_cmd._infer_live_task", return_value="fix login bug"):
            _run_user_prompt_submit(repo)

        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert "pack" in args
        assert args[:4] == ["agentpack", "pack", "--task", "auto"]
        assert (repo / ".agentpack" / "task.md").read_text(encoding="utf-8") == "fix login bug\n"

    def test_repo_unchanged_no_repack(self, repo: Path, monkeypatch) -> None:
        _write_snapshot(repo, "samehash")
        (repo / ".agentpack" / ".mcp_reminded").write_text("samehash")
        (repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"agentpack": {}}}))
        _write_metrics(repo, ["src/a.py"])
        _write_metadata(repo)

        import io
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"prompt": "test"})))
        outputs = []
        monkeypatch.setattr("builtins.print", lambda x: outputs.append(x))

        with patch("subprocess.Popen") as mock_popen, \
             patch("agentpack.commands.hook_cmd._infer_live_task", return_value="general development"):
            _run_user_prompt_submit(repo)

        mock_popen.assert_not_called()

    def test_task_switch_updates_task_md_and_repacks(self, repo: Path, monkeypatch) -> None:
        _write_snapshot(repo, "samehash")
        (repo / ".agentpack" / ".mcp_reminded").write_text("samehash")
        (repo / ".agentpack" / "task.md").write_text("add production-grade Kundali generation API\n")
        (repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"agentpack": {}}}))
        _write_metrics(repo, ["src/old.py"])
        _write_metadata(repo, task="add production-grade Kundali generation API")

        import io
        prompt = "fix numerology dashboard layout"
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"prompt": prompt})))
        outputs = []
        monkeypatch.setattr("builtins.print", lambda x: outputs.append(x))

        with patch("subprocess.Popen") as mock_popen:
            _run_user_prompt_submit(repo)

        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert args[:3] == ["agentpack", "pack", "--task"]
        assert args[3] == "auto"
        assert (repo / ".agentpack" / "task.md").read_text(encoding="utf-8") == prompt + "\n"
        ctx = json.loads(outputs[0])["hookSpecificOutput"]["additionalContext"]
        assert "repacking" in ctx
        assert f"task: {prompt}" in ctx

    def test_task_switch_can_be_disabled_in_config(self, repo: Path, monkeypatch) -> None:
        _write_snapshot(repo, "samehash")
        (repo / ".agentpack" / ".mcp_reminded").write_text("samehash")
        (repo / ".agentpack" / "task.md").write_text("add production-grade Kundali generation API\n")
        (repo / ".agentpack" / "config.toml").write_text(
            "[hooks]\ntask_switch_detection = false\n",
            encoding="utf-8",
        )
        (repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"agentpack": {}}}))
        _write_metrics(repo, ["src/old.py"])
        _write_metadata(repo, task="add production-grade Kundali generation API")

        import io
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"prompt": "fix numerology dashboard layout"})))
        outputs = []
        monkeypatch.setattr("builtins.print", lambda x: outputs.append(x))

        with patch("subprocess.Popen") as mock_popen:
            _run_user_prompt_submit(repo)

        mock_popen.assert_not_called()
        assert (repo / ".agentpack" / "task.md").read_text(encoding="utf-8") == (
            "add production-grade Kundali generation API\n"
        )
        ctx = json.loads(outputs[0])["hookSpecificOutput"]["additionalContext"]
        assert "index fresh" in ctx
        assert "task: add production-grade Kundali generation API" in ctx


class TestLooksLikeCodingPrompt:
    def test_slash_command_rejected(self):
        assert not _looks_like_coding_prompt("/caveman ultra")
        assert not _looks_like_coding_prompt("/agentpack")

    def test_coding_verbs_accepted(self):
        assert _looks_like_coding_prompt("fix the login bug")
        assert _looks_like_coding_prompt("add pagination to the API")
        assert _looks_like_coding_prompt("refactor auth module")
        assert _looks_like_coding_prompt("implement OAuth flow")

    def test_chat_prompt_rejected(self):
        assert not _looks_like_coding_prompt("why does this work?")
        assert not _looks_like_coding_prompt("explain connection pooling")

    def test_empty_rejected(self):
        assert not _looks_like_coding_prompt("")


class TestResolveTask:
    def test_task_md_wins_over_related_coding_prompt(self, tmp_path):
        (tmp_path / ".agentpack").mkdir()
        (tmp_path / ".agentpack" / "task.md").write_text("fix login flow")
        result = _resolve_task(tmp_path, "fix login bug")
        assert result == "fix login flow"

    def test_distinct_coding_prompt_wins_over_stale_task_md(self, tmp_path):
        (tmp_path / ".agentpack").mkdir()
        (tmp_path / ".agentpack" / "task.md").write_text("migrate DB schema")
        result = _resolve_task(tmp_path, "fix login bug")
        assert result == "fix login bug"

    def test_distinct_coding_prompt_can_be_ignored_when_switch_detection_disabled(self, tmp_path):
        (tmp_path / ".agentpack").mkdir()
        (tmp_path / ".agentpack" / "task.md").write_text("migrate DB schema")
        result = _resolve_task(tmp_path, "fix login bug", task_switch_detection=False)
        assert result == "migrate DB schema"

    def test_coding_prompt_used_when_no_task_md(self, tmp_path):
        (tmp_path / ".agentpack").mkdir()
        result = _resolve_task(tmp_path, "fix the auth token")
        assert result == "fix the auth token"

    def test_slash_command_falls_back_to_auto(self, tmp_path):
        (tmp_path / ".agentpack").mkdir()
        result = _resolve_task(tmp_path, "/caveman ultra")
        assert result == "auto"

    def test_non_coding_prompt_falls_back_to_auto(self, tmp_path):
        (tmp_path / ".agentpack").mkdir()
        result = _resolve_task(tmp_path, "why does the DB pool work?")
        assert result == "auto"


class TestTaskSwitchDetection:
    def test_detects_disjoint_coding_task(self):
        assert _looks_like_task_switch(
            "add production-grade Kundali generation API",
            "fix numerology dashboard layout",
        )

    def test_related_task_is_not_switch(self):
        assert not _looks_like_task_switch("fix login flow", "fix login button bug")

    def test_vague_prompt_is_not_switch(self):
        assert not _looks_like_task_switch("fix login flow", "can you fix these")

    def test_min_terms_requires_more_concrete_overlap(self):
        assert not _looks_like_task_switch("fix login flow", "fix dashboard", min_terms=2)
