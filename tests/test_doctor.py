from __future__ import annotations

from pathlib import Path

from agentpack.commands.doctor import _latest_context_path, _release_hygiene_findings, _source_checkout_warning


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
