from __future__ import annotations

from agentpack.core.models import ContextPack, SelectedFile, Symbol
from agentpack.renderers.compact import render_compact


def _make_pack(selected: list[SelectedFile]) -> ContextPack:
    return ContextPack(
        task="fix login redirect",
        agent="generic",
        mode="balanced",
        budget=25000,
        token_estimate=12000,
        raw_repo_tokens=80000,
        after_ignore_tokens=70000,
        estimated_savings_percent=85.0,
        changed_files=["src/auth/session.py"],
        selected_files=selected,
        receipts=[],
    )


def test_compact_header_fields() -> None:
    pack = _make_pack([])
    output = render_compact(pack)
    assert "task: fix login redirect" in output
    assert "mode: balanced" in output
    assert "budget: 12000/25000" in output
    assert "generated:" in output


def test_compact_selected_section() -> None:
    sf = SelectedFile(
        path="src/auth/session.py",
        score=310,
        include_mode="full",
        reasons=["modified", "keyword:session"],
        symbols=[
            Symbol(name="create_session", kind="function", start_line=1, end_line=10),
            Symbol(name="revoke_session", kind="function", start_line=12, end_line=20),
        ],
    )
    pack = _make_pack([sf])
    output = render_compact(pack)

    assert "## selected" in output
    assert "src/auth/session.py" in output
    assert "score: 310" in output
    assert "include: full" in output
    assert "why: modified, keyword:session" in output
    assert "create_session" in output
    assert "revoke_session" in output


def test_compact_deps_section() -> None:
    sf = SelectedFile(
        path="src/auth/token.py",
        score=150,
        include_mode="summary",
        reasons=["direct_dep"],
    )
    pack = _make_pack([sf])
    output = render_compact(pack)

    assert "## deps" in output
    assert "src/auth/token.py" in output
    assert "score: 150" in output
    assert "why: direct_dep" in output
    # summary files should NOT appear in ## selected
    lines = output.splitlines()
    selected_start = next(i for i, l in enumerate(lines) if l == "## selected")
    deps_start = next(i for i, l in enumerate(lines) if l == "## deps")
    selected_block = "\n".join(lines[selected_start:deps_start])
    assert "src/auth/token.py" not in selected_block


def test_compact_separates_selected_from_deps() -> None:
    full_sf = SelectedFile(path="a.py", score=200, include_mode="full", reasons=["modified"])
    sym_sf = SelectedFile(path="b.py", score=180, include_mode="symbols", reasons=["keyword"])
    sum_sf = SelectedFile(path="c.py", score=100, include_mode="summary", reasons=["dep"])
    pack = _make_pack([full_sf, sym_sf, sum_sf])
    output = render_compact(pack)

    lines = output.splitlines()
    sel_idx = next(i for i, l in enumerate(lines) if l == "## selected")
    dep_idx = next(i for i, l in enumerate(lines) if l == "## deps")
    ins_idx = next(i for i, l in enumerate(lines) if l == "## instructions")

    selected_block = "\n".join(lines[sel_idx:dep_idx])
    deps_block = "\n".join(lines[dep_idx:ins_idx])

    assert "a.py" in selected_block
    assert "b.py" in selected_block
    assert "c.py" not in selected_block
    assert "c.py" in deps_block


def test_compact_empty_sections() -> None:
    pack = _make_pack([])
    output = render_compact(pack)
    assert "## selected" in output
    assert "## deps" in output
    assert "(none)" in output


def test_compact_instructions_block() -> None:
    pack = _make_pack([])
    output = render_compact(pack)
    assert "## instructions" in output
    assert "agentpack session refresh" in output
    assert "task.md" in output
