"""AgentPack MCP server — exposes context packing as MCP tools.

Start with:
    agentpack mcp

Or register in Claude Code settings:
    {
      "mcpServers": {
        "agentpack": {
          "command": "agentpack",
          "args": ["mcp"]
        }
      }
    }

Tools exposed:
    pack_context        — generate/refresh a context pack for a task
    get_context         — read the latest context pack (no repack)
    refresh             — refresh using the current task.md
    explain_file        — show score breakdown + symbols for a specific file
    get_related_files   — return import-graph neighbours of a file
    get_delta_context   — return selected-file delta since the previous pack
    get_stats           — token/saving stats for the latest pack
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from agentpack.core import git
from agentpack.core.token_estimator import estimate_tokens


def _repo_root() -> Path:
    """Walk up from cwd until .agentpack/ found; fall back to cwd."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".agentpack").exists():
            return parent
    return cwd


def _truncate_to_budget(text: str, max_tokens: int = 20000) -> str:
    """Truncate packed context to fit within max_tokens (estimated via tiktoken, falls back to len//4)."""
    if estimate_tokens(text) <= max_tokens:
        return text

    split_marker = "\n## File Context"
    marker_pos = text.find(split_marker)
    if marker_pos == -1:
        budget_chars = max_tokens * 4
        truncated = text[:budget_chars]
        omit_files = max(1, (len(text) - budget_chars) // 2000)
        return truncated + f"\n\n> [Truncated: {omit_files} files omitted to fit context window. Use get_context() to read full pack or narrow the task.]"

    header = text[:marker_pos]
    file_section = text[marker_pos:]

    if estimate_tokens(header) >= max_tokens:
        return header + "\n\n> [Truncated: file context omitted to fit context window. Use get_context() to read full pack or narrow the task.]"

    blocks = file_section.split("\n### ")
    # blocks[0] is the "## File Context" heading; blocks[1:] are individual files
    accumulated = blocks[0]
    total_files = len(blocks) - 1
    kept_files = 0
    for block in blocks[1:]:
        candidate = accumulated + "\n### " + block
        if estimate_tokens(header + candidate) > max_tokens:
            break
        accumulated = candidate
        kept_files += 1

    omitted = total_files - kept_files
    if omitted > 0:
        return header + accumulated + f"\n\n> [Truncated: {omitted} files omitted to fit context window. Use get_context() to read full pack or narrow the task.]"
    return header + accumulated


def _get_context_impl(root: Path) -> str:
    """Read the latest pre-built context pack from root, with staleness header."""
    pack_path = None
    for candidate in (
        root / ".agentpack" / "context.claude.md",
        root / ".agentpack" / "context.md",
    ):
        if candidate.exists():
            pack_path = candidate
            break
    if pack_path is None:
        return ""

    content = pack_path.read_text(encoding="utf-8")

    metadata_path = root / ".agentpack" / "pack_metadata.json"
    snapshot_path = root / ".agentpack" / "snapshots" / "latest.json"

    metadata = None
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:
            metadata = None

    snapshot = None
    if snapshot_path.exists():
        try:
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except Exception:
            snapshot = None

    generated_at = metadata.get("generated_at", "unknown") if metadata else "unknown"
    token_estimate = metadata.get("token_estimate", 0) if metadata else 0
    stale_reasons: list[str] = []

    if metadata is None or snapshot is None or metadata.get("snapshot_root_hash") != snapshot.get("root_hash"):
        stale_reasons.append("repo snapshot changed")
    if metadata:
        saved_sha = metadata.get("git_sha") or (metadata.get("freshness") or {}).get("git_sha")
        current_sha = git.current_sha(root) if git.is_git_repo(root) else None
        if saved_sha and current_sha and saved_sha != current_sha:
            stale_reasons.append("git HEAD changed")
        task_md = _task_md_body(root)
        if task_md and task_md != metadata.get("task"):
            stale_reasons.append(".agentpack/task.md differs")

    if stale_reasons:
        reason_text = ", ".join(stale_reasons)
        header = (
            f"> **Stale context** — {reason_text} since last pack "
            f"(generated: {generated_at}). Run pack_context() to refresh.\n\n"
        )
    else:
        header = f"> Context is fresh (generated: {generated_at}, {token_estimate:,} tokens).\n\n"

    return header + content


def _task_md_body(root: Path) -> str | None:
    path = root / ".agentpack" / "task.md"
    if not path.exists():
        return None
    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    lines = [line for line in content.splitlines() if line.strip() and not line.startswith("#")]
    body = lines[0].strip() if lines else ""
    if body and "Write or update the current coding task here." not in body:
        return body
    return None


def _explain_file_impl(root: Path, path: str, task: str = "") -> str:
    """Testable core of the explain_file MCP tool."""
    from agentpack.application.pack_service import PackPlanner, PackRequest, _sf_tokens
    from agentpack.adapters.detect import detect_agent

    resolved_task = task
    if not resolved_task:
        task_md = root / ".agentpack" / "task.md"
        resolved_task = task_md.read_text(encoding="utf-8").strip() if task_md.exists() else "general"

    plan = PackPlanner().plan(PackRequest(
        root=root,
        agent=detect_agent(root),
        task=resolved_task,
        mode="balanced",
        budget=0,
        since=None,
        refresh=False,
    ))

    score_map = {fi.path: (score, reasons) for fi, score, reasons in plan.scored}
    if path not in score_map:
        return f"File not found in scoring data: {path}"

    score_val, reasons = score_map[path]
    selected_file = next((sf for sf in plan.selected if sf.path == path), None)
    is_selected = selected_file is not None
    include_mode = selected_file.include_mode if selected_file else "excluded"

    token_count = 0
    if selected_file:
        token_count = _sf_tokens(selected_file)
    else:
        for fi in plan.scan_result.packable:
            if fi.path == path:
                token_count = fi.estimated_tokens
                break

    summary_data = plan.summaries.get(path, {})
    raw_symbols = summary_data.get("symbols", []) if isinstance(summary_data, dict) else []
    symbol_names = [s["name"] if isinstance(s, dict) else s.name for s in raw_symbols]

    lines = [
        f"## {path}",
        "",
        f"- **selected**: {'yes' if is_selected else 'no'}",
        f"- **include mode**: {include_mode}",
        f"- **score**: {score_val:.0f}",
        f"- **tokens**: {token_count:,}",
        f"- **task**: {resolved_task}",
        "",
        "### Score signals",
        "",
    ]
    if reasons:
        for reason in reasons:
            lines.append(f"- {reason}")
    else:
        lines.append("_(none)_")

    if symbol_names:
        lines += ["", "### Symbols", ""]
        lines += [f"- `{s}`" for s in symbol_names]

    dep_node = plan.dep_graph.get(path)
    if dep_node.imports:
        lines += ["", "### Imports", ""]
        lines += [f"- `{imp}`" for imp in dep_node.imports[:10]]
    if dep_node.imported_by:
        lines += ["", "### Imported by", ""]
        lines += [f"- `{imp}`" for imp in dep_node.imported_by[:10]]

    return "\n".join(lines)


def _get_related_files_impl(root: Path, path: str, depth: int = 1) -> str:
    """Testable core of the get_related_files MCP tool."""
    from agentpack.application.pack_service import PackPlanner, PackRequest
    from agentpack.adapters.detect import detect_agent

    depth = max(1, min(depth, 2))
    task_md = root / ".agentpack" / "task.md"
    task = task_md.read_text(encoding="utf-8").strip() if task_md.exists() else "general"

    plan = PackPlanner().plan(PackRequest(
        root=root,
        agent=detect_agent(root),
        task=task,
        mode="minimal",
        budget=0,
        since=None,
        refresh=False,
    ))

    graph = plan.dep_graph

    def _neighbours(p: str) -> dict[str, str]:
        node = graph.get(p)
        result: dict[str, str] = {}
        for imp in node.imports:
            result[imp] = "imports"
        for rev in node.imported_by:
            result[rev] = "imported_by"
        for test in node.tests:
            result[test] = "test"
        return result

    seen: dict[str, str] = {}
    frontier = {path}
    for hop in range(depth):
        next_frontier: set[str] = set()
        for p in frontier:
            for rel_path, rel_type in _neighbours(p).items():
                if rel_path != path and rel_path not in seen:
                    label = rel_type if hop == 0 else f"{rel_type} (hop {hop + 1})"
                    seen[rel_path] = label
                    next_frontier.add(rel_path)
        frontier = next_frontier

    if not seen:
        return f"No related files found for `{path}` at depth {depth}."

    lines = [f"## Related files for `{path}`", ""]
    for rel_path, rel_type in sorted(seen.items(), key=lambda x: x[1]):
        lines.append(f"- `{rel_path}` — {rel_type}")
    return "\n".join(lines)


def _get_stats_impl(root: Path) -> str:
    """Testable core of the get_stats MCP tool."""
    metadata_path = root / ".agentpack" / "pack_metadata.json"

    if not metadata_path.exists():
        return "No pack metadata found. Run pack_context() first."

    try:
        meta = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return f"Failed to read pack metadata: {exc}"

    lines = [
        "## AgentPack Stats",
        "",
        f"- **task**: {meta.get('task', 'unknown')}",
        f"- **generated_at**: {meta.get('generated_at', 'unknown')}",
        f"- **mode**: {meta.get('mode', 'unknown')}",
        f"- **budget**: {meta.get('budget', 0):,} tokens",
        f"- **packed_tokens**: {meta.get('token_estimate', 0):,}",
        f"- **agent**: {meta.get('agent', 'unknown')}",
    ]

    metrics_path = root / ".agentpack" / "metrics.jsonl"
    if metrics_path.exists():
        try:
            lines_raw = metrics_path.read_text(encoding="utf-8").splitlines()
            for line in reversed(lines_raw):
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                lines += [
                    "",
                    "### Last pack run",
                    "",
                    f"- **raw_tokens**: {rec.get('raw_tokens', 0):,}",
                    f"- **saving**: {rec.get('saving_pct', 0):.1f}%",
                    f"- **selected_files**: {rec.get('selected_files', 0)}",
                    f"- **changed_files**: {rec.get('changed_files', 0)}",
                    f"- **excluded_files**: {rec.get('excluded_files', 0)} (score too low)",
                    f"- **total_time**: {rec.get('total_s', 0):.2f}s",
                ]
                if rec.get("selection_f1"):
                    lines.append(f"- **selection_f1**: {rec['selection_f1']:.3f}")
                excluded_paths = rec.get("excluded_paths", [])
                if excluded_paths:
                    lines += ["", "### Below-threshold files (top 10)", ""]
                    for p in excluded_paths:
                        lines.append(f"- `{p}`")
                break
        except Exception:
            pass

    return "\n".join(lines)


def _get_delta_context_impl(root: Path, max_files: int = 12) -> str:
    """Return the latest saved delta summary and selected-file changes."""
    metadata_path = root / ".agentpack" / "pack_metadata.json"
    if not metadata_path.exists():
        return "No pack metadata found. Run pack_context() first."
    try:
        meta = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return f"Failed to read pack metadata: {exc}"

    freshness = meta.get("freshness") or {}
    delta = freshness.get("delta_summary") or "No selected-file delta recorded for the latest pack."
    selected = meta.get("selected_files_meta") or []
    lines = ["## AgentPack Delta", "", delta, ""]
    if selected:
        lines += ["### Current top selected files", ""]
        for item in selected[:max(1, max_files)]:
            if not isinstance(item, dict):
                continue
            path = item.get("path", "")
            mode = item.get("mode", "")
            why = item.get("why", "")
            suffix = f" — {why}" if why else ""
            lines.append(f"- `{path}` ({mode}){suffix}")
    return "\n".join(lines)


def serve() -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        print(
            "mcp package required for MCP server. "
            "Install: pip install 'agentpack-cli[mcp]'",
            file=sys.stderr,
        )
        sys.exit(1)

    mcp = FastMCP("agentpack")

    @mcp.tool()
    def pack_context(task: str, mode: str = "balanced", budget: int = 0, max_tokens: int = 20000) -> str:
        """Generate a ranked context pack for the given task.

        Args:
            task: Describe what you're working on (e.g. "fix auth token refresh").
            mode: minimal | balanced (default) | deep
            budget: Token budget, 0 = config default (usually 25000).
            max_tokens: Maximum tokens to return (default 20000). Increase for deep context.

        Returns the packed context as a markdown string.
        """
        from agentpack.application.pack_service import PackService, PackRequest
        from agentpack.adapters.detect import detect_agent
        from agentpack.renderers.markdown import render_claude

        root = _repo_root()
        agent = detect_agent(root)
        result = PackService().run(PackRequest(
            root=root,
            agent=agent,
            task=task,
            mode=mode,
            budget=budget,
            since=None,
            refresh=False,
        ))
        return _truncate_to_budget(render_claude(result.pack), max_tokens)

    @mcp.tool()
    def get_context() -> str:
        """Return the latest pre-built context pack without repacking.

        Fast — just reads the cached file. Use pack_context() to regenerate.
        Returns empty string if no pack exists yet.
        """
        return _get_context_impl(_repo_root())

    @mcp.tool()
    def refresh() -> str:
        """Refresh context using the current task.md (or git-inferred task).

        Equivalent to running `agentpack session refresh`.
        Returns summary of what was packed.
        """
        from agentpack.commands._shared import run_refresh
        from agentpack.session.state import load_session
        from agentpack.adapters.detect import detect_agent

        root = _repo_root()
        state = load_session(root)
        agent = state.agent if state else detect_agent(root)
        mode = state.mode if state else "balanced"

        result = run_refresh(root, agent, mode, 0)
        if result is None:
            return "Refresh failed."
        return (
            f"Refreshed: {result['files']} files, "
            f"{result['tokens']:,} tokens, "
            f"{result['saving']:.1f}% saving"
        )

    @mcp.tool()
    def explain_file(path: str, task: str = "") -> str:
        """Return score breakdown and symbol list for a specific file.

        Args:
            path: Repo-relative file path (e.g. "src/auth/session.py").
            task: Optional task description to score against. Defaults to current task.md.

        Returns a markdown string with score signals, include mode, token count, and symbols.
        """
        return _explain_file_impl(_repo_root(), path, task)

    @mcp.tool()
    def get_related_files(path: str, depth: int = 1) -> str:
        """Return import-graph neighbours of a file (files it imports + files that import it).

        Args:
            path: Repo-relative file path (e.g. "src/auth/session.py").
            depth: Graph traversal depth (1 = direct neighbours, 2 = two hops). Max 2.

        Returns a markdown list of related files with their relationship type.
        """
        return _get_related_files_impl(_repo_root(), path, depth)

    @mcp.tool()
    def get_delta_context(max_files: int = 12) -> str:
        """Return selected-file delta and top current files from the latest pack.

        Args:
            max_files: Number of selected files to include. Default 12.

        Returns a compact markdown delta suitable for hooks and agent refresh checks.
        """
        return _get_delta_context_impl(_repo_root(), max_files)

    @mcp.tool()
    def get_stats() -> str:
        """Return token/saving stats for the latest context pack.

        Returns a markdown summary: packed tokens, raw tokens, saving %, selected files, task, generated_at.
        """
        return _get_stats_impl(_repo_root())

    mcp.run()
