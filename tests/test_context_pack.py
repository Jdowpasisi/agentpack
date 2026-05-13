from pathlib import Path
from agentpack.application.pack_service import _summary_cap_for_mode, _summary_score_floor
from agentpack.core.config import DEFAULT_CONFIG
from agentpack.core.context_pack import save_pack_metadata, select_files
from agentpack.core.models import ContextPack, FileInfo
from agentpack.renderers.markdown import render_claude


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


def test_summary_score_floor_excludes_weak_unchanged_files():
    fi = _fi("weak.py")
    selected, receipts = select_files(
        files=[fi],
        scored=[(fi, 10.0, ["content keyword match (1)"])],
        changed_paths=set(),
        summaries={"weak.py": {"summary": "Weak match.", "symbols": []}},
        mode="balanced",
        budget=10000,
        max_file_tokens=4000,
        min_summary_score=60,
    )
    assert selected == []
    assert receipts[0].reason == "summary score below floor"


def test_summary_score_floor_keeps_changed_files():
    f = _fi("changed.py", tokens=5)
    selected, _ = select_files(
        files=[f],
        scored=[(f, 10.0, ["modified"])],
        changed_paths={"changed.py"},
        summaries={},
        mode="balanced",
        budget=10000,
        max_file_tokens=4000,
        min_summary_score=60,
    )
    assert len(selected) == 1


def test_summary_cap_limits_unchanged_summaries():
    files = [_fi(f"file{i}.py") for i in range(3)]
    scored = [(fi, 100.0 - i, ["filename keyword match"]) for i, fi in enumerate(files)]
    selected, receipts = select_files(
        files=files,
        scored=scored,
        changed_paths=set(),
        summaries={fi.path: {"summary": f"Summary {i}", "symbols": []} for i, fi in enumerate(files)},
        mode="balanced",
        budget=10000,
        max_file_tokens=4000,
        max_summary_files=2,
    )
    assert [sf.path for sf in selected] == ["file0.py", "file1.py"]
    assert any(r.reason == "summary cap reached" for r in receipts)


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


def test_render_includes_freshness_metadata():
    pack = ContextPack(
        task="fix auth",
        agent="claude",
        mode="balanced",
        budget=1000,
        token_estimate=100,
        raw_repo_tokens=1000,
        after_ignore_tokens=800,
        estimated_savings_percent=90.0,
        changed_files=[],
        selected_files=[],
        receipts=[],
        freshness={
            "generated_at": "2026-05-13T00:00:00+00:00",
            "git_branch": "codex/example",
            "git_sha": "abc123",
            "task_source": "task.md",
            "changed_files_source": "git working tree",
            "snapshot_root_hash": "root123",
            "dirty_files_count": 2,
        },
        freshness_warnings=["Task terms are broad/generic; pack tightened weak-summary selection."],
    )

    rendered = render_claude(pack)

    assert "## Freshness" in rendered
    assert "**Generated:** 2026-05-13T00:00:00+00:00" in rendered
    assert "**Task source:** task.md" in rendered
    assert "Refresh recommended" in rendered


def test_save_pack_metadata_persists_freshness(tmp_path):
    (tmp_path / ".agentpack").mkdir()
    save_pack_metadata(
        tmp_path,
        context_path=".agentpack/context.md",
        snapshot_root_hash="root123",
        task="fix auth",
        agent="generic",
        mode="balanced",
        budget=1000,
        token_estimate=100,
        freshness={
            "generated_at": "2026-05-13T00:00:00+00:00",
            "git_sha": "abc123",
            "task_source": "task.md",
            "changed_files_source": "git working tree",
        },
        freshness_warnings=["refresh"],
        selected_files=[
            {
                "path": "src/auth.py",
                "mode": "full",
                "score": 100,
                "why": "modified",
                "tokens": 10,
            }
        ],
    )
    meta = (tmp_path / ".agentpack" / "pack_metadata.json").read_text()
    assert '"git_sha": "abc123"' in meta
    assert '"task_source": "task.md"' in meta
    assert '"freshness_warnings": [' in meta
    assert '"selected_files_meta": [' in meta
    assert '"path": "src/auth.py"' in meta


def test_generic_task_tightens_summary_floor_and_cap():
    cfg = DEFAULT_CONFIG
    assert _summary_score_floor(cfg, 0.6) > cfg.context.min_summary_score
    assert _summary_cap_for_mode(cfg, "balanced", 0.6) < cfg.context.max_summary_files_balanced
