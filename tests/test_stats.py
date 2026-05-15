from __future__ import annotations

from pathlib import Path

from agentpack.commands.stats import _freshness_diagnostics, _noise_diagnostics, _top_files_from_metadata
from agentpack.session.state import SessionState


def test_freshness_diagnostics_report_task_and_snapshot_mismatch(tmp_path: Path) -> None:
    task_path = tmp_path / ".agentpack" / "task.md"
    task_path.parent.mkdir()
    task_path.write_text("fix current bug\n", encoding="utf-8")
    missing_context = tmp_path / ".agentpack" / "missing.md"
    session = SessionState(
        active=True,
        started_at="2026-05-13T00:00:00+00:00",
        last_refresh_at="2026-05-13T00:00:00+00:00",
    )

    diagnostics = _freshness_diagnostics(
        root=tmp_path,
        meta={
            "task": "old task",
            "generated_at": "2026-05-13T01:00:00+00:00",
            "snapshot_root_hash": "old",
            "freshness_warnings": ["Task terms are broad/generic."],
        },
        session=session,
        current_root_hash="new",
        context_path=missing_context,
    )

    assert "Task terms are broad/generic." in diagnostics
    assert (
        ".agentpack/task.md differs from the latest packed task "
        "(packed: old task; current: fix current bug)."
    ) in diagnostics
    assert "Files changed since the latest pack; refresh before trusting top included files." in diagnostics
    assert "Recorded context path is missing: .agentpack/missing.md." in diagnostics
    assert "Session last refresh timestamp is older than latest pack metadata." in diagnostics


def test_freshness_diagnostics_reports_agent_mismatch(tmp_path: Path) -> None:
    session = SessionState(
        active=True,
        agent="generic",
        last_resolved_agent="antigravity",
        started_at="2026-05-13T00:00:00+00:00",
        last_refresh_at="2026-05-13T02:00:00+00:00",
    )

    diagnostics = _freshness_diagnostics(
        root=tmp_path,
        meta={
            "task": "fix",
            "agent": "antigravity",
            "generated_at": "2026-05-13T01:00:00+00:00",
            "snapshot_root_hash": "same",
        },
        session=session,
        current_root_hash="same",
        context_path=None,
    )

    assert any("Session agent is generic" in item and "antigravity" in item for item in diagnostics)


def test_noise_diagnostics_report_summary_and_precision_noise() -> None:
    diagnostics = _noise_diagnostics(
        top_files=[
            ("a.py", "summary", "filename keyword match"),
            ("b.py", "summary", "filename keyword match"),
            ("c.py", "summary", "filename keyword match"),
            ("d.py", "symbols", "modified"),
        ],
        accuracy_rows=[
            {
                "selection_precision": 0.01,
                "selection_token_precision": 0.1,
                "selection_token_precision_summary": 0.0,
                "selection_noise_paths": ["src/noisy.py", "src/noisy.py", "src/other.py"],
            }
        ],
    )

    assert "Latest pack is mostly summaries; use minimal mode or a narrower task for edit work." in diagnostics
    assert "Top files mostly matched by filename; task terms may be broad." in diagnostics
    assert "Selection file precision is very low; many selected files were not later changed." in diagnostics
    assert "Token precision is low; most packed tokens became noise in recent runs." in diagnostics
    assert "Try `agentpack pack --mode minimal --task auto` until task wording or scoring improves." in diagnostics
    assert "Summary token precision is 0%; summary context has not matched later edits." in diagnostics
    assert any("Repeated noisy paths: src/noisy.py (2x), src/other.py (1x)" == item for item in diagnostics)


def test_top_files_from_metadata_avoids_markdown_parse() -> None:
    top_files = _top_files_from_metadata({
        "selected_files_meta": [
            {"path": "src/a.py", "mode": "full", "why": "modified"},
            {"path": "src/b.py", "mode": "summary", "why": "filename keyword match"},
        ]
    })

    assert top_files == [
        ("src/a.py", "full", "modified"),
        ("src/b.py", "summary", "filename keyword match"),
    ]
