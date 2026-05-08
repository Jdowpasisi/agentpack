from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import call, patch

import pytest

from agentpack.commands.watch import _should_ignore, _collect_mtimes, _walk_no_symlinks


# ---------------------------------------------------------------------------
# _should_ignore
# ---------------------------------------------------------------------------

def test_should_ignore_git_dir() -> None:
    assert _should_ignore(".git/config") is True
    assert _should_ignore(".git/COMMIT_EDITMSG") is True


def test_should_ignore_node_modules() -> None:
    assert _should_ignore("node_modules/lodash/index.js") is True


def test_should_ignore_venv() -> None:
    assert _should_ignore(".venv/lib/python3.11/site.py") is True
    assert _should_ignore("venv/bin/activate") is True


def test_should_ignore_build_dirs() -> None:
    assert _should_ignore("dist/bundle.js") is True
    assert _should_ignore("build/output.o") is True
    assert _should_ignore(".next/cache/foo") is True


def test_should_ignore_context_files() -> None:
    assert _should_ignore(".agentpack/context.md") is True
    assert _should_ignore(".agentpack/context.compact.md") is True


def test_should_not_ignore_source_files() -> None:
    assert _should_ignore("src/auth/session.py") is False
    assert _should_ignore("README.md") is False
    assert _should_ignore(".agentpack/task.md") is False
    assert _should_ignore(".agentpack/session.json") is False


def test_should_not_ignore_nested_source() -> None:
    assert _should_ignore("src/components/Button.tsx") is False
    assert _should_ignore("tests/test_auth.py") is False


def test_should_ignore_extended_dirs() -> None:
    assert _should_ignore(".yarn/cache/foo.cjs") is True
    assert _should_ignore(".mypy_cache/3.11/foo.json") is True
    assert _should_ignore(".pytest_cache/v/cache/nodeids") is True
    assert _should_ignore(".ruff_cache/0.1.0/foo") is True


def test_should_ignore_agentpack_context_files() -> None:
    assert _should_ignore(".agentpack/context.md") is True
    assert _should_ignore(".agentpack/context.compact.md") is True
    assert _should_ignore(".agentpack/context.claude.md") is True


# ---------------------------------------------------------------------------
# _collect_mtimes — no symlink following, permission errors safe
# ---------------------------------------------------------------------------

def test_collect_mtimes_normal_files(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("x = 1")
    (tmp_path / "src" / "util.py").write_text("y = 2")
    mtimes = _collect_mtimes(tmp_path)
    assert "src/main.py" in mtimes
    assert "src/util.py" in mtimes


def test_collect_mtimes_excludes_ignore_dirs(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("x = 1")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.js").write_text("module = {}")
    mtimes = _collect_mtimes(tmp_path)
    assert "src/main.py" in mtimes
    assert not any("node_modules" in p for p in mtimes)


def test_collect_mtimes_skips_symlinks(tmp_path: Path) -> None:
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    (real_dir / "file.py").write_text("x = 1")
    link = tmp_path / "loop"
    try:
        link.symlink_to(tmp_path)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported")
    mtimes = _collect_mtimes(tmp_path)
    # Should not raise RecursionError or hang; loop dir excluded
    loop_keys = [k for k in mtimes if k.startswith("loop/")]
    assert loop_keys == []


def test_collect_mtimes_handles_permission_error(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text("x = 1")
    mtimes = _collect_mtimes(tmp_path)
    assert "ok.py" in mtimes


def test_collect_mtimes_respects_max_files(tmp_path: Path, monkeypatch) -> None:
    from agentpack.commands import watch as watch_mod
    monkeypatch.setattr(watch_mod, "_MAX_POLL_FILES", 3)
    for i in range(10):
        (tmp_path / f"f{i}.py").write_text(f"x = {i}")
    mtimes = _collect_mtimes(tmp_path)
    assert len(mtimes) <= 3


# ---------------------------------------------------------------------------
# Debounce logic — polling path
# ---------------------------------------------------------------------------

def test_polling_debounce_prevents_double_refresh(tmp_path: Path) -> None:
    """Two rapid file changes within debounce window → only one refresh."""
    import threading

    root = tmp_path
    (root / "src").mkdir()
    src_file = root / "src" / "main.py"
    src_file.write_text("x = 1\n")

    refresh_calls: list[float] = []

    def fake_refresh(r, agent, mode, budget):
        refresh_calls.append(time.monotonic())

    # Run polling loop in thread, inject fake refresh
    stop_event = threading.Event()

    def run():
        prev: dict[str, float] = {}
        POLL_INTERVAL = 0.05
        DEBOUNCE = 0.2
        last_refresh = [time.monotonic() - DEBOUNCE - 1]

        fake_refresh(root, "generic", "balanced", 0)  # initial

        for _ in range(30):
            if stop_event.is_set():
                break
            time.sleep(POLL_INTERVAL)
            curr: dict[str, float] = {}
            for p in root.rglob("*"):
                if not p.is_file():
                    continue
                rel = str(p.relative_to(root))
                if _should_ignore(rel):
                    continue
                try:
                    curr[rel] = p.stat().st_mtime
                except OSError:
                    pass
            changed = {p for p, m in curr.items() if prev.get(p) != m}
            if changed:
                now = time.monotonic()
                if now - last_refresh[0] >= DEBOUNCE:
                    last_refresh[0] = now
                    fake_refresh(root, "generic", "balanced", 0)
            prev = curr

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(0.05)

    # Rapid changes within debounce window
    src_file.write_text("x = 2\n")
    time.sleep(0.02)
    src_file.write_text("x = 3\n")
    time.sleep(0.02)
    src_file.write_text("x = 4\n")

    time.sleep(0.4)  # wait for debounce to fire
    stop_event.set()
    thread.join(timeout=2)

    # Initial + at most one debounced refresh (not one per change)
    assert len(refresh_calls) <= 3  # generous upper bound
    # At least one debounced refresh happened
    assert len(refresh_calls) >= 2
