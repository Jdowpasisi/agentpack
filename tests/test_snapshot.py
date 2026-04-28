import pytest
from agentpack.core.snapshot import build_snapshot, save_snapshot, load_snapshot
from agentpack.core.models import FileInfo
from pathlib import Path


def _fi(path: str, hash_val: str = "abc123", tokens: int = 100) -> FileInfo:
    return FileInfo(
        path=path,
        abs_path=Path(path),
        size_bytes=400,
        estimated_tokens=tokens,
        hash=hash_val,
        language="python",
    )


def test_build_snapshot_contains_files():
    files = [_fi("src/a.py", "h1"), _fi("src/b.py", "h2")]
    snap = build_snapshot(files)
    assert "src/a.py" in snap["files"]
    assert "src/b.py" in snap["files"]
    assert snap["version"] == 1
    assert "root_hash" in snap


def test_root_hash_changes_with_content():
    f1 = [_fi("src/a.py", "h1")]
    f2 = [_fi("src/a.py", "h2")]
    assert build_snapshot(f1)["root_hash"] != build_snapshot(f2)["root_hash"]


def test_save_and_load(tmp_path):
    files = [_fi("src/a.py", "h1")]
    snap = build_snapshot(files)
    save_snapshot(snap, tmp_path)
    loaded = load_snapshot(tmp_path)
    assert loaded is not None
    assert loaded["root_hash"] == snap["root_hash"]


def test_load_returns_none_when_missing(tmp_path):
    assert load_snapshot(tmp_path) is None


def test_ignored_files_excluded_from_snapshot():
    fi = FileInfo(
        path="node_modules/x.js",
        abs_path=Path("node_modules/x.js"),
        size_bytes=100,
        estimated_tokens=25,
        ignored=True,
    )
    snap = build_snapshot([fi])
    assert "node_modules/x.js" not in snap["files"]
