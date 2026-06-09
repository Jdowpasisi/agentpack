from __future__ import annotations

import json
import hashlib
import random
import shlex
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer
from rich.table import Table
from rich import box

from agentpack.commands._shared import console, _root
from agentpack.commands.pack import _resolve_task
from agentpack.application.pack_service import PackRequest, PackService
from agentpack.core import git
from agentpack.core.config import load_config
from agentpack.core.token_estimator import estimate_tokens

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]


@dataclass
class BenchmarkCase:
    task: str
    mode: str = "balanced"
    expected_files: list[str] = field(default_factory=list)
    task_type: str = "general"
    workspace: str | None = None
    budget: int = 0


@dataclass
class CaseResult:
    case: BenchmarkCase
    packed_tokens: int
    raw_tokens: int           # all files (incl. ignored)
    after_ignore_tokens: int  # packable files only — honest baseline
    saving_pct: float         # vs raw
    saving_pct_honest: float  # vs after_ignore
    selected_paths: list[str]
    selected_tokens: dict[str, int]   # path → token count for noise calc
    changed_covered: int
    changed_total: int
    total_s: float
    phase_times: dict[str, float]
    rank_at_k: int | None = None   # min rank to see all expected_files; None if no expected
    noise_pct: float | None = None  # tokens on non-expected / packed; None if no expected
    random_precision: float | None = None
    random_recall: float | None = None
    random_f1: float | None = None
    missed_expected: list[dict[str, Any]] = field(default_factory=list)
    selected_modes: dict[str, str] = field(default_factory=dict)


@dataclass
class FixtureCase:
    fixture: str
    root: Path
    case: BenchmarkCase


@dataclass
class PublicRepoCase:
    commit: str
    task: str
    expected_files: list[str]
    mode: str = "balanced"
    task_type: str = "general"
    workspace: str | None = None
    budget: int = 0


@dataclass
class PublicRepoSpec:
    name: str
    url: str
    ref: str = "main"
    cases: list[PublicRepoCase] = field(default_factory=list)


@dataclass
class E2ECase:
    name: str
    repo: Path
    task: str
    test_command: str
    setup_command: str = ""
    protected_paths: list[str] = field(default_factory=list)
    expected_edit_paths: list[str] = field(default_factory=list)


@dataclass
class E2EResult:
    schema_version: int
    case: str
    strategy: str
    trial: int
    passed: bool
    duration_s: float
    input_tokens: int
    agent_returncode: int
    test_returncode: int
    timed_out: bool
    changed_files: list[str]
    source_files_changed: list[str]
    test_files_changed: list[str]
    protected_files_changed: list[str]
    expected_files_touched: list[str]
    missing_expected_edits: list[str]
    unexpected_files_touched: list[str]
    agent_log_path: str
    test_log_path: str
    workdir: str


def _sample_fixture_cases(fixtures_root: Path) -> list[FixtureCase]:
    specs = [
        (
            "py_fastapi_app",
            "fix FastAPI auth token validation",
            ["src/app/auth.py", "tests/test_auth.py"],
            "backend-api",
        ),
        (
            "py_fastapi_app",
            "add user profile API endpoint",
            ["src/app/main.py", "src/app/users.py", "tests/test_users.py"],
            "backend-api",
        ),
        (
            "nextjs_app",
            "fix Next.js auth helper and API client",
            ["src/lib/auth.ts", "src/lib/api.ts"],
            "frontend-web",
        ),
        (
            "nextjs_app",
            "debug dashboard page data loading",
            ["src/app/page.tsx", "src/lib/api.ts"],
            "frontend-web",
        ),
        (
            "mixed_repo",
            "fix TypeScript API serialization utility",
            ["src/ts/api.ts", "src/ts/utils.ts"],
            "typescript",
        ),
        (
            "mixed_repo",
            "fix Python utility parsing edge case",
            ["src/py/utils.py"],
            "python",
        ),
        (
            "django_rest_app",
            "fix cursor pagination in user list endpoint",
            ["api/views/user_list.py", "api/pagination.py", "tests/test_pagination.py"],
            "backend-api",
        ),
        (
            "django_rest_app",
            "fix validation error in user serializer",
            ["api/serializers/user.py"],
            "backend-api",
        ),
        (
            "go_service",
            "fix kubernetes readiness probe failing on startup",
            ["handler/health.go", "k8s/deployment.yaml"],
            "infrastructure",
        ),
        (
            "go_service",
            "fix Docker image build for deployment",
            ["Dockerfile", "cmd/server/main.go"],
            "infrastructure",
        ),
        (
            "rails_app",
            "fix welcome email not being sent after registration",
            ["app/mailers/user_mailer.rb", "app/jobs/email_job.rb", "spec/mailers/user_mailer_spec.rb"],
            "backend-api",
        ),
    ]

    cases: list[FixtureCase] = []
    for fixture, task, expected_files, task_type in specs:
        fixture_root = fixtures_root / fixture
        if fixture_root.exists():
            cases.append(
                FixtureCase(
                    fixture=fixture,
                    root=fixture_root,
                    case=BenchmarkCase(
                        task=task,
                        mode="balanced",
                        expected_files=expected_files,
                        task_type=task_type,
                    ),
                )
            )
    return cases


def _load_public_repo_specs(path: Path) -> list[PublicRepoSpec]:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    specs: list[PublicRepoSpec] = []
    for raw_repo in data.get("repos", []):
        cases = [
            PublicRepoCase(
                commit=raw_case["commit"],
                task=raw_case["task"],
                expected_files=raw_case.get("expected_files", []),
                mode=raw_case.get("mode", "balanced"),
                task_type=raw_case.get("task_type", "general"),
                workspace=raw_case.get("workspace"),
                budget=raw_case.get("budget", 0),
            )
            for raw_case in raw_repo.get("cases", [])
        ]
        specs.append(PublicRepoSpec(
            name=raw_repo["name"],
            url=raw_repo["url"],
            ref=raw_repo.get("ref", "main"),
            cases=cases,
        ))
    return specs


def _load_cases(path: Path) -> list[BenchmarkCase]:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    cases: list[BenchmarkCase] = []
    for raw in data.get("cases", []):
        cases.append(BenchmarkCase(
            task=raw["task"],
            mode=raw.get("mode", "balanced"),
            expected_files=raw.get("expected_files", []),
            task_type=raw.get("task_type", "general"),
            workspace=raw.get("workspace"),
            budget=raw.get("budget", 0),
        ))
    return cases


def _scaffold_cases(root: Path) -> Path:
    out = root / ".agentpack" / "benchmark.toml"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        '# AgentPack benchmark cases\n'
        '# Each case runs a pack and measures token savings, speed, and\n'
        '# selection quality. Add expected_files for precision/recall scoring.\n\n'
        '# How to build a useful eval set:\n'
        '# 1. Add 5-20 real tasks from your repo history.\n'
        '# 2. Fill expected_files with files you actually edited for that task.\n'
        '# 3. Run: agentpack benchmark --compare\n'
        '# 4. Tune task text, .agentignore, and scoring weights until recall/token noise look sane.\n\n'
        '[[cases]]\n'
        'task = "fix auth token expiry"\n'
        'mode = "balanced"\n'
        'task_type = "backend-api"\n'
        '# workspace = "apps/api"\n'
        '# budget = 2000\n'
        '# expected_files = [\n'
        '#   "src/auth/token.py",\n'
        '#   "src/auth/session.py",\n'
        '# ]\n\n'
        '[[cases]]\n'
        'task = "add rate limiting to API endpoints"\n'
        'mode = "balanced"\n'
        'task_type = "backend-api"\n',
        encoding="utf-8",
    )
    return out


def _write_results_template(root: Path, date: str | None = None) -> Path:
    stamp = date or datetime.now(timezone.utc).date().isoformat()
    out = root / "benchmarks" / "results" / f"{stamp}.md"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "# AgentPack Benchmark Results\n\n"
        f"- date: {stamp}\n"
        "- agentpack version/commit: <version or git sha>\n"
        "- repo/task set: <repo names, anonymized domains, or fixture suite>\n"
        "- cases: <count>\n"
        "- command: `agentpack benchmark --compare --misses`\n\n"
        "| Metric | Value |\n"
        "|---|---:|\n"
        "| avg recall | <percent> |\n"
        "| avg precision | <percent> |\n"
        "| avg token precision | <percent> |\n"
        "| balanced p50 tokens | <tokens> |\n"
        "| balanced p95 tokens | <tokens> |\n"
        "| miss count | <count> |\n\n"
        "## Notes\n\n"
        "- Use historical tasks with `expected_files` set to files actually changed.\n"
        "- Do not mix synthetic fixture smoke results with real repo claims.\n"
        "- Include notable misses and the output from `agentpack benchmark --misses`.\n",
        encoding="utf-8",
    )
    return out


def _public_benchmark_markdown(
    results: list[CaseResult],
    *,
    title: str = "AgentPack Public Benchmark Table",
    suite: str = "historical tasks",
    version: str = "",
    command: str = "agentpack benchmark --misses --public-table",
) -> str:
    """Render benchmark results as publishable Markdown evidence."""
    scored = [result for result in results if result.case.expected_files]
    rows = scored or results
    generated = datetime.now(timezone.utc).date().isoformat()
    version_line = f"- agentpack version/commit: {version}\n" if version else ""
    lines = [
        f"# {title}",
        "",
        f"- date: {generated}",
        f"- suite: {suite}",
        f"- cases: {len(rows)}",
        f"- command: `{command}`",
        "",
    ]
    if version:
        lines.insert(4, version_line.rstrip())

    if scored:
        metrics = [_precision_recall(result) for result in scored]
        avg_p = sum(metric[0] for metric in metrics) / len(metrics)
        avg_r = sum(metric[1] for metric in metrics) / len(metrics)
        avg_f1 = sum(metric[2] for metric in metrics) / len(metrics)
        token_precisions = [
            1 - (result.noise_pct / 100)
            for result in scored
            if result.noise_pct is not None
        ]
        avg_token_precision = sum(token_precisions) / len(token_precisions) if token_precisions else 0.0
        pack_tokens = sorted(result.packed_tokens for result in scored)
        p50_tokens = pack_tokens[len(pack_tokens) // 2]
        p95_tokens = pack_tokens[min(len(pack_tokens) - 1, int((len(pack_tokens) - 1) * 0.95))]
        lines += [
            "| Metric | Value |",
            "|---|---:|",
            f"| avg precision | {avg_p:.1%} |",
            f"| avg recall | {avg_r:.1%} |",
            f"| avg F1 | {avg_f1:.1%} |",
            f"| avg token precision | {avg_token_precision:.1%} |",
            f"| pack p50 tokens | {p50_tokens:,} |",
            f"| pack p95 tokens | {p95_tokens:,} |",
            "",
        ]

    lines += [
        "| Repo / suite | Task | Type | Mode | Budget | Packed tokens | Recall | Token precision | Rank@K | Time | Misses |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in rows:
        repo, task = _split_public_task(result.case.task)
        _p, recall, _f1 = _precision_recall(result) if result.case.expected_files else (0.0, 0.0, 0.0)
        token_precision = 1 - (result.noise_pct / 100) if result.noise_pct is not None else None
        misses = len(result.missed_expected)
        lines.append(
            "| "
            + " | ".join([
                _md_cell(repo),
                _md_cell(task),
                _md_cell(result.case.task_type),
                result.case.mode,
                f"{result.case.budget:,}" if result.case.budget else "default",
                f"{result.packed_tokens:,}",
                f"{recall:.1%}" if result.case.expected_files else "-",
                f"{token_precision:.1%}" if token_precision is not None else "-",
                str(result.rank_at_k) if result.rank_at_k is not None else "-",
                f"{result.total_s:.2f}s",
                str(misses),
            ])
            + " |"
        )
    lines += [
        "",
        "## Notes",
        "",
        "- Use real historical tasks with `expected_files` set to files actually changed.",
        "- Treat small curated suites as smoke proof; expand case counts before broad external claims.",
        "- Keep synthetic fixture smoke results separate from public repo claims.",
        "- Investigate misses with `agentpack benchmark --misses` and `agentpack explain --omitted`.",
    ]
    return "\n".join(lines).replace("\n\n\n", "\n\n") + "\n"


def _write_public_benchmark_table(
    root: Path,
    results: list[CaseResult],
    *,
    suite: str,
    version: str = "",
    command: str = "agentpack benchmark --misses --public-table",
    date: str | None = None,
) -> Path:
    stamp = date or datetime.now(timezone.utc).date().isoformat()
    out = root / "benchmarks" / "results" / f"{stamp}-public.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        _public_benchmark_markdown(results, suite=suite, version=version, command=command),
        encoding="utf-8",
    )
    return out


def _split_public_task(task: str) -> tuple[str, str]:
    if ":" in task:
        prefix, rest = task.split(":", 1)
        if prefix and "/" not in prefix and len(prefix) <= 40:
            return prefix.strip(), rest.strip()
    return "current repo", task


def _md_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def _git_stdout(cwd: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout.strip()


def _run_git(cwd: Path | None, args: list[str]) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )


def _git_commit_exists(cwd: Path, commit: str) -> bool:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return result.returncode == 0


def _ensure_git_commit(cwd: Path, commit: str) -> None:
    if _git_commit_exists(cwd, commit):
        return
    _run_git(cwd, ["fetch", "--quiet", "--depth", "1", "origin", commit])
    if not _git_commit_exists(cwd, commit):
        raise RuntimeError(f"Unable to fetch public benchmark commit {commit}")


def _ensure_public_repo_clone(
    spec: PublicRepoSpec,
    cache_dir: Path,
    *,
    refresh: bool = False,
    depth: int = 120,
) -> Path:
    safe_name = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in spec.name)
    repo_dir = cache_dir / safe_name
    if refresh and repo_dir.exists():
        shutil.rmtree(repo_dir)
    if not repo_dir.exists():
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        _run_git(None, [
            "clone",
            "--quiet",
            "--filter=blob:none",
            "--depth",
            str(depth),
            spec.url,
            str(repo_dir),
        ])
    else:
        _run_git(repo_dir, ["fetch", "--quiet", "--depth", str(depth), "origin", spec.ref])
    _run_git(repo_dir, ["checkout", "--quiet", spec.ref])
    return repo_dir


def _run_public_repo_suite(
    root: Path,
    specs: list[PublicRepoSpec],
    *,
    cache_dir: Path | None = None,
    refresh: bool = False,
) -> list[CaseResult]:
    """Run benchmark cases against parent checkouts of real public commits."""
    cache = cache_dir or root / ".agentpack" / "public-repos"
    results: list[CaseResult] = []
    with tempfile.TemporaryDirectory(prefix="agentpack-public-benchmark-") as temp_dir:
        temp_root = Path(temp_dir)
        for spec in specs:
            source_repo = _ensure_public_repo_clone(spec, cache, refresh=refresh)
            for public_case in spec.cases:
                _ensure_git_commit(source_repo, public_case.commit)
                parent = _git_stdout(source_repo, ["rev-parse", f"{public_case.commit}^"])
                _ensure_git_commit(source_repo, parent)
                work_root = temp_root / f"{spec.name}-{public_case.commit[:8]}"
                shutil.copytree(
                    source_repo,
                    work_root,
                    ignore=shutil.ignore_patterns(".agentpack", ".pytest_cache", "__pycache__"),
                )
                _run_git(work_root, ["checkout", "--quiet", parent])
                result = _run_case(
                    work_root,
                    BenchmarkCase(
                        task=f"{spec.name}: {public_case.task}",
                        mode=public_case.mode,
                        expected_files=public_case.expected_files,
                        task_type=public_case.task_type,
                        workspace=public_case.workspace,
                        budget=public_case.budget,
                    ),
                )
                results.append(result)
    return results


def _default_public_repos_file(root: Path) -> Path:
    return root / "benchmarks" / "public-repos.toml"


def _load_history_cases(root: Path, n: int) -> list[BenchmarkCase]:
    """Sample last N unique tasks from metrics.jsonl."""
    metrics_path = root / ".agentpack" / "metrics.jsonl"
    if not metrics_path.exists():
        return []
    seen: list[str] = []
    seen_set: set[str] = set()
    for line in reversed(metrics_path.read_text().splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            task = rec.get("task", "").strip()
            mode = rec.get("mode", "balanced")
            if task and task not in seen_set:
                seen_set.add(task)
                seen.append((task, mode))
                if len(seen) >= n:
                    break
        except json.JSONDecodeError:
            pass
    return [BenchmarkCase(task=t, mode=m, task_type="history") for t, m in seen]


def _append_benchmark_cases(root: Path, cases: list[BenchmarkCase]) -> Path:
    out = root / ".agentpack" / "benchmark.toml"
    out.parent.mkdir(parents=True, exist_ok=True)
    prefix = out.read_text(encoding="utf-8").rstrip() + "\n\n" if out.exists() and out.read_text(encoding="utf-8").strip() else ""
    blocks: list[str] = []
    for case in cases:
        lines = [
            "[[cases]]",
            f"task = {json.dumps(case.task)}",
            f"mode = {json.dumps(case.mode)}",
            f"task_type = {json.dumps(case.task_type)}",
        ]
        if case.workspace:
            lines.append(f"workspace = {json.dumps(case.workspace)}")
        if case.budget:
            lines.append(f"budget = {case.budget}")
        lines.append("expected_files = [" + ", ".join(json.dumps(path) for path in case.expected_files) + "]")
        blocks.append("\n".join(lines))
    out.write_text(prefix + "\n\n".join(blocks) + "\n", encoding="utf-8")
    return out


def _random_baseline(
    packable_paths: list[str],
    packable_tokens: dict[str, int],
    expected_files: list[str],
    budget: int,
) -> tuple[list[str], float, float, float]:
    """Random file selection at same budget. Returns (selected, precision, recall, f1)."""
    shuffled = list(packable_paths)
    random.shuffle(shuffled)
    selected: list[str] = []
    used = 0
    for p in shuffled:
        tok = packable_tokens.get(p, 50)
        if used + tok <= budget:
            selected.append(p)
            used += tok

    expected = set(expected_files)
    sel_set = set(selected)
    if not expected or not sel_set:
        return selected, 0.0, 0.0, 0.0
    tp = len(sel_set & expected)
    p = tp / len(sel_set)
    r = tp / len(expected)
    f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
    return selected, p, r, f1


def _run_case(root: Path, case: BenchmarkCase) -> CaseResult:
    from agentpack.application.pack_service import PackPlanner, PackRequest, _sf_tokens
    from agentpack.core.config import load_config

    cfg = load_config(root)

    request = PackRequest(
        root=root,
        agent="generic",
        task=case.task,
        mode=case.mode,
        since=None,
        refresh=False,
        workspace=case.workspace,
        budget=case.budget,
    )

    t0 = time.perf_counter()
    plan = PackPlanner().plan(request)
    total_s = time.perf_counter() - t0

    packed_tokens = sum(_sf_tokens(sf) for sf in plan.selected)
    raw_tokens = sum(f.estimated_tokens for f in plan.scan_result.all_files)
    after_ignore_tokens = sum(f.estimated_tokens for f in plan.scan_result.packable)
    saving_pct = (1 - packed_tokens / raw_tokens) * 100 if raw_tokens > 0 else 0.0
    saving_pct_honest = (1 - packed_tokens / after_ignore_tokens) * 100 if after_ignore_tokens > 0 else 0.0

    selected_paths = [sf.path for sf in plan.selected]
    selected_set = set(selected_paths)
    selected_tokens = {sf.path: _sf_tokens(sf) for sf in plan.selected}
    selected_modes = {sf.path: _selected_mode(sf) for sf in plan.selected}

    changed_covered = len(plan.all_changed & selected_set)
    changed_total = len(plan.all_changed)

    # Rank@K: min rank in scored list to cover all expected files
    rank_at_k: int | None = None
    noise_pct: float | None = None
    rand_p = rand_r = rand_f1 = None

    if case.expected_files:
        expected_set = set(case.expected_files)
        scored_paths = [fi.path for fi, _score, _reasons in plan.scored]
        scored_map = {
            fi.path: {"rank": rank, "score": score, "reasons": reasons}
            for rank, (fi, score, reasons) in enumerate(plan.scored, 1)
        }
        all_file_map = {fi.path: fi for fi in plan.scan_result.all_files}
        receipt_map = {receipt.path: receipt.reason for receipt in plan.receipts}
        found: set[str] = set()
        for k, path in enumerate(scored_paths, 1):
            if path in expected_set:
                found.add(path)
            if found >= expected_set:
                rank_at_k = k
                break

        expected_tokens = sum(selected_tokens.get(p, 0) for p in selected_set & expected_set)
        noise_pct = (1 - expected_tokens / packed_tokens) * 100 if packed_tokens > 0 else 0.0

        packable_paths = [f.path for f in plan.scan_result.packable]
        packable_token_map = {f.path: f.estimated_tokens for f in plan.scan_result.packable}
        budget = case.budget or cfg.context.default_budget
        _, rand_p, rand_r, rand_f1 = _random_baseline(packable_paths, packable_token_map, case.expected_files, budget)

        missed_expected = []
        for expected_path in sorted(expected_set - selected_set):
            fi = all_file_map.get(expected_path)
            scored_info = scored_map.get(expected_path)
            status = _miss_status(
                fi=fi,
                expected_path=expected_path,
                receipt_map=receipt_map,
                scored_info=scored_info,
                changed_files_source=plan.changed_files_source,
            )
            missed_expected.append({
                "path": expected_path,
                "status": status,
                "rank": scored_info["rank"] if scored_info else None,
                "score": round(scored_info["score"], 1) if scored_info else None,
                "reasons": scored_info["reasons"][:4] if scored_info else [],
                "basis": plan.changed_files_source,
            })
    else:
        missed_expected = []

    return CaseResult(
        case=case,
        packed_tokens=packed_tokens,
        raw_tokens=raw_tokens,
        after_ignore_tokens=after_ignore_tokens,
        saving_pct=saving_pct,
        saving_pct_honest=saving_pct_honest,
        selected_paths=selected_paths,
        selected_tokens=selected_tokens,
        selected_modes=selected_modes,
        changed_covered=changed_covered,
        changed_total=changed_total,
        total_s=total_s,
        phase_times=plan.phase_times,
        rank_at_k=rank_at_k,
        noise_pct=noise_pct,
        random_precision=rand_p,
        random_recall=rand_r,
        random_f1=rand_f1,
        missed_expected=missed_expected,
    )


def _precision_recall(result: CaseResult) -> tuple[float, float, float]:
    expected = set(result.case.expected_files)
    if not expected:
        return 0.0, 0.0, 0.0
    selected = set(result.selected_paths)
    tp = len(selected & expected)
    p = tp / len(selected) if selected else 0.0
    r = tp / len(expected)
    f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
    return p, r, f1


def _miss_status(
    *,
    fi: Any,
    expected_path: str,
    receipt_map: dict[str, str],
    scored_info: dict[str, Any] | None,
    changed_files_source: str,
) -> str:
    suffix = ""
    if changed_files_source.startswith("no live changes"):
        suffix = "; no live changed-file signal"
    if fi is None:
        return "not found in scanned files"
    if fi.ignored or fi.binary:
        return "ignored or binary"
    if expected_path in receipt_map:
        return receipt_map[expected_path] + suffix
    if scored_info:
        if scored_info["score"] <= 0:
            return "scored too low" + suffix
        return "ranked but not selected" + suffix
    return "not scored" + suffix


def _persist_result(root: Path, result: CaseResult) -> None:
    out = root / ".agentpack" / "benchmark_results.jsonl"
    p, r, f1 = _precision_recall(result) if result.case.expected_files else (None, None, None)
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "task": result.case.task,
        "task_type": result.case.task_type,
        "workspace": result.case.workspace,
        "mode": result.case.mode,
        "budget": result.case.budget,
        "packed_tokens": result.packed_tokens,
        "raw_tokens": result.raw_tokens,
        "after_ignore_tokens": result.after_ignore_tokens,
        "saving_pct": round(result.saving_pct, 1),
        "saving_pct_honest": round(result.saving_pct_honest, 1),
        "files_selected": len(result.selected_paths),
        "mode_counts": _mode_counts(result.selected_modes),
        "changed_covered": result.changed_covered,
        "changed_total": result.changed_total,
        "total_s": round(result.total_s, 3),
        "phases": {k: round(v, 3) for k, v in result.phase_times.items()},
        "precision": round(p, 3) if p is not None else None,
        "recall": round(r, 3) if r is not None else None,
        "f1": round(f1, 3) if f1 is not None else None,
        "rank_at_k": result.rank_at_k,
        "noise_pct": round(result.noise_pct, 1) if result.noise_pct is not None else None,
        "token_precision": round(1 - (result.noise_pct / 100), 3) if result.noise_pct is not None else None,
        "random_f1": round(result.random_f1, 3) if result.random_f1 is not None else None,
        "misses": result.missed_expected,
    }
    try:
        with out.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:
        pass


def _print_case_detail(result: CaseResult, show_misses: bool = False) -> None:
    has_gt = bool(result.case.expected_files)
    p, r, f1 = _precision_recall(result) if has_gt else (0.0, 0.0, 0.0)

    console.print(
        f"\n[bold cyan]{result.case.task}[/]  "
        f"[dim]mode={result.case.mode} type={result.case.task_type}"
        f"{' workspace=' + result.case.workspace if result.case.workspace else ''}[/]"
    )

    tbl = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    tbl.add_column(style="dim")
    tbl.add_column(justify="right", style="bold")
    tbl.add_row("packed tokens", f"{result.packed_tokens:,}")
    tbl.add_row("raw tokens (all files)", f"{result.raw_tokens:,}")
    tbl.add_row("after ignore tokens", f"{result.after_ignore_tokens:,}")
    tbl.add_row("saving vs raw", f"[green]{result.saving_pct:.1f}%[/]")
    tbl.add_row("saving vs after-ignore", f"[cyan]{result.saving_pct_honest:.1f}%[/]")
    tbl.add_row("files selected", str(len(result.selected_paths)))
    tbl.add_row("mode mix", _format_mode_counts(_mode_counts(result.selected_modes)))
    if result.changed_total > 0:
        cov_pct = result.changed_covered / result.changed_total * 100
        tbl.add_row("changed files covered", f"{result.changed_covered}/{result.changed_total}  ({cov_pct:.0f}%)")
    tbl.add_row("total time", f"{result.total_s:.2f}s")
    console.print(tbl)

    if result.phase_times:
        phases = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
        phases.add_column("phase", style="dim")
        phases.add_column("time", justify="right")
        for phase, t in result.phase_times.items():
            phases.add_row(phase, f"{t:.3f}s")
        console.print(phases)

    if has_gt:
        console.print(
            f"  precision [bold]{p:.1%}[/]  "
            f"recall [bold]{r:.1%}[/]  "
            f"F1 [bold]{f1:.1%}[/]"
        )
        if result.rank_at_k is not None:
            console.print(f"  rank@K (all expected covered at rank) [bold]{result.rank_at_k}[/]")
        else:
            console.print("  rank@K  [dim]expected files not all found in scored list[/]")
        if result.noise_pct is not None:
            console.print(f"  noise (tokens on non-expected files) [bold]{result.noise_pct:.1f}%[/]")
        if result.random_f1 is not None:
            lift = f1 - result.random_f1
            color = "green" if lift >= 0 else "red"
            console.print(
                f"  random baseline F1 [dim]{result.random_f1:.1%}[/]  "
                f"ranker lift [{color}]{lift:+.1%}[/{color}]"
            )
        expected_set = set(result.case.expected_files)
        selected_set = set(result.selected_paths)
        hits = expected_set & selected_set
        misses = expected_set - selected_set
        if hits:
            console.print("  [green]hit:[/]  " + ", ".join(sorted(hits)))
        if misses:
            console.print("  [red]miss:[/] " + ", ".join(sorted(misses)))
        if show_misses and result.missed_expected:
            console.print("  [yellow]miss details:[/]")
            for miss in result.missed_expected:
                rank = miss["rank"] if miss["rank"] is not None else "-"
                score = miss["score"] if miss["score"] is not None else "-"
                reasons = ", ".join(miss["reasons"]) if miss["reasons"] else "no scoring reasons"
                console.print(
                    f"    {miss['path']}  status={miss['status']}  "
                    f"rank={rank}  score={score}  why={reasons}"
                )

    console.print("  [dim]top files:[/] " + ", ".join(result.selected_paths[:5]))


def _mode_counts(selected_modes: dict[str, str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for mode in selected_modes.values():
        counts[mode] = counts.get(mode, 0) + 1
    return counts


def _selected_mode(sf: Any) -> str:
    mode = getattr(sf, "include_mode", "summary")
    return mode if isinstance(mode, str) else "summary"


def _format_mode_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "-"
    order = ("full", "diff", "symbols", "skeleton", "summary")
    return ", ".join(f"{mode}:{counts[mode]}" for mode in order if counts.get(mode))


def _print_summary_table(results: list[CaseResult]) -> None:
    has_gt = any(r.case.expected_files for r in results)

    tbl = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
    tbl.add_column("task", max_width=40)
    tbl.add_column("mode", width=9)
    tbl.add_column("tokens", justify="right")
    tbl.add_column("vs raw", justify="right")
    tbl.add_column("vs ignore", justify="right")
    tbl.add_column("files", justify="right")
    tbl.add_column("time", justify="right")
    if has_gt:
        tbl.add_column("P", justify="right")
        tbl.add_column("R", justify="right")
        tbl.add_column("F1", justify="right")
        tbl.add_column("rand F1", justify="right")
        tbl.add_column("rank@K", justify="right")
        tbl.add_column("noise%", justify="right")

    for r in results:
        p, rec, f1 = _precision_recall(r) if r.case.expected_files else (0.0, 0.0, 0.0)
        row = [
            r.case.task[:38],
            r.case.mode,
            f"{r.packed_tokens:,}",
            f"{r.saving_pct:.1f}%",
            f"{r.saving_pct_honest:.1f}%",
            str(len(r.selected_paths)),
            f"{r.total_s:.2f}s",
        ]
        if has_gt:
            row += [
                f"{p:.1%}" if r.case.expected_files else "—",
                f"{rec:.1%}" if r.case.expected_files else "—",
                f"{f1:.1%}" if r.case.expected_files else "—",
                f"{r.random_f1:.1%}" if r.random_f1 is not None else "—",
                str(r.rank_at_k) if r.rank_at_k is not None else "—",
                f"{r.noise_pct:.0f}%" if r.noise_pct is not None else "—",
            ]
        tbl.add_row(*row)

    console.print()
    console.print(tbl)


def _quality_status(
    results: list[CaseResult],
    *,
    min_recall: float = 0.60,
    min_token_precision: float = 0.50,
) -> tuple[bool, dict[str, float]]:
    scored = [result for result in results if result.case.expected_files]
    if not scored:
        return False, {"cases": 0.0}
    recalls = [_precision_recall(result)[1] for result in scored]
    token_precisions = [
        1 - (result.noise_pct / 100)
        for result in scored
        if result.noise_pct is not None
    ]
    avg_recall = sum(recalls) / len(recalls)
    avg_token_precision = sum(token_precisions) / len(token_precisions) if token_precisions else 0.0
    return (
        avg_recall >= min_recall and avg_token_precision >= min_token_precision,
        {
            "cases": float(len(scored)),
            "avg_recall": avg_recall,
            "avg_token_precision": avg_token_precision,
        },
    )


def _print_quality_status(
    results: list[CaseResult],
    *,
    min_recall: float = 0.60,
    min_token_precision: float = 0.50,
) -> bool:
    passed, metrics = _quality_status(
        results,
        min_recall=min_recall,
        min_token_precision=min_token_precision,
    )
    if not metrics.get("cases"):
        console.print("[yellow]Quality target not proven: no benchmark cases have expected_files.[/]")
        return False
    color = "green" if passed else "yellow"
    console.print(
        f"[{color}]Quality target {'passed' if passed else 'not met'}:[/{color}] "
        f"{int(metrics['cases'])} case(s), "
        f"avg recall {metrics['avg_recall']:.1%} / {min_recall:.0%}, "
        f"avg token precision {metrics['avg_token_precision']:.1%} / {min_token_precision:.0%}"
    )
    return passed


def _print_task_type_summary(results: list[CaseResult]) -> None:
    grouped: dict[str, list[CaseResult]] = {}
    for result in results:
        if result.case.expected_files:
            grouped.setdefault(result.case.task_type, []).append(result)
    if not grouped:
        return

    tbl = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
    tbl.add_column("task type", max_width=28)
    tbl.add_column("cases", justify="right")
    tbl.add_column("avg P", justify="right")
    tbl.add_column("avg R", justify="right")
    tbl.add_column("avg F1", justify="right")
    tbl.add_column("avg noise", justify="right")

    for task_type, rows in sorted(grouped.items()):
        metrics = [_precision_recall(row) for row in rows]
        avg_p = sum(item[0] for item in metrics) / len(metrics)
        avg_r = sum(item[1] for item in metrics) / len(metrics)
        avg_f1 = sum(item[2] for item in metrics) / len(metrics)
        noise_values = [row.noise_pct for row in rows if row.noise_pct is not None]
        avg_noise = sum(noise_values) / len(noise_values) if noise_values else None
        tbl.add_row(
            task_type,
            str(len(rows)),
            f"{avg_p:.1%}",
            f"{avg_r:.1%}",
            f"{avg_f1:.1%}",
            f"{avg_noise:.0f}%" if avg_noise is not None else "-",
        )

    console.print("\n[bold]By Task Type[/]")
    console.print(tbl)


def _print_miss_details(results: list[CaseResult]) -> None:
    rows = [miss | {"task": result.case.task[:30]} for result in results for miss in result.missed_expected]
    if not rows:
        return

    tbl = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
    tbl.add_column("task", max_width=30)
    tbl.add_column("missed file", max_width=42)
    tbl.add_column("status", max_width=24)
    tbl.add_column("rank", justify="right")
    tbl.add_column("score", justify="right")
    tbl.add_column("why", max_width=40)

    for row in rows:
        tbl.add_row(
            row["task"],
            row["path"],
            row["status"],
            str(row["rank"]) if row["rank"] is not None else "-",
            str(row["score"]) if row["score"] is not None else "-",
            ", ".join(row["reasons"]) if row["reasons"] else "-",
        )

    console.print("\n[bold]Miss Details[/]")
    console.print(tbl)


def _print_fixture_summary_table(results: list[CaseResult]) -> None:
    tbl = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
    tbl.add_column("fixture task", max_width=42)
    tbl.add_column("mode", width=9)
    tbl.add_column("tokens", justify="right")
    tbl.add_column("R", justify="right")
    tbl.add_column("F1", justify="right")
    tbl.add_column("rank@K", justify="right")
    tbl.add_column("noise", justify="right")

    for result in results:
        _p, recall, f1 = _precision_recall(result)
        tbl.add_row(
            result.case.task[:40],
            result.case.mode,
            f"{result.packed_tokens:,}",
            f"{recall:.0%}",
            f"{f1:.0%}",
            str(result.rank_at_k) if result.rank_at_k is not None else "-",
            f"{result.noise_pct:.0f}%" if result.noise_pct is not None else "-",
        )

    console.print()
    console.print(tbl)


def _print_compare_table(task: str, results: list[CaseResult]) -> None:
    console.print(f"\n[bold]Mode comparison:[/] [cyan]{task}[/]\n")

    tbl = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    tbl.add_column("mode", width=10)
    tbl.add_column("tokens", justify="right")
    tbl.add_column("vs raw", justify="right")
    tbl.add_column("vs ignore", justify="right")
    tbl.add_column("files", justify="right")
    tbl.add_column("time", justify="right")

    for r in results:
        tbl.add_row(
            r.case.mode,
            f"{r.packed_tokens:,}",
            f"{r.saving_pct:.1f}%",
            f"{r.saving_pct_honest:.1f}%",
            str(len(r.selected_paths)),
            f"{r.total_s:.2f}s",
        )
    console.print(tbl)


def _copy_fixture(source: Path, destination: Path) -> None:
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns("__pycache__", ".agentpack", ".pytest_cache"),
    )


benchmark_app = typer.Typer(help="Benchmark file selection quality and token efficiency.")


def register(app: typer.Typer) -> None:
    app.add_typer(benchmark_app, name="benchmark")


@benchmark_app.command("capture")
def capture_benchmark_case(
    since: str = typer.Option(..., "--since", help="Git ref to diff against."),
    task: str = typer.Option(..., "--task", help="Task text for the captured benchmark case."),
    mode: str = typer.Option("balanced", "--mode", help="Benchmark mode."),
    workspace: str = typer.Option("", "--workspace", help="Optional workspace."),
    allow_empty: bool = typer.Option(False, "--allow-empty", help="Allow appending a case with no expected files."),
) -> None:
    """Append a benchmark case from git diff expected files."""
    root = _root()
    expected = sorted(git.changed_files_since(root, since))
    if not expected and not allow_empty:
        console.print(f"[yellow]No files changed since {since}. Use --allow-empty to append anyway.[/]")
        raise typer.Exit(1)
    case = BenchmarkCase(task=task.strip(), mode=mode, expected_files=expected, workspace=workspace or None)
    out = _append_benchmark_cases(root, [case])
    console.print(f"[green]✓[/] Appended benchmark case to [bold]{out}[/]")
    console.print(f"  expected_files: {len(expected)}")


@benchmark_app.command("scan-modes")
def benchmark_scan_modes(
    files: int = typer.Option(2000, "--files", help="Synthetic source file count."),
    target_every: int = typer.Option(200, "--target-every", help="Put the target symbol in every Nth file."),
    llm_command: str = typer.Option("", "--llm-command", help="Optional command that accepts a prompt file path as last arg."),
) -> None:
    """Compare grep baseline and AgentPack full/incremental scan on a synthetic repo."""
    with tempfile.TemporaryDirectory(prefix="agentpack-bench-") as tmp:
        root = Path(tmp)
        _build_synthetic_repo(root, files=files, target_every=target_every)
        _init_synthetic_git(root)

        task = "fix target_symbol caller behavior"
        grep_start = time.perf_counter()
        grep = subprocess.run(
            ["rg", "-n", "target_symbol", "src"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        grep_s = time.perf_counter() - grep_start

        full_start = time.perf_counter()
        full = PackService().run(PackRequest(
            root=root,
            agent="generic",
            task=task,
            mode="balanced",
            budget=40000,
            since=None,
            refresh=False,
            task_source="benchmark",
        ))
        full_s = time.perf_counter() - full_start

        changed = root / "src" / "file_0000.py"
        changed.write_text(changed.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
        incremental_start = time.perf_counter()
        incremental = PackService().run(PackRequest(
            root=root,
            agent="generic",
            task=task,
            mode="balanced",
            budget=40000,
            since=None,
            refresh=False,
            task_source="benchmark",
        ))
        incremental_s = time.perf_counter() - incremental_start

        llm_s: float | None = None
        if llm_command:
            prompt_path = root / "prompt.txt"
            prompt_path.write_text(
                "Find files relevant to fixing target_symbol caller behavior. Return file paths only.\n",
                encoding="utf-8",
            )
            llm_start = time.perf_counter()
            subprocess.run(
                [*llm_command.split(), str(prompt_path)],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=120,
            )
            llm_s = time.perf_counter() - llm_start

        table = Table(box=box.SIMPLE, show_header=True)
        table.add_column("method")
        table.add_column("seconds", justify="right")
        table.add_column("details")
        table.add_row("grep rg", f"{grep_s:.3f}", f"{len(grep.stdout.splitlines())} matching lines")
        table.add_row(
            "agentpack full",
            f"{full_s:.3f}",
            (
                f"{full.scan_result.rehashed_count} hashed, {full.packed_tokens:,}/{full.raw_tokens:,} tokens "
                f"({full.saving_pct:.1f}% less)"
            ),
        )
        table.add_row(
            f"agentpack {incremental.scan_result.scan_mode}",
            f"{incremental_s:.3f}",
            (
                f"{incremental.scan_result.rehashed_count} rehashed, {incremental.scan_result.reused_count} reused"
                + (f"; {incremental.scan_result.full_scan_reason}" if incremental.scan_result.full_scan_reason else "")
            ),
        )
        if llm_s is not None:
            table.add_row("external llm/agent", f"{llm_s:.3f}", llm_command)
        console.print(table)


@benchmark_app.command("e2e")
def benchmark_e2e(
    cases: str = typer.Option(..., "--cases", help="TOML file with [[cases]] entries."),
    agent_command: str = typer.Option(..., "--agent-command", help="Agent command. Use {prompt} and {repo} placeholders, or prompt path is appended."),
    strategies: str = typer.Option("no-context,grep,agentpack-lite,hybrid,agentpack", "--strategies", help="Comma-separated: no-context,grep,agentpack-lite,hybrid,agentpack."),
    trials: int = typer.Option(1, "--trials", help="Runs per case per strategy."),
    timeout: int = typer.Option(300, "--timeout", help="Agent command timeout seconds."),
    output: str = typer.Option("", "--output", help="JSONL output path. Default: .agentpack/e2e_results.jsonl"),
    keep_workdirs: bool = typer.Option(False, "--keep-workdirs", help="Keep temp workdirs for failed-result inspection."),
) -> None:
    """Run real coding-agent E2E evals and judge by test command pass/fail."""
    root = _root()
    parsed_cases = _load_e2e_cases(root, Path(cases))
    wanted_strategies = [item.strip() for item in strategies.split(",") if item.strip()]
    unknown = set(wanted_strategies) - {"no-context", "grep", "agentpack-lite", "hybrid", "agentpack"}
    if unknown:
        raise typer.BadParameter(f"Unknown strategy: {', '.join(sorted(unknown))}")
    if trials < 1:
        raise typer.BadParameter("--trials must be >= 1")

    out_path = Path(output) if output else root / ".agentpack" / "e2e_results.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    results: list[E2EResult] = []

    for case in parsed_cases:
        for strategy in wanted_strategies:
            for trial in range(1, trials + 1):
                result = _run_e2e_case(
                    case,
                    strategy=strategy,
                    trial=trial,
                    agent_command=agent_command,
                    timeout=timeout,
                    keep_workdir=keep_workdirs,
                )
                results.append(result)
                with out_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(result.__dict__) + "\n")

    _print_e2e_summary(results, out_path)


def _load_e2e_cases(root: Path, path: Path) -> list[E2ECase]:
    case_path = path if path.is_absolute() else root / path
    data = tomllib.loads(case_path.read_text(encoding="utf-8"))
    cases: list[E2ECase] = []
    for raw in data.get("cases") or []:
        repo_value = raw.get("repo")
        if not repo_value:
            raise ValueError(f"Case {raw.get('name') or '<unnamed>'} missing repo")
        repo = Path(str(repo_value))
        if not repo.is_absolute():
            repo = (case_path.parent / repo).resolve()
        cases.append(
            E2ECase(
                name=str(raw.get("name") or repo.name),
                repo=repo,
                task=str(raw.get("task") or ""),
                test_command=str(raw.get("test_command") or ""),
                setup_command=str(raw.get("setup_command") or ""),
                protected_paths=[str(path) for path in raw.get("protected_paths", [])],
                expected_edit_paths=[str(path) for path in raw.get("expected_edit_paths", [])],
            )
        )
    if not cases:
        raise ValueError(f"No [[cases]] found in {case_path}")
    return cases


def _run_e2e_case(
    case: E2ECase,
    *,
    strategy: str,
    trial: int,
    agent_command: str,
    timeout: int,
    keep_workdir: bool,
) -> E2EResult:
    start = time.perf_counter()
    work_root = Path(tempfile.mkdtemp(prefix=f"agentpack-e2e-{case.name}-{strategy}-"))
    repo = work_root / "repo"
    shutil.copytree(case.repo, repo, ignore=shutil.ignore_patterns(".git", ".agentpack", "__pycache__", ".pytest_cache"))
    _init_e2e_git(repo)
    if case.setup_command:
        subprocess.run(case.setup_command, cwd=repo, shell=True, capture_output=True, text=True, timeout=timeout)
    protected_hashes = _hash_protected_paths(repo, case.protected_paths)

    prompt = _e2e_prompt(case, strategy, repo)
    prompt_path = repo / ".agentpack_e2e_prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    agent_args = _agent_args(agent_command, prompt_path, repo)
    timed_out = False
    try:
        agent = subprocess.run(agent_args, cwd=repo, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        agent = _timeout_result(agent_args, exc)
    agent_log_path = work_root / "agent.log"
    test_log_path = work_root / "test.log"
    _write_e2e_process_log(agent_log_path, agent)
    try:
        test = subprocess.run(case.test_command, cwd=repo, shell=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        test = _timeout_result(case.test_command, exc)
    _write_e2e_process_log(test_log_path, test)
    changed = sorted(git.dirty_files(repo)) if git.is_git_repo(repo) else []
    public_changed = _public_changed_files(changed)
    source_changed = [path for path in public_changed if not _is_test_path(path)]
    test_changed = [path for path in public_changed if _is_test_path(path)]
    protected_changed = _changed_protected_paths(repo, protected_hashes)
    expected_touched = _expected_files_touched(public_changed, case.expected_edit_paths)
    missing_expected = sorted(set(case.expected_edit_paths) - set(expected_touched))
    unexpected_touched = _unexpected_files_touched(public_changed, case.expected_edit_paths)
    duration = time.perf_counter() - start
    passed = not timed_out and agent.returncode == 0 and test.returncode == 0 and not protected_changed

    if not keep_workdir and passed:
        shutil.rmtree(work_root, ignore_errors=True)

    return E2EResult(
        schema_version=2,
        case=case.name,
        strategy=strategy,
        trial=trial,
        passed=passed,
        duration_s=round(duration, 3),
        input_tokens=estimate_tokens(prompt),
        agent_returncode=agent.returncode,
        test_returncode=test.returncode,
        timed_out=timed_out,
        changed_files=changed,
        source_files_changed=source_changed,
        test_files_changed=test_changed,
        protected_files_changed=protected_changed,
        expected_files_touched=expected_touched,
        missing_expected_edits=missing_expected,
        unexpected_files_touched=unexpected_touched,
        agent_log_path=str(agent_log_path),
        test_log_path=str(test_log_path),
        workdir=str(work_root),
    )


def _public_changed_files(changed: list[str]) -> list[str]:
    internal = {".agentpack_e2e_prompt.txt"}
    return sorted(path for path in changed if path not in internal and not _is_generated_e2e_path(path))


def _is_generated_e2e_path(path: str) -> bool:
    return (
        path == ".agentpack"
        or path.startswith(".agentpack/")
        or path == ".agentpack/"
        or "__pycache__/" in path
        or path.endswith("__pycache__/")
        or path.endswith(".pyc")
    )


def _is_test_path(path: str) -> bool:
    name = Path(path).name
    return (
        path.startswith("tests/")
        or "/tests/" in path
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith(".test.ts")
        or name.endswith(".test.tsx")
        or name.endswith(".spec.ts")
        or name.endswith(".spec.tsx")
    )


def _expected_files_touched(changed: list[str], expected_edit_paths: list[str]) -> list[str]:
    expected = set(expected_edit_paths)
    return sorted(path for path in changed if path in expected)


def _unexpected_files_touched(changed: list[str], expected_edit_paths: list[str]) -> list[str]:
    if not expected_edit_paths:
        return []
    expected = set(expected_edit_paths)
    return sorted(path for path in changed if path not in expected)


def _hash_protected_paths(repo: Path, paths: list[str]) -> dict[str, str | None]:
    return {path: _file_sha256(repo / path) for path in paths}


def _changed_protected_paths(repo: Path, before: dict[str, str | None]) -> list[str]:
    return [
        path
        for path, expected in before.items()
        if _file_sha256(repo / path) != expected
    ]


def _file_sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_e2e_process_log(path: Path, result: subprocess.CompletedProcess[str]) -> None:
    path.write_text(
        "\n".join([
            f"returncode={result.returncode}",
            "",
            "STDOUT:",
            result.stdout,
            "",
            "STDERR:",
            result.stderr,
        ]),
        encoding="utf-8",
    )


def _timeout_result(
    args: str | list[str],
    exc: subprocess.TimeoutExpired,
) -> subprocess.CompletedProcess[str]:
    stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode(errors="replace")
    stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode(errors="replace")
    return subprocess.CompletedProcess(
        args=args,
        returncode=124,
        stdout=stdout,
        stderr=stderr + f"\nTimed out after {exc.timeout} seconds.",
    )


def _e2e_prompt(case: E2ECase, strategy: str, repo: Path) -> str:
    base = (
        f"Task: {case.task}\n\n"
        "Edit the repository to complete the task. Keep changes minimal. "
        f"After editing, the validation command should pass: `{case.test_command}`.\n"
    )
    if strategy == "no-context":
        return base
    if strategy == "grep":
        return base + "\nRelevant grep output:\n" + _grep_context(case.task, repo)
    if strategy == "agentpack-lite":
        return base + "\nAgentPack lite context:\n" + _agentpack_lite_context(case, repo)
    if strategy == "hybrid":
        return (
            base
            + "\nRelevant grep output:\n"
            + _grep_context(case.task, repo)
            + "\n\nAgentPack lite context:\n"
            + _agentpack_lite_context(case, repo)
        )
    if strategy == "agentpack":
        result = PackService().run(PackRequest(
            root=repo,
            agent="generic",
            task=case.task,
            mode="balanced",
            budget=40000,
            since=None,
            refresh=False,
            task_source="e2e",
        ))
        context = result.out_path.read_text(encoding="utf-8") if result.out_path.exists() else ""
        return base + "\nAgentPack context:\n" + context
    raise ValueError(f"unknown strategy: {strategy}")


def _agentpack_lite_context(case: E2ECase, repo: Path) -> str:
    lite = load_config(repo).context_lite
    result = PackService().run(PackRequest(
        root=repo,
        agent="generic",
        task=case.task,
        mode="minimal",
        budget=lite.budget,
        since=None,
        refresh=False,
        task_source="e2e-lite",
    ))
    pack = result.pack
    lines = [
        "Purpose: cheap repo situational awareness. Inspect files before editing; omitted paths are warnings, not evidence.",
        "",
        "## Selected File Map",
        "| File | Mode | Score | Why |",
        "|---|---|---:|---|",
    ]
    for selected in pack.selected_files[:lite.max_selected_files]:
        why = ", ".join(selected.reasons[:3]) or "-"
        lines.append(f"| `{selected.path}` | {selected.include_mode} | {selected.score:.0f} | {why} |")

    if pack.omitted_relevant_files:
        lines.extend([
            "",
            "## High-Risk Omitted Files",
            "| File | Risk | Score | Why |",
            "|---|---|---:|---|",
        ])
        for omitted in pack.omitted_relevant_files[:lite.max_omitted_files]:
            why = ", ".join(omitted.reasons[:3]) or omitted.omission_reason
            lines.append(f"| `{omitted.path}` | {omitted.risk.upper()} | {omitted.score:.0f} | {why} |")

    if pack.changed_files:
        lines.extend(["", "## Changed Files"])
        lines.extend(f"- `{path}`" for path in pack.changed_files[:15])

    stubs = _lite_file_stubs(pack.selected_files[:lite.max_stubs], summary_chars=lite.summary_chars)
    if stubs:
        lines.extend(["", "## File Stubs", *stubs])

    return "\n".join(lines)


def _lite_file_stubs(selected_files: list[Any], *, summary_chars: int = 500) -> list[str]:
    lines: list[str] = []
    for selected in selected_files:
        parts = [f"### `{selected.path}`"]
        if selected.summary:
            parts.append(_truncate_line(selected.summary, summary_chars))
        signatures = [
            symbol.signature or f"{symbol.kind} {symbol.name}"
            for symbol in selected.symbols[:8]
        ]
        if signatures:
            parts.append("Symbols: " + "; ".join(signatures))
        if len(parts) > 1:
            lines.extend(parts)
    return lines


def _truncate_line(text: str, limit: int) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def _grep_context(task: str, repo: Path, *, max_lines: int = 120) -> str:
    terms = [term for term in task.replace("_", " ").replace("-", " ").split() if len(term) >= 4]
    if not terms:
        return "(no grep terms)"
    outputs: list[str] = []
    for term in terms[:8]:
        try:
            result = subprocess.run(
                ["rg", "-n", "--glob", "!.git", "--glob", "!.agentpack", term],
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.stdout:
            outputs.extend(result.stdout.splitlines())
        if len(outputs) >= max_lines:
            break
    return "\n".join(outputs[:max_lines]) or "(no grep matches)"


def _agent_args(command: str, prompt_path: Path, repo: Path) -> list[str]:
    rendered = command.replace("{prompt}", str(prompt_path)).replace("{repo}", str(repo))
    args = shlex.split(rendered)
    if "{prompt}" not in command:
        args.append(str(prompt_path))
    return args


def _init_e2e_git(repo: Path) -> None:
    subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "agentpack@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "AgentPack E2E"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "initial"], cwd=repo, check=True)


def _print_e2e_summary(results: list[E2EResult], out_path: Path) -> None:
    table = Table(box=box.SIMPLE, show_header=True)
    table.add_column("strategy")
    table.add_column("runs", justify="right")
    table.add_column("pass rate", justify="right")
    table.add_column("timeouts", justify="right")
    table.add_column("expected touch", justify="right")
    table.add_column("avg tokens", justify="right")
    table.add_column("avg seconds", justify="right")
    table.add_column("pass/min", justify="right")
    for strategy in sorted({result.strategy for result in results}):
        subset = [result for result in results if result.strategy == strategy]
        pass_rate = sum(1 for result in subset if result.passed) / len(subset)
        timeout_rate = sum(1 for result in subset if result.timed_out) / len(subset)
        expected_cases = [result for result in subset if result.expected_files_touched or result.missing_expected_edits]
        expected_touch_rate = (
            sum(1 for result in expected_cases if result.expected_files_touched) / len(expected_cases)
            if expected_cases
            else None
        )
        avg_tokens = sum(result.input_tokens for result in subset) / len(subset)
        avg_seconds = sum(result.duration_s for result in subset) / len(subset)
        total_seconds = sum(result.duration_s for result in subset)
        pass_per_minute = (sum(1 for result in subset if result.passed) / total_seconds * 60) if total_seconds else 0.0
        table.add_row(
            strategy,
            str(len(subset)),
            f"{pass_rate:.0%}",
            f"{timeout_rate:.0%}",
            f"{expected_touch_rate:.0%}" if expected_touch_rate is not None else "-",
            f"{avg_tokens:,.0f}",
            f"{avg_seconds:.1f}",
            f"{pass_per_minute:.2f}",
        )
    console.print(table)
    console.print(f"[dim]JSONL: {out_path}[/]")


def _build_synthetic_repo(root: Path, *, files: int, target_every: int) -> None:
    src = root / "src"
    src.mkdir(parents=True)
    for index in range(files):
        target = "\n    return target_symbol(value)\n" if index % max(1, target_every) == 0 else "\n    return value\n"
        (src / f"file_{index:04d}.py").write_text(
            f"def helper_{index}(value):{target}\n",
            encoding="utf-8",
        )
    (root / ".agentpack").mkdir()
    (root / ".gitignore").write_text(
        "\n".join([
            ".agentpack/cache/",
            ".agentpack/snapshots/",
            ".agentpack/context*.md",
            ".agentpack/metrics.jsonl",
            ".agentpack/pack_metadata.json",
            ".agentpack/term_stats.json",
            "",
        ]),
        encoding="utf-8",
    )
    (root / ".agentpack" / "config.toml").write_text(
        "[context]\ndefault_budget = 40000\nincremental_scan = true\ninclude_receipts = true\n",
        encoding="utf-8",
    )
    (root / ".agentpack" / "task.md").write_text("fix target_symbol caller behavior\n", encoding="utf-8")


def _init_synthetic_git(root: Path) -> None:
    subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "agentpack@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "AgentPack Benchmark"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "initial"], cwd=root, check=True)


@benchmark_app.callback(invoke_without_command=True)
def benchmark(
    ctx: typer.Context,
    task: str = typer.Option("", "--task", help="Single task to benchmark (skips cases file)."),
    mode: str = typer.Option("balanced", "--mode", help="Mode for single-task run (minimal|balanced|deep)."),
    workspace: str = typer.Option("", "--workspace", help="Restrict benchmark packs to a workspace, e.g. apps/web."),
    cases: str = typer.Option("", "--cases", help="Path to TOML cases file (default: .agentpack/benchmark.toml)."),
    compare: bool = typer.Option(False, "--compare", is_flag=True, help="Compare minimal/balanced/deep for each task."),
    init: bool = typer.Option(False, "--init", is_flag=True, help="Scaffold a benchmark.toml and exit."),
    results_template: bool = typer.Option(False, "--results-template", is_flag=True, help="Create benchmarks/results/YYYY-MM-DD.md for publishing benchmark evidence."),
    from_history: int = typer.Option(0, "--from-history", help="Sample last N unique tasks from metrics.jsonl history."),
    write_cases: bool = typer.Option(False, "--write-cases", help="Append --from-history cases to .agentpack/benchmark.toml."),
    sample_fixtures: bool = typer.Option(False, "--sample-fixtures", is_flag=True, help="Run bundled FastAPI/Next.js/mixed-repo fixture evals from a source checkout."),
    release_gate: bool = typer.Option(False, "--release-gate", is_flag=True, help="Run the public real-repo release gate."),
    public_repos: bool = typer.Option(False, "--public-repos", is_flag=True, help="Run real public-repo commit cases from benchmarks/public-repos.toml."),
    public_repos_file: str = typer.Option("", "--public-repos-file", help="Path to public repo benchmark manifest."),
    public_repos_cache: str = typer.Option("", "--public-repos-cache", help="Directory for cached public repo clones."),
    refresh_public_repos: bool = typer.Option(False, "--refresh-public-repos", is_flag=True, help="Delete and reclone public repo benchmark cache before running."),
    public_table: bool = typer.Option(False, "--public-table", is_flag=True, help="Write a publishable Markdown benchmark table under benchmarks/results/."),
    no_public_table: bool = typer.Option(False, "--no-public-table", help="Do not write a benchmark results markdown table."),
    misses: bool = typer.Option(False, "--misses", is_flag=True, help="Show diagnostics for expected files that were not selected."),
    prove_targets: bool = typer.Option(False, "--prove-targets", is_flag=True, help="Exit non-zero unless recall/token precision targets pass."),
    min_recall: float = typer.Option(0.60, "--min-recall", help="Recall target for --prove-targets."),
    min_token_precision: float = typer.Option(0.50, "--min-token-precision", help="Token precision target for --prove-targets."),
) -> None:
    """Benchmark file selection quality and token efficiency across tasks."""
    if ctx.invoked_subcommand is not None:
        return
    root = _root()
    if release_gate:
        public_repos = True
        prove_targets = True
        misses = True
        public_table = not no_public_table
        console.print("[bold]Release gate:[/] public real-repo benchmark with target proof.")

    if init:
        out = _scaffold_cases(root)
        console.print(f"[green]✓[/] Created [bold]{out}[/]")
        console.print("  Edit the file to add your tasks and expected files, then run [bold]agentpack benchmark[/].")
        return

    if results_template:
        out = _write_results_template(root)
        console.print(f"[green]✓[/] Created [bold]{out}[/]")
        console.print("  Fill it with `agentpack benchmark --compare --misses` results from real historical tasks.")
        return

    if sample_fixtures:
        fixtures_root = root / "tests" / "fixtures"
        fixture_cases = _sample_fixture_cases(fixtures_root)
        if not fixture_cases:
            console.print(f"[yellow]No bundled fixture repos found at {fixtures_root}[/]")
            console.print("  This demo is available from an AgentPack source checkout. For your own repo, run [bold]agentpack benchmark --init[/].")
            raise typer.Exit(1)

        if compare:
            expanded_fixtures: list[FixtureCase] = []
            for fixture_case in fixture_cases:
                for fixture_mode in ("minimal", "balanced", "deep"):
                    expanded_fixtures.append(
                        FixtureCase(
                            fixture=fixture_case.fixture,
                            root=fixture_case.root,
                            case=BenchmarkCase(
                                task=fixture_case.case.task,
                                mode=fixture_mode,
                                expected_files=fixture_case.case.expected_files,
                                task_type=fixture_case.case.task_type,
                                workspace=fixture_case.case.workspace,
                                budget=fixture_case.case.budget,
                            ),
                        )
                    )
            fixture_cases = expanded_fixtures

        console.print(f"\n[bold]Running {len(fixture_cases)} sample fixture benchmark case(s)...[/]\n")

        results: list[CaseResult] = []
        with tempfile.TemporaryDirectory(prefix="agentpack-benchmark-") as temp_dir:
            temp_root = Path(temp_dir)
            for i, fixture_case in enumerate(fixture_cases, 1):
                case_root = temp_root / f"{i:02d}-{fixture_case.fixture}"
                _copy_fixture(fixture_case.root, case_root)
                label = f"[{i}/{len(fixture_cases)}] {fixture_case.fixture}: {fixture_case.case.task[:42]}  mode={fixture_case.case.mode}"
                with console.status(f"[dim]{label}[/]"):
                    try:
                        result = _run_case(case_root, fixture_case.case)
                        result.case.task = f"{fixture_case.fixture}: {result.case.task}"
                        results.append(result)
                    except Exception as e:
                        console.print(f"[red]Error on fixture case '{fixture_case.case.task}': {e}[/]")

        if not results:
            raise typer.Exit(1)

        console.print("[dim]Sample fixtures are regression smoke evals for this source checkout, not the public release gate.[/]")
        fixture_names = ", ".join(sorted({fixture_case.fixture for fixture_case in fixture_cases}))
        console.print(f"[dim]Fixtures:[/] {fixture_names}")
        if len(results) == 1:
            _print_case_detail(results[0], show_misses=misses)
            _print_quality_status(results, min_recall=min_recall, min_token_precision=min_token_precision)
        else:
            console.print("\n[bold]Summary[/]")
            _print_fixture_summary_table(results)
            _print_task_type_summary(results)
            if misses:
                _print_miss_details(results)
            _print_quality_status(results, min_recall=min_recall, min_token_precision=min_token_precision)
        if public_table:
            from agentpack import __version__
            out = _write_public_benchmark_table(
                root,
                results,
                suite=f"source-checkout fixtures ({fixture_names})",
                version=__version__,
                command="agentpack benchmark --sample-fixtures --misses --public-table",
            )
            console.print(f"[green]✓[/] Wrote public benchmark table: [bold]{out}[/]")
        if prove_targets and not _quality_status(results, min_recall=min_recall, min_token_precision=min_token_precision)[0]:
            raise typer.Exit(2)
        return

    if public_repos:
        manifest = Path(public_repos_file) if public_repos_file else _default_public_repos_file(root)
        if not manifest.exists():
            console.print(f"[yellow]No public repo manifest found at {manifest}[/]")
            console.print("  Use [bold]benchmarks/public-repos.toml[/] or pass [bold]--public-repos-file[/].")
            raise typer.Exit(1)
        specs = _load_public_repo_specs(manifest)
        case_count = sum(len(spec.cases) for spec in specs)
        if not specs or case_count == 0:
            console.print(f"[yellow]No public repo cases found in {manifest}[/]")
            raise typer.Exit(1)

        console.print(f"\n[bold]Running {case_count} public real-repo benchmark case(s)...[/]")
        console.print(f"[dim]Manifest:[/] {manifest}")
        console.print("[dim]Each case checks out the parent of a real public commit and scores files changed by that commit.[/]\n")
        cache = Path(public_repos_cache) if public_repos_cache else None
        with console.status("[dim]Cloning/checking out public repo cases...[/]"):
            results = _run_public_repo_suite(root, specs, cache_dir=cache, refresh=refresh_public_repos)

        if not results:
            raise typer.Exit(1)

        console.print("\n[bold]Summary[/]")
        _print_summary_table(results)
        _print_task_type_summary(results)
        if misses:
            _print_miss_details(results)
        _print_quality_status(results, min_recall=min_recall, min_token_precision=min_token_precision)
        if public_table:
            from agentpack import __version__
            repo_names = ", ".join(spec.name for spec in specs)
            out = _write_public_benchmark_table(
                root,
                results,
                suite=f"public real-repo commits ({repo_names})",
                version=__version__,
                command="agentpack benchmark --release-gate",
            )
            console.print(f"[green]✓[/] Wrote public benchmark table: [bold]{out}[/]")
        if prove_targets and not _quality_status(results, min_recall=min_recall, min_token_precision=min_token_precision)[0]:
            raise typer.Exit(2)
        return

    # Build case list
    if from_history > 0:
        bench_cases = _load_history_cases(root, from_history)
        if not bench_cases:
            console.print("[yellow]No task history found in metrics.jsonl. Run agentpack pack first.[/]")
            raise typer.Exit(1)
        if write_cases:
            out = _append_benchmark_cases(root, bench_cases)
            console.print(f"[green]✓[/] Appended {len(bench_cases)} history case(s) to [bold]{out}[/]")
            console.print("[yellow]History cases do not prove recall until expected_files are filled.[/]")
    elif task:
        resolved = _resolve_task(task) if task == "auto" else task
        bench_cases = [BenchmarkCase(task=resolved, mode=mode, workspace=workspace or None)]
    else:
        cases_path = Path(cases) if cases else root / ".agentpack" / "benchmark.toml"
        if not cases_path.exists():
            console.print(f"[yellow]No cases file found at {cases_path}[/]")
            console.print("  Run [bold]agentpack benchmark --init[/] to scaffold one, or use [bold]--task \"...\"[/]")
            raise typer.Exit(1)
        bench_cases = _load_cases(cases_path)
        if not bench_cases:
            console.print("[yellow]No cases defined in benchmark file.[/]")
            raise typer.Exit(1)
    if workspace and not compare:
        bench_cases = [
            BenchmarkCase(
                task=c.task,
                mode=c.mode,
                expected_files=c.expected_files,
                task_type=c.task_type,
                workspace=workspace,
                budget=c.budget,
            )
            for c in bench_cases
        ]

    # Expand for compare mode
    if compare:
        expanded: list[BenchmarkCase] = []
        for c in bench_cases:
            for m in ("minimal", "balanced", "deep"):
                expanded.append(
                    BenchmarkCase(
                        task=c.task,
                        mode=m,
                        expected_files=c.expected_files,
                        task_type=c.task_type,
                        workspace=workspace or c.workspace,
                        budget=c.budget,
                    )
                )
        bench_cases = expanded

    console.print(f"\n[bold]Running {len(bench_cases)} benchmark case(s)...[/]\n")

    results: list[CaseResult] = []
    for i, c in enumerate(bench_cases, 1):
        label = f"[{i}/{len(bench_cases)}] {c.task[:50]}  mode={c.mode}"
        with console.status(f"[dim]{label}[/]"):
            try:
                r = _run_case(root, c)
                _persist_result(root, r)
                results.append(r)
            except Exception as e:
                console.print(f"[red]Error on case '{c.task}': {e}[/]")

    if not results:
        raise typer.Exit(1)

    # Output
    if compare and len(set(r.case.task for r in results)) == 1:
        _print_compare_table(results[0].case.task, results)
        if misses:
            _print_miss_details(results)
        _print_quality_status(results, min_recall=min_recall, min_token_precision=min_token_precision)
    elif len(results) == 1:
        _print_case_detail(results[0], show_misses=misses)
        _print_quality_status(results, min_recall=min_recall, min_token_precision=min_token_precision)
    else:
        if not compare:
            for r in results:
                _print_case_detail(r, show_misses=misses)
        console.print("\n[bold]Summary[/]")
        _print_summary_table(results)
        _print_task_type_summary(results)
        if misses:
            _print_miss_details(results)
        _print_quality_status(results, min_recall=min_recall, min_token_precision=min_token_precision)
    if public_table:
        from agentpack import __version__
        out = _write_public_benchmark_table(
            root,
            results,
            suite="current repo benchmark.toml",
            version=__version__,
            command="agentpack benchmark --misses --public-table",
        )
        console.print(f"[green]✓[/] Wrote public benchmark table: [bold]{out}[/]")
    if prove_targets and not _quality_status(results, min_recall=min_recall, min_token_precision=min_token_precision)[0]:
        raise typer.Exit(2)
