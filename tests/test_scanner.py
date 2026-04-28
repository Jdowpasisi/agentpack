import pytest
from pathlib import Path
import pathspec

from agentpack.core.scanner import scan, file_hash
from agentpack.core.ignore import load_spec, DEFAULT_AGENTIGNORE


def _spec() -> pathspec.PathSpec:
    return pathspec.PathSpec.from_lines("gitignore", DEFAULT_AGENTIGNORE.splitlines())


def test_scan_excludes_ignored(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.js").write_text("module.exports = {}")

    spec = _spec()
    files = scan(tmp_path, spec)
    paths = {f.path for f in files}
    active_paths = {f.path for f in files if not f.ignored and not f.binary}

    assert "src/main.py" in paths
    assert not any("node_modules" in p for p in active_paths)


def test_scan_marks_ignored(tmp_path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("x")

    spec = _spec()
    files = scan(tmp_path, spec)
    ignored = [f for f in files if f.ignored]
    assert any("node_modules" in f.path for f in ignored)


def test_hash_changes_with_content(tmp_path):
    f = tmp_path / "file.py"
    f.write_text("version 1")
    h1 = file_hash(f)
    f.write_text("version 2")
    h2 = file_hash(f)
    assert h1 != h2


def test_hash_stable(tmp_path):
    f = tmp_path / "file.py"
    f.write_text("stable content")
    assert file_hash(f) == file_hash(f)


def test_token_estimation(tmp_path):
    f = tmp_path / "big.py"
    content = "x" * 400
    f.write_text(content)
    spec = _spec()
    files = scan(tmp_path, spec)
    fi = next(x for x in files if x.path == "big.py")
    # tiktoken gives exact counts; len//4 is the fallback — either way > 0
    assert fi.estimated_tokens > 0
    # 400 chars of 'x' is ~50-100 tokens depending on estimator
    assert fi.estimated_tokens <= 400
