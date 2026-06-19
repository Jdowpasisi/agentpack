from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone

from agentpack.commands.doctor import (
    _agentignore_sync_findings,
    _latest_context_path,
    _publish_secret_findings,
    _release_hygiene_findings,
    _safe_fix,
    _source_checkout_warning,
    _thread_conflict_findings,
)
from agentpack.core.command_surface import installed_cli_status, refresh_commands
from agentpack.core.thread_context import append_thread_index, build_thread_index_row


def test_source_checkout_warning_when_importing_installed_package(tmp_path: Path) -> None:
    root = tmp_path
    (root / "src" / "agentpack").mkdir(parents=True)
    package_file = Path("/site-packages/agentpack/commands/doctor.py")

    warning = _source_checkout_warning(root, package_file, "/python", "/bin/agentpack")

    assert warning is not None
    assert "source checkout detected" in warning
    assert "pip install -e ." in warning


def test_source_checkout_warning_skips_local_source_import(tmp_path: Path) -> None:
    root = tmp_path
    source_pkg = root / "src" / "agentpack"
    source_pkg.mkdir(parents=True)
    package_file = source_pkg / "commands" / "doctor.py"

    assert _source_checkout_warning(root, package_file, "/python", "/bin/agentpack") is None


def test_release_hygiene_flags_generated_artifacts(tmp_path: Path, monkeypatch) -> None:
    class Result:
        returncode = 0
        stdout = "?? .agentpack/context.md\n M src/agentpack/commands/pack.py\n?? .coverage\n"

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: Result())

    findings = _release_hygiene_findings(tmp_path)

    assert findings
    assert ".agentpack/context.md" in findings[0]
    assert ".coverage" in findings[0]
    assert "pack.py" not in findings[0]


def test_publish_secret_findings_warns_when_npm_token_missing(tmp_path: Path) -> None:
    (tmp_path / "npm").mkdir()
    (tmp_path / "npm" / "package.json").write_text("{}", encoding="utf-8")

    findings = _publish_secret_findings(tmp_path, env={})

    assert findings
    assert "NPM_TOKEN" in findings[0]


def test_publish_secret_findings_accepts_npm_token(tmp_path: Path) -> None:
    (tmp_path / "npm").mkdir()
    (tmp_path / "npm" / "package.json").write_text("{}", encoding="utf-8")

    assert _publish_secret_findings(tmp_path, env={"NPM_TOKEN": "secret"}) == []


def test_latest_context_path_uses_metadata_path(tmp_path: Path) -> None:
    agentpack_dir = tmp_path / ".agentpack"
    agentpack_dir.mkdir()
    (agentpack_dir / "context.md").write_text("fresh", encoding="utf-8")
    (agentpack_dir / "context.claude.md").write_text("old", encoding="utf-8")
    (agentpack_dir / "pack_metadata.json").write_text(
        '{"context_path": ".agentpack/context.md"}',
        encoding="utf-8",
    )

    assert _latest_context_path(tmp_path) == agentpack_dir / "context.md"


def test_agentignore_sync_findings_warn_when_import_block_stale(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("backend/.serverless/\n", encoding="utf-8")
    (tmp_path / ".agentignore").write_text("custom/\n", encoding="utf-8")

    findings = _agentignore_sync_findings(tmp_path)

    assert findings == ["imported .agentignore rules are stale; run `agentpack ignore sync`."]


def test_agentignore_sync_findings_report_synced_imports(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("agentpack.core.ignore._git_config_excludesfile", lambda: None)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / ".gitignore").write_text("backend/.serverless/\n", encoding="utf-8")
    status = tmp_path / ".agentignore"
    status.write_text(
        "custom/\n\n"
        "# agentpack:imported-gitignore:start\n"
        "# Imported from git ignore sources because these look like generated/noisy paths\n"
        "backend/.serverless/\n"
        "# agentpack:imported-gitignore:end\n",
        encoding="utf-8",
    )

    findings = _agentignore_sync_findings(tmp_path)

    assert findings
    assert findings[0].startswith("synced: Imported 1 generated/noisy rules")


def test_doctor_safe_fix_syncs_agentignore(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("agentpack.core.ignore._git_config_excludesfile", lambda: None)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / ".gitignore").write_text("backend/.serverless/\n", encoding="utf-8")

    _safe_fix(tmp_path, "generic")

    content = (tmp_path / ".agentignore").read_text(encoding="utf-8")
    assert "backend/.serverless/" in content


def test_doctor_thread_conflict_findings_report_overlap(tmp_path: Path) -> None:
    current = build_thread_index_row(
        root=tmp_path,
        thread_id="thread-a",
        task="fix auth",
        branch="main",
        selected_files=["src/auth.py"],
        dirty_files=[],
        status="in_progress",
    )
    other = build_thread_index_row(
        root=tmp_path,
        thread_id="thread-b",
        task="fix auth tests",
        branch="main",
        selected_files=["src/auth.py", "tests/test_auth.py"],
        dirty_files=[],
        status="in_progress",
    )
    stamp = datetime.now(timezone.utc).isoformat()
    current["updated_at"] = stamp
    other["updated_at"] = stamp
    append_thread_index(tmp_path, current)
    append_thread_index(tmp_path, other)

    findings = _thread_conflict_findings(tmp_path)

    assert findings
    assert "thread-a overlaps thread-b" in findings[0] or "thread-b overlaps thread-a" in findings[0]


def test_command_surface_status_reports_repair_command() -> None:
    status = installed_cli_status()

    assert status["agentpack_version"]
    assert "importable_commands" in status
    assert status["repair_command"]
    assert refresh_commands("auto").primary.startswith("agentpack ")
