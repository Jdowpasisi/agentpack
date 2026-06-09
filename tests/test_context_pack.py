from pathlib import Path
import subprocess
import json
from agentpack.application.pack_service import _settle_rendered_token_estimate, _summary_cap_for_mode, _summary_score_floor
from agentpack.core.config import DEFAULT_CONFIG
from agentpack.core.context_pack import enrich_call_site_scores, save_pack_metadata, select_files, _selection_priority
from agentpack.core.models import ContextPack, FileInfo, OmittedRelevantFile, Receipt, SelectedFile
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


def test_large_dirty_file_uses_diff_mode(tmp_path):
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    f = tmp_path / "large.py"
    f.write_text("def old():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "large.py"], cwd=tmp_path, check=True)
    f.write_text("def old():\n    return 2\n" + "\n".join(f"# filler {i}" for i in range(2000)), encoding="utf-8")
    fi = FileInfo(
        path="large.py",
        abs_path=f,
        size_bytes=f.stat().st_size,
        estimated_tokens=5000,
        hash="h2",
        language="python",
    )

    selected, _ = select_files(
        files=[fi],
        scored=[(fi, 100.0, ["modified"])],
        changed_paths={"large.py"},
        summaries={},
        mode="balanced",
        budget=3000,
        max_file_tokens=4000,
    )

    assert selected[0].include_mode == "diff"
    assert "diff --git" in selected[0].content
    assert "# filler 1999" not in selected[0].content


def test_high_score_unchanged_file_uses_skeleton_mode():
    fi = _fi("src/service.py", tokens=2000)
    summaries = {
        "src/service.py": {
            "summary": "Service orchestration.",
            "imports": ["src.db", "src.models"],
            "symbols": [
                {
                    "name": "BillingService",
                    "kind": "class",
                    "start_line": 1,
                    "end_line": 20,
                    "signature": "class BillingService:",
                },
                {
                    "name": "charge",
                    "kind": "function",
                    "start_line": 22,
                    "end_line": 35,
                    "signature": "def charge(invoice_id: str) -> None:",
                },
            ],
        }
    }

    selected, _ = select_files(
        files=[fi],
        scored=[(fi, 180.0, ["filename keyword match"])],
        changed_paths=set(),
        summaries=summaries,
        mode="balanced",
        budget=10000,
        max_file_tokens=4000,
    )

    assert selected[0].include_mode == "skeleton"
    assert "class BillingService" in selected[0].content
    assert "src.db" in selected[0].content


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


def test_budget_exhausted_files_can_be_collected_as_omitted_relevant():
    files = [
        _fi("src/refund_service.py", tokens=100),
        _fi("api/routes/refund.py", tokens=1000),
    ]
    omitted: list[OmittedRelevantFile] = []

    selected, receipts = select_files(
        files=files,
        scored=[
            (files[0], 250.0, ["filename keyword match"]),
            (files[1], 210.0, ["reverse dependency of src/refund_service.py"]),
        ],
        changed_paths=set(),
        summaries={},
        mode="balanced",
        budget=250,
        max_file_tokens=4000,
        omitted_relevant_files=omitted,
    )

    assert [sf.path for sf in selected] == ["src/refund_service.py"]
    assert any(r.path == "api/routes/refund.py" and r.reason == "budget exhausted" for r in receipts)
    assert omitted[0].path == "api/routes/refund.py"
    assert omitted[0].score == 210.0
    assert omitted[0].risk == "high"
    assert omitted[0].suggested_mode == "summary"


def test_call_site_expansion_boosts_files_calling_selected_symbols():
    service = _fi("payments/refund_service.py", tokens=100)
    route = _fi("api/routes/refund.py", tokens=100)
    summaries = {
        service.path: {
            "summary": "Refund service.",
            "symbols": [
                {
                    "name": "refund_order",
                    "kind": "function",
                    "start_line": 1,
                    "end_line": 3,
                    "signature": "def refund_order(order_id):",
                }
            ],
            "defines": ["refund_order"],
            "calls": [],
        },
        route.path: {
            "summary": "Refund API route.",
            "symbols": [],
            "defines": [],
            "calls": ["refund_order"],
        },
    }
    selected = [
        SelectedFile(
            path=service.path,
            language="python",
            score=250,
            include_mode="full",
            reasons=["modified"],
        )
    ]

    expanded, count = enrich_call_site_scores(
        scored=[
            (service, 250.0, ["modified"]),
            (route, 20.0, ["score floor candidate"]),
        ],
        selected=selected,
        summaries=summaries,
        changed_paths={service.path},
    )

    route_item = next(item for item in expanded if item[0].path == route.path)
    assert count == 1
    assert route_item[1] > 20.0
    assert "caller of selected symbol `refund_order`" in route_item[2]


def test_call_site_omissions_are_high_risk_budget_exclusions():
    service = _fi("payments/refund_service.py", tokens=100)
    route = _fi("api/routes/refund.py", tokens=1000)
    summaries = {
        service.path: {
            "summary": "Refund service.",
            "symbols": [
                {
                    "name": "refund_order",
                    "kind": "function",
                    "start_line": 1,
                    "end_line": 3,
                    "signature": "def refund_order(order_id):",
                }
            ],
            "defines": ["refund_order"],
            "calls": [],
        },
        route.path: {
            "summary": "Refund API route.",
            "symbols": [
                {
                    "name": f"route_helper_{i}",
                    "kind": "function",
                    "start_line": i + 1,
                    "end_line": i + 1,
                    "signature": f"def route_helper_{i}(request, response, refund_context):",
                }
                for i in range(30)
            ],
            "defines": [],
            "calls": ["controller.refund_order"],
        },
    }

    selected, _receipts = select_files(
        files=[service, route],
        scored=[
            (service, 250.0, ["modified"]),
            (route, 80.0, ["score floor candidate"]),
        ],
        changed_paths={service.path},
        summaries=summaries,
        mode="balanced",
        budget=300,
        max_file_tokens=4000,
        min_summary_score=100,
    )
    expanded, count = enrich_call_site_scores(
        scored=[
            (service, 250.0, ["modified"]),
            (route, 80.0, ["score floor candidate"]),
        ],
        selected=selected,
        summaries=summaries,
        changed_paths={service.path},
    )
    omitted: list[OmittedRelevantFile] = []

    selected, receipts = select_files(
        files=[service, route],
        scored=expanded,
        changed_paths={service.path},
        summaries=summaries,
        mode="balanced",
        budget=300,
        max_file_tokens=4000,
        min_summary_score=100,
        omitted_relevant_files=omitted,
    )

    assert count == 1
    assert [sf.path for sf in selected] == [service.path]
    assert any(r.path == route.path and r.reason == "budget exhausted" for r in receipts)
    assert omitted[0].path == route.path
    assert omitted[0].risk == "high"
    assert "caller of selected symbol `refund_order`" in omitted[0].reasons


def test_reserve_bucket_order_seeds_tests_docs_and_deps():
    changed = _fi("src/noise.py", tokens=100)
    test = _fi("tests/test_auth.py", tokens=100)
    doc = _fi("docs/auth.md", tokens=100)
    dep = _fi("src/auth_service.py", tokens=100)
    other = _fi("src/other.py", tokens=100)

    selected, _ = select_files(
        files=[changed, test, doc, dep, other],
        scored=[
            (changed, 500.0, ["modified"]),
            (other, 490.0, ["filename keyword match"]),
            (test, 120.0, ["test for high-scoring src/auth.py"]),
            (doc, 110.0, ["knowledge/architecture doc"]),
            (dep, 100.0, ["direct dependency of changed file"]),
        ],
        changed_paths={"src/noise.py"},
        summaries={},
        mode="balanced",
        budget=10000,
        max_file_tokens=4000,
    )

    assert [sf.path for sf in selected[:4]] == [
        "src/noise.py",
        "tests/test_auth.py",
        "docs/auth.md",
        "src/auth_service.py",
    ]


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


def test_weak_signal_candidates_are_capped_and_compressed_to_summary():
    files = [_fi(f"file{i}.py", tokens=1500) for i in range(3)]
    summaries = {
        fi.path: {
            "summary": f"Summary {i}",
            "imports": [f"pkg{i}"],
            "symbols": [{
                "name": f"Service{i}",
                "kind": "class",
                "start_line": 1,
                "end_line": 10,
                "signature": f"class Service{i}:",
            }],
        }
        for i, fi in enumerate(files)
    }
    scored = [
        (fi, 180.0 - i, ["filename keyword match", "broad-task weak-signal dampening"])
        for i, fi in enumerate(files)
    ]

    selected, receipts = select_files(
        files=files,
        scored=scored,
        changed_paths=set(),
        summaries=summaries,
        mode="balanced",
        budget=10000,
        max_file_tokens=4000,
        max_summary_files=5,
        max_weak_signal_files=1,
    )

    assert [sf.path for sf in selected] == ["file0.py"]
    assert selected[0].include_mode == "summary"
    assert "weak-signal file compressed to summary" in selected[0].reasons
    assert any(r.reason == "weak-signal cap reached" for r in receipts)


def test_selection_priority_lifts_paired_tests() -> None:
    src = _fi("src/types.py", tokens=1000)
    test = _fi("tests/test_types.py", tokens=1000)

    src_priority = _selection_priority((src, 250.0, ["filename keyword match"]), set(), 4000)
    test_priority = _selection_priority((test, 230.0, ["test for high-scoring src/types.py"]), set(), 4000)

    assert test_priority > src_priority


def test_negative_summary_cap_disables_summaries():
    fi = _fi("file.py")
    selected, receipts = select_files(
        files=[fi],
        scored=[(fi, 100.0, ["content keyword match (1)"])],
        changed_paths=set(),
        summaries={fi.path: {"summary": "Noisy summary.", "symbols": []}},
        mode="balanced",
        budget=10000,
        max_file_tokens=4000,
        max_summary_files=-1,
    )
    assert selected == []
    assert any(r.reason == "summaries disabled by precision guard" for r in receipts)


def test_strict_summary_selection_requires_support_signal():
    fi = _fi("file.py")
    selected, receipts = select_files(
        files=[fi],
        scored=[(fi, 100.0, ["filename keyword match"])],
        changed_paths=set(),
        summaries={fi.path: {"summary": "Noisy summary.", "symbols": []}},
        mode="balanced",
        budget=10000,
        max_file_tokens=4000,
        strict_summary_selection=True,
    )
    assert selected == []
    assert any(r.reason == "summary needs stronger support signal" for r in receipts)


def test_strict_summary_selection_keeps_supported_summary():
    fi = _fi("file.py")
    selected, _ = select_files(
        files=[fi],
        scored=[(fi, 100.0, ["filename keyword match", "direct dependency of changed file"])],
        changed_paths=set(),
        summaries={fi.path: {"summary": "Supported summary.", "symbols": []}},
        mode="balanced",
        budget=10000,
        max_file_tokens=4000,
        strict_summary_selection=True,
    )
    assert len(selected) == 1
    assert selected[0].include_mode == "summary"


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
            "workspace_roots": ["apps/dashboard", "packages/core"],
            "snapshot_root_hash": "root123",
            "dirty_files_count": 2,
        },
        freshness_warnings=["Task terms are broad/generic; pack tightened weak-summary selection."],
        execution_state={
            "task": {
                "status": "in_progress",
                "summary": "Budget done.",
                "state_file": ".agentpack/task_state.md",
                "checklist": {"done": 1, "open": 2, "blocked": 0},
            },
            "git": {
                "branch": "main",
                "sha": "abc123456789",
                "staged_count": 1,
                "unstaged_count": 2,
                "untracked_count": 3,
                "ahead": 1,
                "behind": 0,
            },
            "runtime": {"docker": "running", "compose_file": "docker-compose.yml"},
        },
        concurrent_context={
            "thread_id": "thread-a",
            "active_threads": 2,
            "conflicts": [
                {
                    "thread_id": "thread-b",
                    "task": "edit auth",
                    "status": "in_progress",
                    "overlap": ["src/auth.py"],
                    "overlap_count": 1,
                }
            ],
        },
    )

    rendered = render_claude(pack)

    assert "## Freshness" in rendered
    assert "<!-- agentpack:freshness" in rendered
    freshness_json = rendered.split("<!-- agentpack:freshness", 1)[1].split("-->", 1)[0]
    freshness = json.loads(freshness_json)
    assert freshness["active_context"] == "mcp"
    assert freshness["fallback_context"] == "markdown"
    assert freshness["snapshot_root_hash"] == "root123"
    assert freshness["refresh_required"] is False
    assert freshness["guard_command"] == "agentpack guard --agent auto --repair-stale --refresh-context"
    assert "**Generated:** 2026-05-13T00:00:00+00:00" in rendered
    assert "**Task source:** task.md" in rendered
    assert "**Workspaces:** apps/dashboard, packages/core" in rendered
    assert "Refresh recommended" in rendered
    assert "## Execution State" in rendered
    assert "**Task status:** in_progress" in rendered
    assert "## Concurrent Context" in rendered
    assert "`thread-b`" in rendered
    assert "If this pack's task does not match the user's current task" in rendered
    assert "agentpack pack --task auto" in rendered


def test_context_pack_renders_agent_lessons():
    pack = ContextPack(
        task="Add CLI learning summaries",
        agent="generic",
        mode="balanced",
        budget=1000,
        token_estimate=100,
        raw_repo_tokens=1000,
        after_ignore_tokens=800,
        estimated_savings_percent=90.0,
        selected_files=[],
        omitted_relevant_files=[],
        receipts=[],
        changed_files=[],
        agent_lessons="- When editing CLI commands, update command docs and CLI tests.",
    )

    rendered = render_claude(pack)

    assert "## Agent Lessons From Prior Work" in rendered
    assert "update command docs" in rendered


def test_render_compresses_excluded_receipts_and_lists_token_consumers():
    selected = SelectedFile(
        path="src/big.py",
        language="python",
        score=100,
        include_mode="full",
        reasons=["modified"],
        content="print('x')\n" * 100,
    )
    pack = ContextPack(
        task="fix auth",
        agent="claude",
        mode="balanced",
        budget=1000,
        token_estimate=100,
        raw_repo_tokens=1000,
        after_ignore_tokens=800,
        estimated_savings_percent=90.0,
        changed_files=["src/big.py"],
        selected_files=[selected],
        receipts=[
            Receipt(path="src/big.py", action="included", reason="modified"),
            *[
                Receipt(path=f"src/omitted_{i}.py", action="excluded", reason="budget exhausted")
                for i in range(12)
            ],
        ],
    )

    rendered = render_claude(pack)

    assert "## Largest Token Consumers" in rendered
    assert "| `src/big.py` | full |" in rendered
    assert "12 file(s) excluded because budget exhausted" in rendered
    assert "`src/omitted_9.py`" in rendered
    assert "`src/omitted_10.py`" not in rendered
    assert "+2 more" in rendered


def test_render_lists_omitted_but_relevant_files_before_file_context():
    pack = ContextPack(
        task="fix refunds",
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
        omitted_relevant_files=[
            OmittedRelevantFile(
                path="api/routes/refund.py",
                score=210,
                reasons=["reverse dependency of payments/refund_service.py"],
                estimated_tokens=900,
                suggested_mode="summary",
                risk="high",
            )
        ],
    )

    rendered = render_claude(pack)

    assert "## Omitted But Relevant Files" in rendered
    assert rendered.index("## Omitted But Relevant Files") < rendered.index("## File Context")
    assert "`api/routes/refund.py`" in rendered
    assert "inspect caller" in rendered
    assert "Do not assume omitted relevant files are safe" in rendered


def test_rendered_token_estimate_includes_markdown_overhead():
    pack = ContextPack(
        task="fix auth",
        agent="generic",
        mode="balanced",
        budget=1000,
        token_estimate=1,
        raw_repo_tokens=1000,
        after_ignore_tokens=800,
        estimated_savings_percent=90.0,
        changed_files=[],
        selected_files=[],
        receipts=[],
    )

    class Adapter:
        def render(self, current_pack: ContextPack) -> str:
            return f"# Context\nToken estimate: {current_pack.token_estimate}\n" + ("overhead " * 80)

    rendered_tokens = _settle_rendered_token_estimate(pack, Adapter())

    assert rendered_tokens > 1
    assert pack.token_estimate == rendered_tokens


def test_render_loud_stale_task_warning():
    pack = ContextPack(
        task="old task",
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
        freshness_warnings=[
            ".agentpack/task.md differs from the packed task; AgentPack-controlled context reads should auto-refresh."
        ],
    )

    rendered = render_claude(pack)

    assert "STALE TASK CONTEXT" in rendered
    freshness_json = rendered.split("<!-- agentpack:freshness", 1)[1].split("-->", 1)[0]
    freshness = json.loads(freshness_json)
    assert freshness["stale_task_context"] is True
    assert freshness["refresh_required"] is True
    assert "Do not trust selected files until refreshed" in rendered
    assert "agentpack_get_context()" in rendered
    assert "agentpack_pack_context()" in rendered


def test_select_files_caps_unrelated_changed_files_when_many_dirty():
    files = [_fi(f"src/noise_{i}.py", tokens=20) for i in range(6)]
    files.append(_fi("src/auth.py", tokens=20))
    changed = {fi.path for fi in files}
    scored = [(fi, 100, ["modified"]) for fi in files[:6]]
    scored.append((files[-1], 140, ["modified", "symbol keyword match"]))

    selected, receipts = select_files(
        files=files,
        scored=scored,
        changed_paths=changed,
        summaries={},
        mode="balanced",
        budget=10000,
        max_file_tokens=1000,
    )

    selected_paths = {sf.path for sf in selected}
    capped = [r for r in receipts if r.reason == "unrelated changed-file safety cap"]
    assert "src/auth.py" in selected_paths
    assert len([path for path in selected_paths if "noise" in path]) == 3
    assert len(capped) == 3


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
    assert '"task_hash":' in meta
    assert '"task_source": "task.md"' in meta
    assert '"freshness_warnings": [' in meta
    assert '"selected_files_meta": [' in meta
    assert '"path": "src/auth.py"' in meta


def test_generic_task_tightens_summary_floor_and_cap():
    cfg = DEFAULT_CONFIG
    assert _summary_score_floor(cfg, 0.6) > cfg.context.min_summary_score
    assert _summary_cap_for_mode(cfg, "balanced", 0.6) < cfg.context.max_summary_files_balanced
