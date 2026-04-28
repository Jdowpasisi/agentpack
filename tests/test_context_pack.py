import pytest
from pathlib import Path
from agentpack.core.context_pack import select_files
from agentpack.core.models import FileInfo


def _fi(path: str, tokens: int = 100, hash_val: str = "h1") -> FileInfo:
    return FileInfo(
        path=path,
        abs_path=Path("/nonexistent") / path,
        size_bytes=tokens * 4,
        estimated_tokens=tokens,
        hash=hash_val,
        language="python",
    )


def test_selects_changed_file_as_full(tmp_path):
    f = tmp_path / "session.py"
    f.write_text("def login(): pass\n")
    fi = FileInfo(
        path="session.py",
        abs_path=f,
        size_bytes=20,
        estimated_tokens=5,
        hash="h1",
        language="python",
    )
    scored = [(fi, 100.0, ["modified"])]
    selected, receipts = select_files(
        files=[fi],
        scored=scored,
        changed_paths={"session.py"},
        summaries={},
        mode="balanced",
        budget=10000,
        max_file_tokens=4000,
    )
    assert len(selected) == 1
    assert selected[0].include_mode == "full"
    assert selected[0].content is not None


def test_budget_respected():
    files = [_fi(f"file{i}.py", tokens=1000) for i in range(20)]
    scored = [(fi, 80.0 - i, [f"reason {i}"]) for i, fi in enumerate(files)]
    # budget=500, summary fallback uses min(1000, 200)=200 per file -> max 2 files
    selected, _ = select_files(
        files=files,
        scored=scored,
        changed_paths=set(),
        summaries={},
        mode="balanced",
        budget=500,
        max_file_tokens=4000,
    )
    assert len(selected) <= 3


def test_excluded_ignored_files():
    fi = FileInfo(
        path="node_modules/x.js",
        abs_path=Path("/nonexistent/node_modules/x.js"),
        size_bytes=100,
        estimated_tokens=25,
        ignored=True,
    )
    scored = [(fi, 50.0, ["test"])]
    selected, receipts = select_files(
        files=[fi],
        scored=scored,
        changed_paths=set(),
        summaries={},
        mode="balanced",
        budget=10000,
        max_file_tokens=4000,
    )
    assert len(selected) == 0
    assert any(r.action == "excluded" for r in receipts)
