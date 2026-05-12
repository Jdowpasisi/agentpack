from __future__ import annotations

from pathlib import Path

from agentpack.commands.doctor import _source_checkout_warning


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
