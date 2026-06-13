from __future__ import annotations

import json
import hashlib
import random
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fnmatch import fnmatch
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
from agentpack.core.modes import MODE_HELP, invalid_mode_message, is_requested_mode, normalize_mode
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
    expected_skills: list[str] = field(default_factory=list)
    avoid_skills: list[str] = field(default_factory=list)
    task_type: str = "general"
    workspace: str | None = None
    budget: int = 0

    def __post_init__(self) -> None:
        self.mode = normalize_mode(self.mode)


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
    candidate_recall_at_20: float | None = None
    candidate_recall_at_50: float | None = None
    candidate_recall_at_100: float | None = None
    candidate_precision_at_3: float | None = None
    candidate_precision_at_5: float | None = None
    low_budget_extra_file_waste: int | None = None
    precision_delta_if_drop_last_summary: float | None = None
    expected_token_coverage: float | None = None
    selected_family_tokens: dict[str, int] = field(default_factory=dict)
    selected_family_waste_tokens: dict[str, int] = field(default_factory=dict)
    reason_family_precision: dict[str, dict[str, float]] = field(default_factory=dict)
    failure_type_counts: dict[str, int] = field(default_factory=dict)
    noise_pct: float | None = None  # tokens on non-expected / packed; None if no expected
    random_precision: float | None = None
    random_recall: float | None = None
    random_f1: float | None = None
    selected_skills: list[str] = field(default_factory=list)
    skill_recall_at_3: float | None = None
    skill_precision_at_3: float | None = None
    skill_mrr: float | None = None
    skill_noise_rate: float | None = None
    skill_token_cost: int = 0
    missed_expected: list[dict[str, Any]] = field(default_factory=list)
    selected_modes: dict[str, str] = field(default_factory=dict)
    top_candidates: list[dict[str, Any]] = field(default_factory=list)
    selection_diagnostics: dict[str, Any] = field(default_factory=dict)


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

    def __post_init__(self) -> None:
        self.mode = normalize_mode(self.mode)


@dataclass
class PublicRepoSpec:
    name: str
    url: str
    ref: str = "main"
    cases: list[PublicRepoCase] = field(default_factory=list)
    sample_history: int = 0
    task_type: str = "general"
    mode: str = "balanced"
    budget: int = 0
    include_globs: list[str] = field(default_factory=list)
    exclude_globs: list[str] = field(default_factory=list)
    max_changed_files: int = 8

    def __post_init__(self) -> None:
        self.mode = normalize_mode(self.mode)


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
    agent_output_tokens: int
    estimated_input_cost_usd: float
    estimated_output_cost_usd: float
    estimated_total_cost_usd: float
    agent_returncode: int
    test_returncode: int
    timed_out: bool
    agent_tool_calls: int
    time_to_first_expected_file_s: float | None
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
                mode=normalize_mode(raw_case.get("mode", "balanced")),
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
            sample_history=int(raw_repo.get("sample_history", 0) or 0),
            task_type=raw_repo.get("task_type", "general"),
            mode=normalize_mode(raw_repo.get("mode", "balanced")),
            budget=int(raw_repo.get("budget", 0) or 0),
            include_globs=raw_repo.get("include_globs", []),
            exclude_globs=raw_repo.get("exclude_globs", []),
            max_changed_files=int(raw_repo.get("max_changed_files", 8) or 8),
        ))
    return specs


def _split_filter_values(value: str) -> set[str]:
    return {part.strip() for part in value.split(",") if part.strip()}


def _filter_public_repo_specs(
    specs: list[PublicRepoSpec],
    *,
    repo_filter: str = "",
    task_type_filter: str = "",
) -> list[PublicRepoSpec]:
    repo_names = _split_filter_values(repo_filter)
    task_types = _split_filter_values(task_type_filter)
    if not repo_names and not task_types:
        return specs
    filtered: list[PublicRepoSpec] = []
    for spec in specs:
        if repo_names and spec.name not in repo_names:
            continue
        cases = [case for case in spec.cases if not task_types or case.task_type in task_types]
        include_sampled_history = not task_types or spec.task_type in task_types
        sample_history = spec.sample_history if include_sampled_history else 0
        if not cases and sample_history <= 0:
            continue
        filtered.append(
            PublicRepoSpec(
                name=spec.name,
                url=spec.url,
                ref=spec.ref,
                cases=cases,
                sample_history=sample_history,
                task_type=spec.task_type,
                mode=spec.mode,
                budget=spec.budget,
                include_globs=spec.include_globs,
                exclude_globs=spec.exclude_globs,
                max_changed_files=spec.max_changed_files,
            )
        )
    return filtered


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
            mode=normalize_mode(raw.get("mode", "balanced")),
            expected_files=raw.get("expected_files", []),
            expected_skills=raw.get("expected_skills", []),
            avoid_skills=raw.get("avoid_skills", []),
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
        '# expected_skills = ["pytest-debugging", "auth-flow-review"]\n'
        '# avoid_skills = ["frontend-react-review"]\n\n'
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
        last_summary_waste, drop_last_delta, waste_cases = _low_budget_waste_summary(scored)
        lines += [
            "| Metric | Value |",
            "|---|---:|",
            f"| avg precision | {avg_p:.1%} |",
            f"| avg recall | {avg_r:.1%} |",
            f"| avg F1 | {avg_f1:.1%} |",
            f"| avg token precision | {avg_token_precision:.1%} |",
            f"| pack p50 tokens | {p50_tokens:,} |",
            f"| pack p95 tokens | {p95_tokens:,} |",
        ]
        if waste_cases:
            lines += [
                f"| low-budget cases with last-summary diagnostic | {waste_cases} |",
                f"| avg last-summary waste | {last_summary_waste:.0f} tokens |",
                f"| avg precision delta if drop last summary | {drop_last_delta:+.1%} |",
            ]
        lines += [
            "",
        ]

    lines += [
        "| Repo / suite | Task | Type | Mode | Budget | Packed tokens | Recall | Cand R@50 | Cand P@3 | Token precision | Rank@K | Time | Misses |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
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
                f"{result.candidate_recall_at_50:.1%}" if result.candidate_recall_at_50 is not None else "-",
                f"{result.candidate_precision_at_3:.1%}" if result.candidate_precision_at_3 is not None else "-",
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


def _git_lines(cwd: Path, args: list[str]) -> list[str]:
    output = _git_stdout(cwd, args)
    return [line for line in output.splitlines() if line.strip()]


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
            "--depth",
            str(depth),
            spec.url,
            str(repo_dir),
        ])
    else:
        _run_git(repo_dir, ["fetch", "--quiet", "--depth", str(depth), "origin", spec.ref])
    _run_git(repo_dir, ["checkout", "--quiet", spec.ref])
    _run_git(repo_dir, ["reset", "--hard", "--quiet", spec.ref])
    _run_git(repo_dir, ["clean", "-ffd", "--quiet"])
    return repo_dir


def _sample_public_history_cases(source_repo: Path, spec: PublicRepoSpec) -> list[PublicRepoCase]:
    """Create benchmark cases from recent public commits and their real changed files."""
    if spec.sample_history <= 0:
        return []
    candidates = _git_lines(
        source_repo,
        [
            "log",
            "--first-parent",
            "--no-merges",
            "--format=%H%x00%s",
            f"-n{max(spec.sample_history * 4, spec.sample_history)}",
            spec.ref,
        ],
    )
    cases: list[PublicRepoCase] = []
    explicit_commits = {case.commit for case in spec.cases}
    for line in candidates:
        if "\x00" not in line:
            continue
        commit, subject = line.split("\x00", 1)
        if commit in explicit_commits:
            continue
        expected_files = _public_commit_changed_files(
            source_repo,
            commit,
            include_globs=spec.include_globs,
            exclude_globs=spec.exclude_globs,
            max_changed_files=spec.max_changed_files,
        )
        if not expected_files:
            continue
        cases.append(
            PublicRepoCase(
                commit=commit,
                task=subject,
                expected_files=expected_files,
                mode=spec.mode,
                task_type=spec.task_type,
                budget=spec.budget,
            )
        )
        if len(cases) >= spec.sample_history:
            break
    return cases


def _public_commit_changed_files(
    source_repo: Path,
    commit: str,
    *,
    include_globs: list[str],
    exclude_globs: list[str],
    max_changed_files: int,
) -> list[str]:
    try:
        parent = _git_stdout(source_repo, ["rev-parse", f"{commit}^"])
        files = _git_lines(
            source_repo,
            ["diff-tree", "--no-commit-id", "--name-only", "-r", commit],
        )
    except subprocess.CalledProcessError:
        return []
    filtered = [
        path
        for path in files
        if _public_path_allowed(path, include_globs=include_globs, exclude_globs=exclude_globs)
        and _public_path_exists_at_commit(source_repo, parent, path)
    ]
    if not filtered or len(filtered) > max_changed_files:
        return []
    return sorted(filtered)


def _public_path_exists_at_commit(source_repo: Path, commit: str, path: str) -> bool:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}:{path}"],
        cwd=source_repo,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _public_path_allowed(path: str, *, include_globs: list[str], exclude_globs: list[str]) -> bool:
    if any(part in path for part in ("/vendor/", "/dist/", "/build/", "/node_modules/")):
        return False
    if Path(path).name in {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "go.sum"}:
        return False
    if exclude_globs and any(fnmatch(path, pattern) for pattern in exclude_globs):
        return False
    return not include_globs or any(fnmatch(path, pattern) for pattern in include_globs)


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
            public_cases = [*spec.cases, *_sample_public_history_cases(source_repo, spec)]
            for public_case in public_cases:
                _ensure_git_commit(source_repo, public_case.commit)
                parent = _git_stdout(source_repo, ["rev-parse", f"{public_case.commit}^"])
                _ensure_git_commit(source_repo, parent)
                work_root = temp_root / f"{spec.name}-{public_case.commit[:8]}"
                shutil.copytree(
                    source_repo,
                    work_root,
                    ignore=shutil.ignore_patterns(".agentpack", ".pytest_cache", "__pycache__"),
                )
                try:
                    _run_git(work_root, ["checkout", "--force", "--quiet", parent])
                    _run_git(work_root, ["reset", "--hard", "--quiet", parent])
                    _run_git(work_root, ["clean", "-ffd", "--quiet"])
                except subprocess.CalledProcessError as exc:
                    stderr = (exc.stderr or "").strip()
                    command = " ".join(str(part) for part in exc.cmd)
                    detail = f": {stderr}" if stderr else ""
                    raise RuntimeError(
                        "Public benchmark checkout failed "
                        f"for repo={spec.name} commit={public_case.commit} parent={parent}; "
                        f"`{command}` exited {exc.returncode}{detail}"
                    ) from exc
                result = _run_case(
                    work_root,
                    BenchmarkCase(
                        task=public_case.task,
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
            mode = normalize_mode(rec.get("mode", "balanced"))
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
        if case.expected_skills:
            lines.append("expected_skills = [" + ", ".join(json.dumps(skill) for skill in case.expected_skills) + "]")
        if case.avoid_skills:
            lines.append("avoid_skills = [" + ", ".join(json.dumps(skill) for skill in case.avoid_skills) + "]")
        blocks.append("\n".join(lines))
    out.write_text(prefix + "\n\n".join(blocks) + "\n", encoding="utf-8")
    return out


def _write_anonymous_benchmark_report(root: Path) -> tuple[Path, Path]:
    data = _anonymous_benchmark_report_data(root)
    report_json = root / ".agentpack" / "benchmark-report.json"
    report_md = root / ".agentpack" / "benchmark-report.md"
    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_md.write_text(_anonymous_benchmark_report_markdown(data), encoding="utf-8")
    return report_md, report_json


def _anonymous_benchmark_report_data(root: Path) -> dict[str, Any]:
    cases_path = root / ".agentpack" / "benchmark.toml"
    cases = _load_cases(cases_path) if cases_path.exists() else []
    records = _load_jsonl(root / ".agentpack" / "benchmark_results.jsonl")
    scored_records = [
        record
        for record in records
        if isinstance(record.get("recall"), (int, float))
        and isinstance(record.get("token_precision"), (int, float))
    ]
    language_mix = _language_mix(root)
    avg_recall = _avg_record_value(scored_records, "recall")
    avg_token_precision = _avg_record_value(scored_records, "token_precision")
    miss_count = sum(len(record.get("misses") or []) for record in scored_records)
    repo_type = "public" if (root / ".git").exists() and _git_remote_public(root) else "private-or-local"
    return {
        "schema_version": 1,
        "repo_type": repo_type,
        "language_mix": language_mix,
        "cases": len(cases),
        "scored_runs": len(scored_records),
        "recall": round(avg_recall, 3) if avg_recall is not None else None,
        "token_precision": round(avg_token_precision, 3) if avg_token_precision is not None else None,
        "misses": miss_count,
        "no_source_code_uploaded": True,
        "source_paths_included": False,
        "generated_files": [
            ".agentpack/benchmark-report.md",
            ".agentpack/benchmark-report.json",
        ],
    }


def _anonymous_benchmark_report_markdown(data: dict[str, Any]) -> str:
    language_rows = "\n".join(
        f"| {language} | {share:.1%} |"
        for language, share in data.get("language_mix", {}).items()
    ) or "| unknown | 0.0% |"
    recall = _fmt_report_pct(data.get("recall"))
    token_precision = _fmt_report_pct(data.get("token_precision"))
    return "\n".join([
        "# AgentPack Anonymous Benchmark Report",
        "",
        f"- Repo type: {data['repo_type']}",
        f"- Cases: {data['cases']}",
        f"- Scored runs: {data['scored_runs']}",
        f"- Recall: {recall}",
        f"- Token precision: {token_precision}",
        f"- Misses: {data['misses']}",
        f"- No source code uploaded: {str(data['no_source_code_uploaded']).lower()}",
        "",
        "## Language Mix",
        "",
        "| Language | Share |",
        "|---|---:|",
        language_rows,
        "",
        "## Notes",
        "",
        "- This report contains aggregate counts and percentages only.",
        "- It does not include source code or private file contents.",
        "- Share with: `agentpack benchmark capture --since main --anonymous-report`.",
        "",
    ]) + "\n"


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def _avg_record_value(records: list[dict[str, Any]], key: str) -> float | None:
    values = [float(record[key]) for record in records if isinstance(record.get(key), (int, float))]
    return sum(values) / len(values) if values else None


def _fmt_report_pct(value: Any) -> str:
    return f"{float(value):.1%}" if isinstance(value, (int, float)) else "not measured"


def _language_mix(root: Path) -> dict[str, float]:
    counts: dict[str, int] = {}
    suffix_map = {
        ".py": "Python",
        ".ts": "TypeScript",
        ".tsx": "TypeScript",
        ".js": "JavaScript",
        ".jsx": "JavaScript",
        ".go": "Go",
        ".java": "Java",
        ".rs": "Rust",
        ".rb": "Ruby",
        ".yaml": "YAML",
        ".yml": "YAML",
        ".toml": "TOML",
    }
    for path in root.rglob("*"):
        if not path.is_file() or _anonymous_skip_path(path, root):
            continue
        language = suffix_map.get(path.suffix.lower())
        if language:
            counts[language] = counts.get(language, 0) + 1
    total = sum(counts.values())
    if total == 0:
        return {}
    return {
        language: round(count / total, 4)
        for language, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    }


def _anonymous_skip_path(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    parts = set(rel.parts)
    return bool(parts & {".git", ".agentpack", "node_modules", ".venv", "__pycache__", "dist", "build"})


def _git_remote_public(root: Path) -> bool:
    try:
        remotes = _git_lines(root, ["remote", "-v"])
    except subprocess.CalledProcessError:
        return False
    return any("github.com" in line or "gitlab.com" in line for line in remotes)


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
    candidate_recall_at_20: float | None = None
    candidate_recall_at_50: float | None = None
    candidate_recall_at_100: float | None = None
    candidate_precision_at_3: float | None = None
    candidate_precision_at_5: float | None = None
    noise_pct: float | None = None
    low_budget_extra_file_waste: int | None = None
    precision_delta_if_drop_last_summary: float | None = None
    expected_token_coverage: float | None = None
    selected_family_tokens: dict[str, int] = {}
    selected_family_waste_tokens: dict[str, int] = {}
    reason_family_precision: dict[str, dict[str, float]] = {}
    failure_type_counts: dict[str, int] = {}
    top_candidates: list[dict[str, Any]] = []
    selection_diagnostics: dict[str, Any] = {}
    rand_p = rand_r = rand_f1 = None

    if case.expected_files:
        expected_set = set(case.expected_files)
        ranked_scored = sorted(plan.scored, key=lambda item: item[1], reverse=True)
        scored_paths = [fi.path for fi, _score, _reasons in ranked_scored]
        candidate_recall_at_20 = _candidate_recall_at(scored_paths, expected_set, 20)
        candidate_recall_at_50 = _candidate_recall_at(scored_paths, expected_set, 50)
        candidate_recall_at_100 = _candidate_recall_at(scored_paths, expected_set, 100)
        candidate_precision_at_3 = _candidate_precision_at(scored_paths, expected_set, 3)
        candidate_precision_at_5 = _candidate_precision_at(scored_paths, expected_set, 5)
        scored_map = {
            fi.path: {
                "rank": rank,
                "score": score,
                "reasons": reasons,
                "estimated_tokens": int(getattr(fi, "estimated_tokens", 0) or 0),
            }
            for rank, (fi, score, reasons) in enumerate(ranked_scored, 1)
        }
        top_candidates = _top_candidate_diagnostics(
            ranked_scored=ranked_scored,
            selected_set=selected_set,
            expected_set=expected_set,
        )
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
        expected_total_tokens = sum(
            all_file_map[p].estimated_tokens
            for p in expected_set
            if p in all_file_map and getattr(all_file_map[p], "estimated_tokens", 0) > 0
        )
        expected_token_coverage = expected_tokens / expected_total_tokens if expected_total_tokens > 0 else None
        selected_family_tokens = _selected_family_tokens(selected_paths, selected_tokens)
        selected_family_waste_tokens = _selected_family_tokens(
            [path for path in selected_paths if path not in expected_set],
            selected_tokens,
        )
        reason_family_precision = _reason_family_precision(plan.selected, expected_set)
        selected_by_path = {sf.path: sf for sf in plan.selected}
        selected_noise = _selected_noise_diagnostics(
            selected_paths=selected_paths,
            selected_tokens=selected_tokens,
            selected_modes=selected_modes,
            scored_map=scored_map,
            expected_set=expected_set,
        )
        low_budget_extra_file_waste, precision_delta_if_drop_last_summary = _low_budget_extra_file_waste(
            selected=plan.selected,
            selected_tokens=selected_tokens,
            expected_files=expected_set,
            packed_tokens=packed_tokens,
            expected_tokens=expected_tokens,
            budget=case.budget or cfg.context.default_budget,
            changed_files_source=plan.changed_files_source,
        )

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
            failure_type = _miss_failure_type(
                fi=fi,
                scored_info=scored_info,
                status=status,
                selected_count=len(selected_paths),
            )
            failure_type_counts[failure_type] = failure_type_counts.get(failure_type, 0) + 1
            missed_expected.append({
                "path": expected_path,
                "status": status,
                "failure_type": failure_type,
                "family": _path_family(expected_path),
                "rank": scored_info["rank"] if scored_info else None,
                "score": round(scored_info["score"], 1) if scored_info else None,
                "reasons": scored_info["reasons"][:4] if scored_info else [],
                "basis": plan.changed_files_source,
                "would_select_with_one_more_slot": _would_select_with_one_more_slot(
                    scored_info=scored_info,
                    selected_count=len(selected_paths),
                    status=status,
                ),
                "score_delta_vs_last_selected": _score_delta_vs_last_selected(
                    scored_info=scored_info,
                    selected_paths=selected_paths,
                    scored_map=scored_map,
                ),
                "selected_noise_file_that_beat_expected": _selected_noise_that_beat_expected(
                    scored_info=scored_info,
                    selected_noise=selected_noise,
                ),
                "cap_block_diagnostic": _cap_block_diagnostic(
                    status=status,
                    fi=fi,
                    scored_info=scored_info,
                    summaries=plan.summaries,
                    selected_by_path=selected_by_path,
                    selected_tokens=selected_tokens,
                    expected_set=expected_set,
                    packed_tokens=packed_tokens,
                    budget=budget,
                ),
            })
        plausibly_useful_noise = _plausibly_useful_selected_noise(
            selected_noise=selected_noise,
            expected_set=expected_set,
            scored_map=scored_map,
        )
        selection_diagnostics = {
            "selected_noise": selected_noise[:10],
            "selected_noise_family_tokens": selected_family_waste_tokens,
            "expected_ranked_not_selected": sum(1 for miss in missed_expected if miss["rank"] is not None),
            "missed_expected_count": len(missed_expected),
            "replacement_pairs": _replacement_pair_diagnostics(plan.receipts, scored_map, selected_tokens),
            "same_scope_replacement_opportunities": _same_scope_replacement_opportunities(
                missed_expected=missed_expected,
                selected_noise=selected_noise,
                scored_map=scored_map,
            ),
            "selected_not_expected_but_plausibly_useful": plausibly_useful_noise,
            "label_audit": _label_audit_summary(
                selected_noise=selected_noise,
                plausibly_useful=plausibly_useful_noise,
                packed_tokens=packed_tokens,
            ),
            "owner_file_recall": _owner_file_recall(selected_set=selected_set, expected_set=expected_set),
            "expected_family_recall": _expected_family_recall(selected_set=selected_set, expected_set=expected_set),
            "expected_include_modes": _expected_include_mode_diagnostics(
                expected_set=expected_set,
                selected_modes=selected_modes,
            ),
            "expected_rank_distribution": _expected_rank_distribution(expected_set, scored_map),
            "package_boundary": _package_boundary_diagnostics(
                selected_paths=selected_paths,
                expected_set=expected_set,
            ),
        }
    else:
        missed_expected = []

    selected_skills, skill_token_cost = _route_skills_for_case(root, case)
    skill_recall, skill_precision, skill_mrr, skill_noise = _skill_metrics(
        selected_skills,
        expected_skills=case.expected_skills,
        avoid_skills=case.avoid_skills,
    )

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
        candidate_recall_at_20=candidate_recall_at_20,
        candidate_recall_at_50=candidate_recall_at_50,
        candidate_recall_at_100=candidate_recall_at_100,
        candidate_precision_at_3=candidate_precision_at_3,
        candidate_precision_at_5=candidate_precision_at_5,
        low_budget_extra_file_waste=low_budget_extra_file_waste,
        precision_delta_if_drop_last_summary=precision_delta_if_drop_last_summary,
        expected_token_coverage=expected_token_coverage,
        selected_family_tokens=selected_family_tokens,
        selected_family_waste_tokens=selected_family_waste_tokens,
        reason_family_precision=reason_family_precision,
        failure_type_counts=failure_type_counts,
        noise_pct=noise_pct,
        random_precision=rand_p,
        random_recall=rand_r,
        random_f1=rand_f1,
        selected_skills=selected_skills,
        skill_recall_at_3=skill_recall,
        skill_precision_at_3=skill_precision,
        skill_mrr=skill_mrr,
        skill_noise_rate=skill_noise,
        missed_expected=missed_expected,
        top_candidates=top_candidates,
        selection_diagnostics=selection_diagnostics,
    )


def _candidate_recall_at(scored_paths: list[str], expected_files: set[str], k: int) -> float:
    if not expected_files:
        return 0.0
    return len(set(scored_paths[:k]) & expected_files) / len(expected_files)


def _candidate_precision_at(scored_paths: list[str], expected_files: set[str], k: int) -> float:
    candidates = scored_paths[:k]
    if not candidates:
        return 0.0
    return len(set(candidates) & expected_files) / len(candidates)


def _top_candidate_diagnostics(
    *,
    ranked_scored: list[tuple[Any, float, list[str]]],
    selected_set: set[str],
    expected_set: set[str],
    limit: int = 10,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rank, (fi, score, reasons) in enumerate(ranked_scored[:limit], 1):
        path = str(getattr(fi, "path", ""))
        rows.append({
            "path": path,
            "rank": rank,
            "score": round(score, 1),
            "family": _path_family(path),
            "selected": path in selected_set,
            "expected": path in expected_set,
            "reasons": reasons[:4],
        })
    return rows


def _selected_noise_diagnostics(
    *,
    selected_paths: list[str],
    selected_tokens: dict[str, int],
    selected_modes: dict[str, str],
    scored_map: dict[str, dict[str, Any]],
    expected_set: set[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in selected_paths:
        if path in expected_set:
            continue
        scored_info = scored_map.get(path)
        rows.append({
            "path": path,
            "family": _path_family(path),
            "tokens": selected_tokens.get(path, 0),
            "mode": selected_modes.get(path),
            "rank": scored_info["rank"] if scored_info else None,
            "score": round(scored_info["score"], 1) if scored_info else None,
            "reasons": scored_info["reasons"][:4] if scored_info else [],
        })
    return rows


def _would_select_with_one_more_slot(
    *,
    scored_info: dict[str, Any] | None,
    selected_count: int,
    status: str,
) -> bool:
    if scored_info is None:
        return False
    if any(term in status.lower() for term in ("not found", "ignored", "binary", "scored too low")):
        return False
    return int(scored_info.get("rank") or 0) <= selected_count + 1


def _score_delta_vs_last_selected(
    *,
    scored_info: dict[str, Any] | None,
    selected_paths: list[str],
    scored_map: dict[str, dict[str, Any]],
) -> float | None:
    if scored_info is None:
        return None
    for path in reversed(selected_paths):
        selected_info = scored_map.get(path)
        if selected_info:
            delta = float(scored_info["score"]) - float(selected_info["score"])
            return round(delta, 1)
    return None


def _selected_noise_that_beat_expected(
    *,
    scored_info: dict[str, Any] | None,
    selected_noise: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if scored_info is None:
        return selected_noise[0] if selected_noise else None
    expected_rank = int(scored_info.get("rank") or 0)
    expected_score = float(scored_info.get("score") or 0.0)
    ranked_noise = [
        row for row in selected_noise
        if row.get("rank") is not None and int(row["rank"]) < expected_rank
    ]
    if not ranked_noise:
        ranked_noise = [
            row for row in selected_noise
            if row.get("score") is not None and float(row["score"]) >= expected_score
        ]
    return ranked_noise[0] if ranked_noise else None


_CAP_STRONG_REASON_PREFIXES = (
    "direct content evidence",
    "direct dependency",
    "has related tests",
    "historically co-changed",
    "keyword phrase match:",
    "literal definition match:",
    "matched call:",
    "matched define:",
    "matched entrypoint:",
    "matched env read:",
    "matched external system:",
    "matched side effect:",
    "multi-token",
    "quoted literal match:",
    "release/version metadata",
    "reverse dependency",
    "test for",
    "workspace match",
)


def _cap_block_diagnostic(
    *,
    status: str,
    fi: Any,
    scored_info: dict[str, Any] | None,
    summaries: dict[str, Any],
    selected_by_path: dict[str, Any],
    selected_tokens: dict[str, int],
    expected_set: set[str],
    packed_tokens: int,
    budget: int,
) -> dict[str, Any] | None:
    if "cap reached" not in status.lower():
        return None
    candidate_path = str(getattr(fi, "path", ""))
    candidate_tokens, candidate_mode = _candidate_compressed_estimate(
        candidate_path,
        fi=fi,
        score=float(scored_info["score"]) if scored_info else 0.0,
        summaries=summaries,
    )
    candidate_reasons = scored_info["reasons"] if scored_info else []
    candidate_has_strong_evidence = _cap_has_strong_evidence(candidate_reasons)
    replaceable = _replaceable_selected_noise(
        selected_by_path=selected_by_path,
        selected_tokens=selected_tokens,
        expected_set=expected_set,
    )
    replaceable_tokens = sum(item["tokens"] for item in replaceable)
    needed_tokens = max(0, packed_tokens + candidate_tokens - budget)
    if not candidate_has_strong_evidence:
        block_reason = "candidate evidence below replacement gate"
    elif not replaceable:
        block_reason = "no replaceable selected compressed noise"
    elif replaceable_tokens < needed_tokens:
        block_reason = "candidate too large for replaceable selected noise"
    else:
        block_reason = "replacement appears feasible"
    return {
        "candidate_tokens": candidate_tokens,
        "candidate_mode": candidate_mode,
        "candidate_has_strong_evidence": candidate_has_strong_evidence,
        "needed_tokens": needed_tokens,
        "replaceable_selected_tokens": replaceable_tokens,
        "replaceable_selected": replaceable[:5],
        "block_reason": block_reason,
    }


def _candidate_compressed_estimate(
    path: str,
    *,
    fi: Any,
    score: float,
    summaries: dict[str, Any],
) -> tuple[int, str]:
    summary_data = summaries.get(path) or {}
    symbols = _summary_symbols(summary_data)
    if symbols and score >= 160:
        parts: list[str] = []
        summary = str(summary_data.get("summary") or "").strip() if isinstance(summary_data, dict) else ""
        if summary:
            parts.append(summary)
        parts.extend(signature for signature in symbols if signature)
        text = "\n".join(parts)
        return (estimate_tokens(text) if text else 50), "skeleton"
    if isinstance(summary_data, dict):
        summary = str(summary_data.get("summary") or "").strip()
        if summary:
            return estimate_tokens(summary), "summary"
    return min(int(getattr(fi, "estimated_tokens", 0) or 0), 200) or 50, "summary"


def _summary_symbols(summary_data: Any) -> list[str]:
    if not isinstance(summary_data, dict):
        return []
    signatures: list[str] = []
    for item in summary_data.get("symbols") or []:
        if isinstance(item, dict):
            signature = item.get("signature")
            if signature:
                signatures.append(str(signature))
        elif hasattr(item, "signature") and item.signature:
            signatures.append(str(item.signature))
    return signatures


def _cap_has_strong_evidence(reasons: list[str]) -> bool:
    content_hits = 0
    for reason in reasons:
        match = re.match(r"content keyword match \((\d+)\)", reason)
        if match:
            content_hits = max(content_hits, int(match.group(1)))
    if content_hits >= 3 and any(reason.startswith(("matched define:", "matched call:", "keyword phrase match:")) for reason in reasons):
        return True
    if "config file" in reasons and content_hits >= 2:
        return True
    return any(reason.startswith(_CAP_STRONG_REASON_PREFIXES) for reason in reasons)


def _replacement_pair_diagnostics(
    receipts: list[Any],
    scored_map: dict[str, dict[str, Any]],
    selected_tokens: dict[str, int],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    marker = "marginal slot replaced by "
    for receipt in receipts:
        reason = getattr(receipt, "reason", "")
        if not isinstance(reason, str) or marker not in reason:
            continue
        displaced_path = getattr(receipt, "path", "")
        challenger_path = reason.split(marker, 1)[1].strip()
        displaced = scored_map.get(displaced_path, {})
        challenger = scored_map.get(challenger_path, {})
        rows.append({
            "displaced": displaced_path,
            "challenger": challenger_path,
            "displaced_score": round(float(displaced.get("score", 0.0) or 0.0), 1),
            "challenger_score": round(float(challenger.get("score", 0.0) or 0.0), 1),
            "challenger_rank": challenger.get("rank"),
            "displaced_tokens": selected_tokens.get(displaced_path, 0),
            "challenger_reasons": list(challenger.get("reasons", []) or [])[:4],
            "displaced_reasons": list(displaced.get("reasons", []) or [])[:4],
        })
    return rows[:20]


def _same_scope_replacement_opportunities(
    *,
    missed_expected: list[dict[str, Any]],
    selected_noise: list[dict[str, Any]],
    scored_map: dict[str, dict[str, Any]],
    limit: int = 20,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for miss in missed_expected:
        missed_path = str(miss.get("path") or "")
        missed_info = scored_map.get(missed_path) or {}
        cap_diagnostic = miss.get("cap_block_diagnostic")
        if isinstance(cap_diagnostic, dict):
            missed_tokens = int(cap_diagnostic.get("candidate_tokens") or 0)
        else:
            missed_tokens = int(missed_info.get("estimated_tokens") or 0)
        if not missed_path or missed_tokens <= 0 or miss.get("rank") is None:
            continue
        if not _diagnostic_replacement_status(str(miss.get("status") or "")):
            continue
        missed_scope = _diagnostic_scope(missed_path)
        missed_reasons = list(miss.get("reasons") or [])
        missed_evidence = _diagnostic_evidence_score(
            path=missed_path,
            score=float(miss.get("score") or 0.0),
            reasons=missed_reasons,
        )
        for noise in selected_noise:
            noise_path = str(noise.get("path") or "")
            noise_tokens = int(noise.get("tokens") or 0)
            if not noise_path or noise_tokens <= 0 or missed_tokens > noise_tokens:
                continue
            noise_scope = _diagnostic_scope(noise_path)
            if not _diagnostic_related_scope(missed_scope, noise_scope):
                continue
            noise_reasons = list(noise.get("reasons") or [])
            noise_evidence = _diagnostic_evidence_score(
                path=noise_path,
                score=float(noise.get("score") or 0.0),
                reasons=noise_reasons,
            )
            evidence_gain = missed_evidence - noise_evidence
            if evidence_gain < 25:
                continue
            rows.append({
                "missed": missed_path,
                "selected_noise": noise_path,
                "scope": missed_scope,
                "missed_rank": miss.get("rank"),
                "noise_rank": noise.get("rank"),
                "missed_score": miss.get("score"),
                "noise_score": noise.get("score"),
                "missed_tokens": missed_tokens,
                "noise_tokens": noise_tokens,
                "token_delta": missed_tokens - noise_tokens,
                "missed_evidence": round(missed_evidence, 1),
                "noise_evidence": round(noise_evidence, 1),
                "evidence_gain": round(evidence_gain, 1),
                "missed_reasons": missed_reasons[:4],
                "noise_reasons": noise_reasons[:4],
            })

    return sorted(
        rows,
        key=lambda row: (
            -float(row["evidence_gain"]),
            int(row["token_delta"]),
            int(row["missed_rank"] or 999999),
            int(row["noise_rank"] or 999999),
        ),
    )[:limit]


def _plausibly_useful_selected_noise(
    *,
    selected_noise: list[dict[str, Any]],
    expected_set: set[str],
    scored_map: dict[str, dict[str, Any]],
    limit: int = 20,
) -> list[dict[str, Any]]:
    expected_scopes = {_diagnostic_scope(path) for path in expected_set}
    expected_packages = {_workspace_package(path) for path in expected_set}
    expected_families = {_path_family(path) for path in expected_set}
    rows: list[dict[str, Any]] = []
    for noise in selected_noise:
        path = str(noise.get("path") or "")
        if not path:
            continue
        scope = _diagnostic_scope(path)
        package = _workspace_package(path)
        family = _path_family(path)
        reasons: list[str] = []
        if any(_diagnostic_related_scope(scope, expected_scope) for expected_scope in expected_scopes):
            reasons.append("same_or_related_scope_as_expected")
        if package and package in expected_packages:
            reasons.append("same_workspace_package_as_expected")
        if family in expected_families and _cap_has_strong_evidence(list(noise.get("reasons") or [])):
            reasons.append("same_family_with_strong_evidence")
        if not reasons:
            continue
        scored_info = scored_map.get(path) or {}
        rows.append({
            "path": path,
            "family": family,
            "scope": scope,
            "workspace_package": package,
            "rank": noise.get("rank"),
            "score": noise.get("score"),
            "tokens": noise.get("tokens"),
            "plausibility_reasons": reasons,
            "selection_reasons": list(noise.get("reasons") or scored_info.get("reasons") or [])[:4],
        })
    return sorted(
        rows,
        key=lambda row: (
            int(row["rank"] or 999999),
            -float(row["score"] or 0.0),
            str(row["path"]),
        ),
    )[:limit]


def _label_audit_summary(
    *,
    selected_noise: list[dict[str, Any]],
    plausibly_useful: list[dict[str, Any]],
    packed_tokens: int,
) -> dict[str, Any]:
    noise_tokens = sum(int(row.get("tokens") or 0) for row in selected_noise)
    plausible_tokens = sum(int(row.get("tokens") or 0) for row in plausibly_useful)
    audited_noise_tokens = max(0, noise_tokens - plausible_tokens)
    adjusted_token_precision = None
    if packed_tokens > 0:
        adjusted_token_precision = 1 - (audited_noise_tokens / packed_tokens)
    return {
        "selected_noise_count": len(selected_noise),
        "selected_noise_tokens": noise_tokens,
        "plausibly_useful_count": len(plausibly_useful),
        "plausibly_useful_tokens": plausible_tokens,
        "audited_noise_tokens": audited_noise_tokens,
        "adjusted_token_precision": round(adjusted_token_precision, 3)
        if adjusted_token_precision is not None else None,
    }


def _owner_file_recall(*, selected_set: set[str], expected_set: set[str]) -> dict[str, Any]:
    if not expected_set:
        return {"owner_files": [], "selected": 0, "total": 0, "recall": None}
    owner_priority = min(_owner_priority(path) for path in expected_set)
    owner_files = sorted(path for path in expected_set if _owner_priority(path) == owner_priority)
    selected = sum(1 for path in owner_files if path in selected_set)
    return {
        "owner_files": owner_files,
        "selected": selected,
        "total": len(owner_files),
        "recall": round(selected / len(owner_files), 3) if owner_files else None,
        "owner_family": _path_family(owner_files[0]) if owner_files else None,
    }


def _owner_priority(path: str) -> int:
    family = _path_family(path)
    if family == "source":
        return 0
    if family == "config":
        return 1
    if family == "test":
        return 2
    if family == "docs":
        return 3
    return 4


def _expected_family_recall(*, selected_set: set[str], expected_set: set[str]) -> dict[str, dict[str, float]]:
    buckets: dict[str, dict[str, float]] = {}
    for path in expected_set:
        family = _path_family(path)
        bucket = buckets.setdefault(family, {"selected": 0.0, "expected": 0.0, "recall": 0.0})
        bucket["expected"] += 1
        if path in selected_set:
            bucket["selected"] += 1
    for bucket in buckets.values():
        expected = bucket["expected"]
        bucket["recall"] = round(bucket["selected"] / expected, 3) if expected else 0.0
    return dict(sorted(buckets.items()))


def _expected_include_mode_diagnostics(
    *,
    expected_set: set[str],
    selected_modes: dict[str, str],
) -> dict[str, Any]:
    selected_expected = sorted(path for path in expected_set if path in selected_modes)
    mode_counts: dict[str, int] = {}
    by_family: dict[str, dict[str, int]] = {}
    for path in selected_expected:
        mode = selected_modes.get(path, "missing")
        family = _path_family(path)
        mode_counts[mode] = mode_counts.get(mode, 0) + 1
        family_counts = by_family.setdefault(family, {})
        family_counts[mode] = family_counts.get(mode, 0) + 1
    summary_only = sum(1 for path in selected_expected if selected_modes.get(path) == "summary")
    return {
        "selected_expected_count": len(selected_expected),
        "expected_count": len(expected_set),
        "mode_counts": dict(sorted(mode_counts.items())),
        "by_family": {family: dict(sorted(counts.items())) for family, counts in sorted(by_family.items())},
        "source_code_block_rate": _family_actionable_mode_rate(
            expected_set=expected_set,
            selected_modes=selected_modes,
            family="source",
        ),
        "test_code_block_rate": _family_actionable_mode_rate(
            expected_set=expected_set,
            selected_modes=selected_modes,
            family="test",
        ),
        "summary_only_expected_rate": round(summary_only / len(selected_expected), 3) if selected_expected else None,
    }


def _family_actionable_mode_rate(
    *,
    expected_set: set[str],
    selected_modes: dict[str, str],
    family: str,
) -> float | None:
    paths = [path for path in expected_set if _path_family(path) == family]
    if not paths:
        return None
    actionable_modes = {"full", "diff", "symbols", "skeleton"}
    selected_actionable = sum(1 for path in paths if selected_modes.get(path) in actionable_modes)
    return round(selected_actionable / len(paths), 3)


def _expected_rank_distribution(
    expected_set: set[str],
    scored_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    ranks = sorted(int(scored_map[path]["rank"]) for path in expected_set if path in scored_map and scored_map[path].get("rank"))
    if not ranks:
        return {
            "ranked_expected_count": 0,
            "unranked_expected_count": len(expected_set),
            "median": None,
            "p90": None,
            "min": None,
            "max": None,
            "buckets": {},
        }
    return {
        "ranked_expected_count": len(ranks),
        "unranked_expected_count": len(expected_set) - len(ranks),
        "median": _percentile_rank(ranks, 0.5),
        "p90": _percentile_rank(ranks, 0.9),
        "min": ranks[0],
        "max": ranks[-1],
        "buckets": {
            "1_3": sum(1 for rank in ranks if rank <= 3),
            "4_8": sum(1 for rank in ranks if 4 <= rank <= 8),
            "9_20": sum(1 for rank in ranks if 9 <= rank <= 20),
            "21_plus": sum(1 for rank in ranks if rank >= 21),
        },
    }


def _percentile_rank(sorted_ranks: list[int], percentile: float) -> int:
    if not sorted_ranks:
        return 0
    index = min(len(sorted_ranks) - 1, max(0, int(round((len(sorted_ranks) - 1) * percentile))))
    return sorted_ranks[index]


def _package_boundary_diagnostics(
    *,
    selected_paths: list[str],
    expected_set: set[str],
) -> dict[str, Any]:
    expected_packages = {_workspace_package(path) for path in expected_set if _workspace_package(path)}
    selected_packages = [_workspace_package(path) for path in selected_paths if _workspace_package(path)]
    selected_expected_package = sum(1 for package in selected_packages if package in expected_packages)
    selected_cross_package = len(selected_packages) - selected_expected_package
    return {
        "expected_packages": sorted(expected_packages),
        "selected_expected_package_files": selected_expected_package,
        "selected_cross_package_files": selected_cross_package,
        "selected_package_match_rate": round(selected_expected_package / len(selected_packages), 3)
        if selected_packages else None,
    }


def _workspace_package(path: str) -> str:
    normalized = path.lower().replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    if not parts:
        return ""
    if "packages" in parts:
        index = parts.index("packages")
        if len(parts) > index + 1:
            return "/".join(parts[:index + 2])
    if "apps" in parts:
        index = parts.index("apps")
        if len(parts) > index + 1:
            return "/".join(parts[:index + 2])
    if parts[0] in {"integration", "examples", "playground"} and len(parts) > 1:
        return "/".join(parts[:2])
    if parts[0] in {"src", "lib", "app", "tests", "test"}:
        return parts[0]
    return parts[0]


def _diagnostic_replacement_status(status: str) -> bool:
    lowered = status.lower()
    return any(term in lowered for term in ("budget", "cap reached", "compressed", "summarized", "stronger support"))


def _diagnostic_scope(path: str) -> str:
    normalized = path.lower().replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    if not parts:
        return ""
    for marker in ("src", "lib", "app", "packages", "tests", "test", "integration"):
        if marker not in parts:
            continue
        index = parts.index(marker)
        if marker == "packages" and len(parts) > index + 2:
            return "/".join(parts[:index + 3])
        tail = parts[index + 1:-1]
        depth = 2 if marker in {"src", "lib", "app"} else 1
        return "/".join(parts[:index + 1] + tail[:depth])
    if len(parts) > 2:
        return "/".join(parts[:2])
    return parts[0]


def _diagnostic_related_scope(left: str, right: str) -> bool:
    if left == right:
        return True
    if not left or not right:
        return False
    return left.startswith(f"{right}/") or right.startswith(f"{left}/")


def _diagnostic_evidence_score(*, path: str, score: float, reasons: list[str]) -> float:
    evidence = min(max(score, 0.0), 300.0) * 0.25
    for reason in reasons:
        lowered = reason.lower()
        content_match = re.match(r"content keyword match \((\d+)\)", lowered)
        if content_match:
            evidence += min(int(content_match.group(1)), 6) * 18
        if reason.startswith(_CAP_STRONG_REASON_PREFIXES):
            evidence += 55
        elif lowered.startswith(("filename keyword match", "symbol keyword match")):
            evidence += 12
        elif lowered.startswith(("recently modified", "high churn")):
            evidence += 5
    if _path_family(path) in {"examples", "fixtures", "generated", "docs"}:
        evidence -= 25
    return evidence


def _replaceable_selected_noise(
    *,
    selected_by_path: dict[str, Any],
    selected_tokens: dict[str, int],
    expected_set: set[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path, sf in selected_by_path.items():
        if path in expected_set:
            continue
        mode = getattr(sf, "include_mode", "")
        reasons = list(getattr(sf, "reasons", []) or [])
        if mode not in {"summary", "skeleton"}:
            continue
        if _cap_has_strong_evidence(reasons):
            continue
        rows.append({
            "path": path,
            "tokens": selected_tokens.get(path, 0),
            "mode": mode,
            "score": round(float(getattr(sf, "score", 0.0) or 0.0), 1),
            "reasons": reasons[:4],
        })
    return sorted(rows, key=lambda row: (row["score"], -row["tokens"]))


def _path_family(path: str) -> str:
    normalized = path.lower().replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    name = parts[-1] if parts else normalized
    suffix = Path(name).suffix

    if any(part in {"docs", "doc"} for part in parts) or name.startswith("readme") or suffix in {".md", ".mdx", ".rst"}:
        return "docs"
    if any(part in {"fixtures", "fixture", "__fixtures__", "snapshots", "__snapshots__"} for part in parts):
        return "fixtures"
    if any(part in {"examples", "example", "playground", "playgrounds", "samples", "sample", "templates", "template"} for part in parts):
        return "examples"
    if any(part in {"test", "tests", "__tests__", "spec", "specs", "e2e", "integration"} for part in parts):
        return "test"
    if any(part in {"dist", "build", "generated", "__generated__", "coverage"} for part in parts):
        return "generated"
    if name.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx", "_test.go", "_test.py")):
        return "test"
    if name in {
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "pyproject.toml",
        "go.mod",
        "go.sum",
        "pom.xml",
        "build.gradle",
        "gradle.properties",
    } or suffix in {".toml", ".yaml", ".yml", ".json", ".ini", ".cfg"}:
        return "config"
    if suffix in {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".kt", ".rs", ".rb", ".php", ".cs"}:
        return "source"
    return "other"


def _selected_family_tokens(paths: list[str], selected_tokens: dict[str, int]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for path in paths:
        family = _path_family(path)
        totals[family] = totals.get(family, 0) + selected_tokens.get(path, 0)
    return dict(sorted(totals.items()))


def _reason_family(reason: str) -> str:
    reason = reason.lower()
    if reason.startswith("filename keyword match") or "matched naming keyword" in reason:
        return "filename"
    if reason.startswith("symbol keyword match") or reason.startswith("matched define"):
        return "symbol"
    if (
        reason.startswith("content keyword match")
        or reason.startswith("keyword phrase match")
        or reason.startswith("quoted literal match")
    ):
        return "content"
    if reason.startswith(("matched call", "matched entrypoint", "matched domain", "matched external system")):
        return "semantic"
    if reason.startswith(("direct dependency", "reverse dependency", "has related tests", "test for")):
        return "graph"
    if reason.startswith(("recently modified", "historically co-changed", "high churn")):
        return "history"
    if reason.startswith(("config file", "release/version metadata", "knowledge/architecture doc")):
        return "metadata"
    if reason.startswith(("matched role keyword", "matched ranking keyword")):
        return "summary"
    return "other"


def _reason_family_precision(selected: list[Any], expected_files: set[str]) -> dict[str, dict[str, float]]:
    counts: dict[str, dict[str, int]] = {}
    for sf in selected:
        path = str(getattr(sf, "path", ""))
        families = {_reason_family(reason) for reason in (getattr(sf, "reasons", None) or [])}
        for family in families:
            bucket = counts.setdefault(family, {"selected": 0, "expected": 0})
            bucket["selected"] += 1
            if path in expected_files:
                bucket["expected"] += 1

    result: dict[str, dict[str, float]] = {}
    for family, bucket in sorted(counts.items()):
        selected_count = bucket["selected"]
        expected_count = bucket["expected"]
        result[family] = {
            "selected": float(selected_count),
            "expected": float(expected_count),
            "precision": expected_count / selected_count if selected_count else 0.0,
        }
    return result


def _miss_failure_type(
    *,
    fi: Any,
    scored_info: dict[str, Any] | None,
    status: str,
    selected_count: int,
) -> str:
    if fi is None:
        return "EXPECTED_NOT_FOUND"
    if scored_info is None:
        return "EXPECTED_NOT_SCORED"
    rank = int(scored_info.get("rank") or 0)
    score = float(scored_info.get("score") or 0.0)
    if score <= 0 or rank > max(50, selected_count * 4):
        return "EXPECTED_RANKED_LOW"
    lowered = status.lower()
    if any(term in lowered for term in ("budget", "cap reached", "stronger support", "score below", "summarized", "compressed")):
        return "EXPECTED_SKIPPED"
    return "NOISE_SELECTED_ABOVE_EXPECTED"


def _low_budget_extra_file_waste(
    *,
    selected: list[Any],
    selected_tokens: dict[str, int],
    expected_files: set[str],
    packed_tokens: int,
    expected_tokens: int,
    budget: int,
    changed_files_source: str,
) -> tuple[int | None, float | None]:
    if budget > 2500 or not changed_files_source.startswith("no live changes"):
        return None, None
    last_summary = next((sf for sf in reversed(selected) if getattr(sf, "include_mode", "") == "summary"), None)
    if last_summary is None:
        return None, None
    last_path = str(getattr(last_summary, "path", ""))
    last_tokens = selected_tokens.get(last_path, 0)
    if last_tokens <= 0 or packed_tokens <= last_tokens:
        return None, None
    current_precision = expected_tokens / packed_tokens if packed_tokens else 0.0
    expected_without = expected_tokens - (last_tokens if last_path in expected_files else 0)
    precision_without = expected_without / (packed_tokens - last_tokens)
    waste = 0 if last_path in expected_files else last_tokens
    return waste, precision_without - current_precision


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


def _route_skills_for_case(root: Path, case: BenchmarkCase) -> tuple[list[str], int]:
    if not case.expected_skills and not case.avoid_skills:
        return [], 0
    from agentpack.router.service import RouteService

    service = RouteService()
    route = service.route_task(root, case.task)
    selected = [item.skill.name for item in route.selected_skills[:3]]
    selected_keys = {_normalize_skill_name(name) for name in selected}
    token_cost = 0
    inventory = service.inventory(root)
    for skill in inventory.skills:
        keys = {
            _normalize_skill_name(skill.name),
            _normalize_skill_name(skill.path),
            _normalize_skill_name(str(Path(skill.path).parent)),
        }
        if selected_keys & keys:
            token_cost += estimate_tokens(skill.raw_text or skill.description or skill.name)
    return selected, token_cost


def _skill_metrics(
    selected_skills: list[str],
    *,
    expected_skills: list[str],
    avoid_skills: list[str],
) -> tuple[float | None, float | None, float | None, float | None]:
    selected = [_normalize_skill_name(skill) for skill in selected_skills[:3]]
    expected = {_normalize_skill_name(skill) for skill in expected_skills}
    avoided = {_normalize_skill_name(skill) for skill in avoid_skills}
    selected_set = set(selected)

    recall = len(selected_set & expected) / len(expected) if expected else None
    precision = len(selected_set & expected) / len(selected) if expected and selected else (0.0 if expected else None)
    mrr = None
    if expected:
        for idx, skill in enumerate(selected, start=1):
            if skill in expected:
                mrr = 1 / idx
                break
        if mrr is None:
            mrr = 0.0
    noise = len(selected_set & avoided) / len(selected) if avoided and selected else (0.0 if avoided else None)
    return recall, precision, mrr, noise


def _normalize_skill_name(value: str) -> str:
    normalized = value.strip().lower().replace("\\", "/").rstrip("/")
    if normalized.endswith("/skill.md"):
        normalized = normalized[: -len("/skill.md")]
    return normalized


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


def _result_record(result: CaseResult) -> dict[str, Any]:
    p, r, f1 = _precision_recall(result) if result.case.expected_files else (None, None, None)
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "task": result.case.task,
        "task_type": result.case.task_type,
        "workspace": result.case.workspace,
        "mode": result.case.mode,
        "budget": result.case.budget,
        "expected_files": result.case.expected_files,
        "selected_paths": result.selected_paths,
        "selected_tokens": result.selected_tokens,
        "selected_modes": result.selected_modes,
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
        "candidate_recall_at_20": round(result.candidate_recall_at_20, 3)
        if result.candidate_recall_at_20 is not None else None,
        "candidate_recall_at_50": round(result.candidate_recall_at_50, 3)
        if result.candidate_recall_at_50 is not None else None,
        "candidate_recall_at_100": round(result.candidate_recall_at_100, 3)
        if result.candidate_recall_at_100 is not None else None,
        "candidate_precision_at_3": round(result.candidate_precision_at_3, 3)
        if result.candidate_precision_at_3 is not None else None,
        "candidate_precision_at_5": round(result.candidate_precision_at_5, 3)
        if result.candidate_precision_at_5 is not None else None,
        "low_budget_extra_file_waste": result.low_budget_extra_file_waste,
        "precision_delta_if_drop_last_summary": round(result.precision_delta_if_drop_last_summary, 3)
        if result.precision_delta_if_drop_last_summary is not None else None,
        "expected_token_coverage": round(result.expected_token_coverage, 3)
        if result.expected_token_coverage is not None else None,
        "selected_family_tokens": result.selected_family_tokens,
        "selected_family_waste_tokens": result.selected_family_waste_tokens,
        "reason_family_precision": result.reason_family_precision,
        "failure_type_counts": result.failure_type_counts,
        "noise_pct": round(result.noise_pct, 1) if result.noise_pct is not None else None,
        "token_precision": round(1 - (result.noise_pct / 100), 3) if result.noise_pct is not None else None,
        "random_f1": round(result.random_f1, 3) if result.random_f1 is not None else None,
        "selected_skills": result.selected_skills,
        "skill_recall_at_3": round(result.skill_recall_at_3, 3) if result.skill_recall_at_3 is not None else None,
        "skill_precision_at_3": round(result.skill_precision_at_3, 3) if result.skill_precision_at_3 is not None else None,
        "skill_mrr": round(result.skill_mrr, 3) if result.skill_mrr is not None else None,
        "skill_noise_rate": round(result.skill_noise_rate, 3) if result.skill_noise_rate is not None else None,
        "skill_token_cost": result.skill_token_cost,
        "misses": result.missed_expected,
        "top_candidates": result.top_candidates,
        "selection_diagnostics": result.selection_diagnostics,
    }


def _persist_result(root: Path, result: CaseResult) -> None:
    out = root / ".agentpack" / "benchmark_results.jsonl"
    record = _result_record(result)
    try:
        with out.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:
        pass


def _write_results_jsonl(path: Path, results: list[CaseResult]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for result in results:
            fh.write(json.dumps(_result_record(result), sort_keys=True) + "\n")
    return path


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
        if result.candidate_recall_at_20 is not None:
            console.print(
                "  candidate recall "
                f"@20 [bold]{result.candidate_recall_at_20:.1%}[/]  "
                f"@50 [bold]{result.candidate_recall_at_50:.1%}[/]  "
                f"@100 [bold]{result.candidate_recall_at_100:.1%}[/]"
            )
        if result.candidate_precision_at_3 is not None:
            console.print(
                "  candidate precision "
                f"@3 [bold]{result.candidate_precision_at_3:.1%}[/]  "
                f"@5 [bold]{result.candidate_precision_at_5:.1%}[/]"
            )
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

    if result.case.expected_skills or result.case.avoid_skills:
        mrr_text = f"{result.skill_mrr:.2f}" if result.skill_mrr is not None else "-"
        console.print(
            "  skill recall@3 "
            f"[bold]{_fmt_pct(result.skill_recall_at_3)}[/]  "
            "precision@3 "
            f"[bold]{_fmt_pct(result.skill_precision_at_3)}[/]  "
            f"MRR [bold]{mrr_text}[/]"
        )
        if result.skill_noise_rate is not None:
            console.print(f"  skill noise [bold]{result.skill_noise_rate:.1%}[/]")
        console.print(f"  skill token cost [bold]{result.skill_token_cost:,}[/]")
        if result.selected_skills:
            console.print("  [dim]top skills:[/] " + ", ".join(result.selected_skills[:3]))

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
    has_skill_gt = any(r.case.expected_skills or r.case.avoid_skills for r in results)

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
        tbl.add_column("cand R@50", justify="right")
        tbl.add_column("cand P@3", justify="right")
        tbl.add_column("rank@K", justify="right")
        tbl.add_column("noise%", justify="right")
    if has_skill_gt:
        tbl.add_column("skill R@3", justify="right")
        tbl.add_column("skill P@3", justify="right")
        tbl.add_column("skill MRR", justify="right")
        tbl.add_column("skill noise", justify="right")

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
                f"{r.candidate_recall_at_50:.1%}" if r.candidate_recall_at_50 is not None else "—",
                f"{r.candidate_precision_at_3:.1%}" if r.candidate_precision_at_3 is not None else "—",
                str(r.rank_at_k) if r.rank_at_k is not None else "—",
                f"{r.noise_pct:.0f}%" if r.noise_pct is not None else "—",
            ]
        if has_skill_gt:
            row += [
                _fmt_pct(r.skill_recall_at_3) if r.case.expected_skills else "—",
                _fmt_pct(r.skill_precision_at_3) if r.case.expected_skills else "—",
                f"{r.skill_mrr:.2f}" if r.skill_mrr is not None else "—",
                _fmt_pct(r.skill_noise_rate) if r.case.avoid_skills else "—",
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
    tbl.add_column("avg cand R@50", justify="right")
    tbl.add_column("avg cand P@3", justify="right")
    tbl.add_column("avg noise", justify="right")
    tbl.add_column("last waste", justify="right")
    tbl.add_column("drop-last Δ", justify="right")

    for task_type, rows in sorted(grouped.items()):
        metrics = [_precision_recall(row) for row in rows]
        avg_p = sum(item[0] for item in metrics) / len(metrics)
        avg_r = sum(item[1] for item in metrics) / len(metrics)
        avg_f1 = sum(item[2] for item in metrics) / len(metrics)
        candidate_recall_values = [
            row.candidate_recall_at_50 for row in rows if row.candidate_recall_at_50 is not None
        ]
        avg_candidate_recall = (
            sum(candidate_recall_values) / len(candidate_recall_values)
            if candidate_recall_values else None
        )
        candidate_precision_values = [
            row.candidate_precision_at_3 for row in rows if row.candidate_precision_at_3 is not None
        ]
        avg_candidate_precision = (
            sum(candidate_precision_values) / len(candidate_precision_values)
            if candidate_precision_values else None
        )
        noise_values = [row.noise_pct for row in rows if row.noise_pct is not None]
        avg_noise = sum(noise_values) / len(noise_values) if noise_values else None
        avg_last_waste, avg_drop_last_delta, waste_cases = _low_budget_waste_summary(rows)
        tbl.add_row(
            task_type,
            str(len(rows)),
            f"{avg_p:.1%}",
            f"{avg_r:.1%}",
            f"{avg_f1:.1%}",
            f"{avg_candidate_recall:.1%}" if avg_candidate_recall is not None else "-",
            f"{avg_candidate_precision:.1%}" if avg_candidate_precision is not None else "-",
            f"{avg_noise:.0f}%" if avg_noise is not None else "-",
            f"{avg_last_waste:.0f}t/{waste_cases}" if waste_cases else "-",
            f"{avg_drop_last_delta:+.1%}" if waste_cases else "-",
        )

    console.print("\n[bold]By Task Type[/]")
    console.print(tbl)


def _low_budget_waste_summary(rows: list[CaseResult]) -> tuple[float, float, int]:
    values = [
        (row.low_budget_extra_file_waste, row.precision_delta_if_drop_last_summary)
        for row in rows
        if row.low_budget_extra_file_waste is not None
        and row.precision_delta_if_drop_last_summary is not None
    ]
    if not values:
        return 0.0, 0.0, 0
    avg_waste = sum(waste for waste, _delta in values) / len(values)
    avg_delta = sum(delta for _waste, delta in values) / len(values)
    return avg_waste, avg_delta, len(values)


def _print_precision_diagnostics(results: list[CaseResult]) -> None:
    scored = [result for result in results if result.case.expected_files]
    if not scored:
        return

    failure_counts: dict[str, int] = {}
    family_waste: dict[str, int] = {}
    reason_counts: dict[str, dict[str, float]] = {}
    coverage_values: list[float] = []
    label_audit_cases = 0
    label_audit_plausible_tokens = 0
    label_audit_noise_tokens = 0
    adjusted_precision_values: list[float] = []

    for result in scored:
        for failure_type, count in result.failure_type_counts.items():
            failure_counts[failure_type] = failure_counts.get(failure_type, 0) + count
        for family, tokens in result.selected_family_waste_tokens.items():
            family_waste[family] = family_waste.get(family, 0) + tokens
        for family, stats in result.reason_family_precision.items():
            bucket = reason_counts.setdefault(family, {"selected": 0.0, "expected": 0.0})
            bucket["selected"] += stats.get("selected", 0.0)
            bucket["expected"] += stats.get("expected", 0.0)
        if result.expected_token_coverage is not None:
            coverage_values.append(result.expected_token_coverage)
        label_audit = result.selection_diagnostics.get("label_audit")
        if isinstance(label_audit, dict):
            plausible_tokens = int(label_audit.get("plausibly_useful_tokens") or 0)
            noise_tokens = int(label_audit.get("selected_noise_tokens") or 0)
            adjusted_precision = label_audit.get("adjusted_token_precision")
            if plausible_tokens > 0:
                label_audit_cases += 1
                label_audit_plausible_tokens += plausible_tokens
                label_audit_noise_tokens += noise_tokens
            if isinstance(adjusted_precision, (int, float)):
                adjusted_precision_values.append(float(adjusted_precision))

    tbl = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
    tbl.add_column("diagnostic", max_width=30)
    tbl.add_column("value", justify="right")
    tbl.add_column("note", max_width=48)

    avg_coverage = sum(coverage_values) / len(coverage_values) if coverage_values else None
    tbl.add_row(
        "expected token coverage",
        f"{avg_coverage:.1%}" if avg_coverage is not None else "-",
        "selected expected tokens / estimated expected-file tokens",
    )

    for failure_type, count in sorted(failure_counts.items(), key=lambda item: (-item[1], item[0])):
        tbl.add_row(f"miss {failure_type.lower()}", str(count), "primary funnel stage for missed expected files")

    for family, tokens in sorted(family_waste.items(), key=lambda item: (-item[1], item[0]))[:6]:
        if tokens > 0:
            tbl.add_row(f"{family} waste", f"{tokens:,}t", "selected tokens outside expected files")

    if label_audit_plausible_tokens > 0:
        avg_adjusted_precision = (
            sum(adjusted_precision_values) / len(adjusted_precision_values)
            if adjusted_precision_values else None
        )
        tbl.add_row(
            "label-audit plausible noise",
            f"{label_audit_plausible_tokens:,}t/{label_audit_cases}",
            "non-expected selected tokens with same-scope/package/family evidence",
        )
        tbl.add_row(
            "label-audit adjusted TP",
            f"{avg_adjusted_precision:.1%}" if avg_adjusted_precision is not None else "-",
            "diagnostic only; treats plausible unlabeled context as useful",
        )

    for family, stats in sorted(reason_counts.items()):
        selected = stats.get("selected", 0.0)
        expected = stats.get("expected", 0.0)
        if selected <= 0:
            continue
        precision = expected / selected
        if selected >= 2:
            tbl.add_row(
                f"reason {family}",
                f"{precision:.1%}",
                f"{int(expected)}/{int(selected)} selected files with this signal were expected",
            )

    console.print("\n[bold]Precision Diagnostics[/]")
    console.print(tbl)


def _fmt_pct(value: float | None) -> str:
    return f"{value:.1%}" if value is not None else "-"


def _print_miss_details(results: list[CaseResult]) -> None:
    rows = [miss | {"task": result.case.task[:30]} for result in results for miss in result.missed_expected]
    if not rows:
        return

    tbl = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
    tbl.add_column("task", max_width=30)
    tbl.add_column("missed file", max_width=42)
    tbl.add_column("failure", max_width=24)
    tbl.add_column("status", max_width=24)
    tbl.add_column("rank", justify="right")
    tbl.add_column("score", justify="right")
    tbl.add_column("why", max_width=40)

    for row in rows:
        tbl.add_row(
            row["task"],
            row["path"],
            row.get("failure_type", "-"),
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
    tbl.add_column("cand R@50", justify="right")
    tbl.add_column("cand P@3", justify="right")
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
            f"{result.candidate_recall_at_50:.0%}" if result.candidate_recall_at_50 is not None else "-",
            f"{result.candidate_precision_at_3:.0%}" if result.candidate_precision_at_3 is not None else "-",
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
    mode: str = typer.Option("balanced", "--mode", help=f"Benchmark mode ({MODE_HELP})."),
    workspace: str = typer.Option("", "--workspace", help="Optional workspace."),
    allow_empty: bool = typer.Option(False, "--allow-empty", help="Allow appending a case with no expected files."),
    anonymous_report: bool = typer.Option(False, "--anonymous-report", help="Write shareable benchmark-report files without source code."),
) -> None:
    """Append a benchmark case from git diff expected files."""
    if not is_requested_mode(mode):
        console.print(f"[red]{invalid_mode_message(mode)}[/]")
        raise typer.Exit(1)
    root = _root()
    expected = sorted(git.changed_files_since(root, since))
    if not expected and not allow_empty:
        console.print(f"[yellow]No files changed since {since}. Use --allow-empty to append anyway.[/]")
        raise typer.Exit(1)
    case = BenchmarkCase(task=task.strip(), mode=normalize_mode(mode), expected_files=expected, workspace=workspace or None)
    out = _append_benchmark_cases(root, [case])
    console.print(f"[green]✓[/] Appended benchmark case to [bold]{out}[/]")
    console.print(f"  expected_files: {len(expected)}")
    if anonymous_report:
        report_md, report_json = _write_anonymous_benchmark_report(root)
        console.print(f"[green]✓[/] Wrote anonymous report: [bold]{report_md}[/]")
        console.print(f"[green]✓[/] Wrote anonymous report data: [bold]{report_json}[/]")


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


@benchmark_app.command("e2e-init")
def benchmark_e2e_init(
    output: str = typer.Option("", "--output", help="Output TOML path. Default: .agentpack/e2e_cases.toml."),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing file."),
) -> None:
    """Scaffold a guarded E2E benchmark suite for real coding agents."""
    root = _root()
    out_path = Path(output) if output else root / ".agentpack" / "e2e_cases.toml"
    if not out_path.is_absolute():
        out_path = root / out_path
    if out_path.exists() and not force:
        console.print(f"[yellow]E2E cases file already exists:[/] {out_path}")
        console.print("  Pass [bold]--force[/] to overwrite.")
        raise typer.Exit(1)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_e2e_cases_template(root), encoding="utf-8")
    console.print(f"[green]✓[/] Created [bold]{out_path}[/]")
    console.print("  Fill in setup/test commands, then run [bold]agentpack benchmark e2e[/].")


def _e2e_cases_template(root: Path) -> str:
    repo = json.dumps(str(root))
    categories = [
        ("caller_signature_change", "Function signature or behavior change requiring caller updates."),
        ("api_service_model_contract", "API route, service, serializer, and model contract change."),
        ("config_env_runtime", "Bug depends on config/env/default behavior."),
        ("deleted_or_renamed_file", "Snapshot or reference logic must handle deleted/renamed files."),
        ("omitted_related_test", "Related test is not obvious from the primary source file."),
        ("cross_package_monorepo", "Change spans workspace/package boundaries."),
        ("side_effect_eventing", "Fix needs awareness of emitted events, analytics, or side effects."),
        ("schema_migration_contract", "Schema/model/migration contract impacts runtime behavior."),
        ("generated_file_noise", "Generated or ignored files should not steer the fix."),
        ("broad_task_precision", "Broad task wording where noisy context hurts precision."),
    ]
    lines = [
        "# AgentPack guarded E2E benchmark cases",
        "#",
        "# Each case should protect validation tests from edits and name expected source files.",
        "# Run at least 3 trials across no-context, grep, agentpack-lite, hybrid, and agentpack.",
        "# Example:",
        "#   agentpack benchmark e2e --cases .agentpack/e2e_cases.toml \\",
        "#     --agent-command 'bash -lc \"codex exec --dangerously-bypass-approvals-and-sandbox --cd {repo} --skip-git-repo-check \\\"$(cat {prompt})\\\"\"' \\",
        "#     --strategies no-context,grep,agentpack-lite,hybrid,agentpack --trials 3",
        "",
    ]
    for name, description in categories:
        lines.extend([
            "# [[cases]]",
            f"# name = \"{name}\"",
            f"# repo = {repo}",
            f"# task = \"{description}\"",
            f"# setup_command = \"python /absolute/path/to/setup_{name}.py\"",
            "# test_command = \"PYTHONPATH=src pytest -q tests/path/to_targeted_test.py\"",
            "# protected_paths = [\"tests/path/to_targeted_test.py\"]",
            "# expected_edit_paths = [\"src/path/to_expected_source.py\"]",
            "",
        ])
    return "\n".join(lines)


@benchmark_app.command("e2e")
def benchmark_e2e(
    cases: str = typer.Option(..., "--cases", help="TOML file with [[cases]] entries."),
    agent_command: str = typer.Option(..., "--agent-command", help="Agent command. Use {prompt} and {repo} placeholders, or prompt path is appended."),
    strategies: str = typer.Option("no-context,grep,agentpack-lite,hybrid,agentpack", "--strategies", help="Comma-separated: no-context,grep,agentpack-lite,hybrid,agentpack."),
    trials: int = typer.Option(1, "--trials", help="Runs per case per strategy."),
    timeout: int = typer.Option(300, "--timeout", help="Agent command timeout seconds."),
    input_cost_per_mtok: float = typer.Option(0.0, "--input-cost-per-mtok", help="Optional input token price in USD per 1M tokens."),
    output_cost_per_mtok: float = typer.Option(0.0, "--output-cost-per-mtok", help="Optional output token price in USD per 1M tokens."),
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
                    input_cost_per_mtok=input_cost_per_mtok,
                    output_cost_per_mtok=output_cost_per_mtok,
                    keep_workdir=keep_workdirs,
                )
                results.append(result)
                with out_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(result.__dict__) + "\n")

    _print_e2e_summary(results, out_path)


@benchmark_app.command("e2e-report")
def benchmark_e2e_report(
    results: str = typer.Option("", "--results", help="JSONL output from `agentpack benchmark e2e`. Default: .agentpack/e2e_results.jsonl."),
    baseline: str = typer.Option("no-context", "--baseline", help="Baseline strategy, usually no-context."),
    treatment: str = typer.Option("agentpack", "--treatment", help="Treatment strategy, usually agentpack."),
    markdown: bool = typer.Option(False, "--markdown", help="Print a Markdown report instead of a console table."),
) -> None:
    """Compare AgentPack vs no-AgentPack E2E benchmark runs."""
    root = _root()
    path = Path(results) if results else root / ".agentpack" / "e2e_results.jsonl"
    if not path.is_absolute():
        path = root / path
    records = _load_e2e_result_records(path)
    if not records:
        console.print(f"[yellow]No E2E results found at {path}[/]")
        raise typer.Exit(1)
    if markdown:
        console.print(_e2e_ab_markdown(records, baseline=baseline, treatment=treatment, source=path))
        return
    _print_e2e_ab_table(records, baseline=baseline, treatment=treatment, source=path)


def _load_e2e_result_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _e2e_strategy_metrics(records: list[dict[str, Any]], strategy: str) -> dict[str, float]:
    subset = [row for row in records if row.get("strategy") == strategy]
    if not subset:
        return {"runs": 0.0}

    def avg(key: str) -> float:
        return sum(float(row.get(key) or 0.0) for row in subset) / len(subset)

    first_file_values = [
        float(row["time_to_first_expected_file_s"])
        for row in subset
        if row.get("time_to_first_expected_file_s") is not None
    ]
    expected_rows = [
        row
        for row in subset
        if row.get("expected_files_touched") or row.get("missing_expected_edits")
    ]
    expected_touch_rate = (
        sum(1 for row in expected_rows if row.get("expected_files_touched")) / len(expected_rows)
        if expected_rows
        else 0.0
    )
    return {
        "runs": float(len(subset)),
        "success_rate": sum(1 for row in subset if row.get("passed")) / len(subset),
        "expected_touch_rate": expected_touch_rate,
        "avg_input_tokens": avg("input_tokens"),
        "avg_output_tokens": avg("agent_output_tokens"),
        "avg_total_tokens": avg("input_tokens") + avg("agent_output_tokens"),
        "avg_total_cost_usd": avg("estimated_total_cost_usd"),
        "avg_duration_s": avg("duration_s"),
        "avg_tool_calls": avg("agent_tool_calls"),
        "avg_time_to_first_expected_file_s": (
            sum(first_file_values) / len(first_file_values)
            if first_file_values
            else 0.0
        ),
    }


def _e2e_ab_metrics(records: list[dict[str, Any]], *, baseline: str, treatment: str) -> dict[str, Any]:
    base = _e2e_strategy_metrics(records, baseline)
    treat = _e2e_strategy_metrics(records, treatment)
    if not base.get("runs") or not treat.get("runs"):
        return {"baseline": base, "treatment": treat, "deltas": {}}
    return {
        "baseline": base,
        "treatment": treat,
        "deltas": {
            "success_rate_pp": (treat["success_rate"] - base["success_rate"]) * 100,
            "task_success_saved": treat["success_rate"] - base["success_rate"],
            "tool_calls_saved": base["avg_tool_calls"] - treat["avg_tool_calls"],
            "token_cost_saved_usd": base["avg_total_cost_usd"] - treat["avg_total_cost_usd"],
            "tokens_saved": base["avg_total_tokens"] - treat["avg_total_tokens"],
            "time_to_first_correct_file_saved_s": (
                base["avg_time_to_first_expected_file_s"] - treat["avg_time_to_first_expected_file_s"]
            ),
            "duration_saved_s": base["avg_duration_s"] - treat["avg_duration_s"],
        },
    }


def _print_e2e_ab_table(
    records: list[dict[str, Any]],
    *,
    baseline: str,
    treatment: str,
    source: Path,
) -> None:
    metrics = _e2e_ab_metrics(records, baseline=baseline, treatment=treatment)
    table = Table(title=f"E2E A/B: {baseline} vs {treatment}", box=box.SIMPLE, show_header=True)
    table.add_column("metric")
    table.add_column(baseline, justify="right")
    table.add_column(treatment, justify="right")
    table.add_column("saved / lift", justify="right")
    base = metrics["baseline"]
    treat = metrics["treatment"]
    deltas = metrics["deltas"]
    if not deltas:
        console.print(f"[yellow]Need results for both {baseline} and {treatment} in {source}[/]")
        return
    table.add_row("runs", f"{base['runs']:.0f}", f"{treat['runs']:.0f}", "-")
    table.add_row("task success", f"{base['success_rate']:.0%}", f"{treat['success_rate']:.0%}", f"{deltas['success_rate_pp']:+.1f} pp")
    table.add_row("expected file touched", f"{base['expected_touch_rate']:.0%}", f"{treat['expected_touch_rate']:.0%}", "-")
    table.add_row("tool calls", f"{base['avg_tool_calls']:.1f}", f"{treat['avg_tool_calls']:.1f}", f"{deltas['tool_calls_saved']:+.1f}")
    table.add_row("tokens", f"{base['avg_total_tokens']:,.0f}", f"{treat['avg_total_tokens']:,.0f}", f"{deltas['tokens_saved']:+,.0f}")
    table.add_row("cost", f"${base['avg_total_cost_usd']:.4f}", f"${treat['avg_total_cost_usd']:.4f}", _fmt_signed_usd(deltas["token_cost_saved_usd"]))
    table.add_row("time to first correct file", f"{base['avg_time_to_first_expected_file_s']:.1f}s", f"{treat['avg_time_to_first_expected_file_s']:.1f}s", f"{deltas['time_to_first_correct_file_saved_s']:+.1f}s")
    table.add_row("duration", f"{base['avg_duration_s']:.1f}s", f"{treat['avg_duration_s']:.1f}s", f"{deltas['duration_saved_s']:+.1f}s")
    console.print(table)
    console.print(f"[dim]Source: {source}[/]")


def _e2e_ab_markdown(
    records: list[dict[str, Any]],
    *,
    baseline: str,
    treatment: str,
    source: Path,
) -> str:
    metrics = _e2e_ab_metrics(records, baseline=baseline, treatment=treatment)
    base = metrics["baseline"]
    treat = metrics["treatment"]
    deltas = metrics["deltas"]
    if not deltas:
        return f"Need results for both `{baseline}` and `{treatment}` in `{source}`.\n"
    return "\n".join([
        f"# AgentPack E2E A/B: {baseline} vs {treatment}",
        "",
        f"- source: `{source}`",
        "",
        "| Metric | Baseline | AgentPack | Saved / lift |",
        "|---|---:|---:|---:|",
        f"| runs | {base['runs']:.0f} | {treat['runs']:.0f} | - |",
        f"| task success | {base['success_rate']:.0%} | {treat['success_rate']:.0%} | {deltas['success_rate_pp']:+.1f} pp |",
        f"| expected file touched | {base['expected_touch_rate']:.0%} | {treat['expected_touch_rate']:.0%} | - |",
        f"| tool calls | {base['avg_tool_calls']:.1f} | {treat['avg_tool_calls']:.1f} | {deltas['tool_calls_saved']:+.1f} |",
        f"| tokens | {base['avg_total_tokens']:,.0f} | {treat['avg_total_tokens']:,.0f} | {deltas['tokens_saved']:+,.0f} |",
        f"| token cost | ${base['avg_total_cost_usd']:.4f} | ${treat['avg_total_cost_usd']:.4f} | {_fmt_signed_usd(deltas['token_cost_saved_usd'])} |",
        f"| time to first correct file | {base['avg_time_to_first_expected_file_s']:.1f}s | {treat['avg_time_to_first_expected_file_s']:.1f}s | {deltas['time_to_first_correct_file_saved_s']:+.1f}s |",
        f"| duration | {base['avg_duration_s']:.1f}s | {treat['avg_duration_s']:.1f}s | {deltas['duration_saved_s']:+.1f}s |",
        "",
    ])


def _fmt_signed_usd(value: float) -> str:
    sign = "+" if value >= 0 else "-"
    return f"{sign}${abs(value):.4f}"


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
    input_cost_per_mtok: float = 0.0,
    output_cost_per_mtok: float = 0.0,
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
    agent_start_epoch = time.time()
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
    input_tokens = estimate_tokens(prompt)
    agent_output_tokens = _process_output_tokens(agent)
    input_cost = _estimate_token_cost(input_tokens, input_cost_per_mtok)
    output_cost = _estimate_token_cost(agent_output_tokens, output_cost_per_mtok)
    changed = sorted(git.dirty_files(repo)) if git.is_git_repo(repo) else []
    public_changed = _public_changed_files(changed)
    source_changed = [path for path in public_changed if not _is_test_path(path)]
    test_changed = [path for path in public_changed if _is_test_path(path)]
    protected_changed = _changed_protected_paths(repo, protected_hashes)
    expected_touched = _expected_files_touched(public_changed, case.expected_edit_paths)
    missing_expected = sorted(set(case.expected_edit_paths) - set(expected_touched))
    unexpected_touched = _unexpected_files_touched(public_changed, case.expected_edit_paths)
    time_to_first_expected_file = _time_to_first_expected_file(repo, expected_touched, agent_start_epoch)
    tool_calls = _estimate_agent_tool_calls(agent)
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
        input_tokens=input_tokens,
        agent_output_tokens=agent_output_tokens,
        estimated_input_cost_usd=round(input_cost, 8),
        estimated_output_cost_usd=round(output_cost, 8),
        estimated_total_cost_usd=round(input_cost + output_cost, 8),
        agent_returncode=agent.returncode,
        test_returncode=test.returncode,
        timed_out=timed_out,
        agent_tool_calls=tool_calls,
        time_to_first_expected_file_s=round(time_to_first_expected_file, 3) if time_to_first_expected_file is not None else None,
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
    parts = {part.lower() for part in Path(path.lower()).parts}
    return (
        path.startswith("tests/")
        or "test" in parts
        or "/tests/" in path
        or "__test__/" in path
        or "__tests__/" in path
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith("_test.go")
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


def _process_output_tokens(result: subprocess.CompletedProcess[str]) -> int:
    return estimate_tokens("\n".join(part for part in (result.stdout, result.stderr) if part))


def _estimate_agent_tool_calls(result: subprocess.CompletedProcess[str]) -> int:
    text = "\n".join(part for part in (result.stdout, result.stderr) if part)
    if not text:
        return 0
    patterns = [
        r"\btool[_ -]?call\b",
        r"\bexec_command\b",
        r"\bapply_patch\b",
        r"\bread_file\b",
        r"\bwrite_file\b",
        r"\blist_files\b",
        r"\bsearch\b",
        r"\brg\b",
    ]
    return sum(len(re.findall(pattern, text, flags=re.IGNORECASE)) for pattern in patterns)


def _time_to_first_expected_file(repo: Path, expected_touched: list[str], agent_start_epoch: float) -> float | None:
    deltas: list[float] = []
    for path in expected_touched:
        target = repo / path
        if not target.exists():
            continue
        try:
            delta = target.stat().st_mtime - agent_start_epoch
        except OSError:
            continue
        if delta >= 0:
            deltas.append(delta)
    return min(deltas) if deltas else None


def _estimate_token_cost(tokens: int, cost_per_mtok: float) -> float:
    if tokens <= 0 or cost_per_mtok <= 0:
        return 0.0
    return tokens / 1_000_000 * cost_per_mtok


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
        mode="lite",
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
    table.add_column("avg cost", justify="right")
    table.add_column("avg tools", justify="right")
    table.add_column("first file", justify="right")
    table.add_column("avg seconds", justify="right")
    table.add_column("pass/min", justify="right")
    table.add_column("pass/$", justify="right")
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
        avg_cost = sum(result.estimated_total_cost_usd for result in subset) / len(subset)
        avg_tools = sum(result.agent_tool_calls for result in subset) / len(subset)
        first_file_times = [
            result.time_to_first_expected_file_s
            for result in subset
            if result.time_to_first_expected_file_s is not None
        ]
        avg_first_file = sum(first_file_times) / len(first_file_times) if first_file_times else None
        avg_seconds = sum(result.duration_s for result in subset) / len(subset)
        total_seconds = sum(result.duration_s for result in subset)
        total_cost = sum(result.estimated_total_cost_usd for result in subset)
        pass_per_minute = (sum(1 for result in subset if result.passed) / total_seconds * 60) if total_seconds else 0.0
        pass_per_dollar = (sum(1 for result in subset if result.passed) / total_cost) if total_cost else 0.0
        table.add_row(
            strategy,
            str(len(subset)),
            f"{pass_rate:.0%}",
            f"{timeout_rate:.0%}",
            f"{expected_touch_rate:.0%}" if expected_touch_rate is not None else "-",
            f"{avg_tokens:,.0f}",
            f"${avg_cost:.4f}" if avg_cost else "-",
            f"{avg_tools:.1f}",
            f"{avg_first_file:.1f}s" if avg_first_file is not None else "-",
            f"{avg_seconds:.1f}",
            f"{pass_per_minute:.2f}",
            f"{pass_per_dollar:.2f}" if total_cost else "-",
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
    mode: str = typer.Option("balanced", "--mode", help=f"Mode for single-task run ({MODE_HELP})."),
    workspace: str = typer.Option("", "--workspace", help="Restrict benchmark packs to a workspace, e.g. apps/web."),
    cases: str = typer.Option("", "--cases", help="Path to TOML cases file (default: .agentpack/benchmark.toml)."),
    compare: bool = typer.Option(False, "--compare", help="Compare lite/balanced/deep for each task."),
    init: bool = typer.Option(False, "--init", help="Scaffold a benchmark.toml and exit."),
    results_template: bool = typer.Option(False, "--results-template", help="Create benchmarks/results/YYYY-MM-DD.md for publishing benchmark evidence."),
    from_history: int = typer.Option(0, "--from-history", help="Sample last N unique tasks from metrics.jsonl history."),
    write_cases: bool = typer.Option(False, "--write-cases", help="Append --from-history cases to .agentpack/benchmark.toml."),
    sample_fixtures: bool = typer.Option(False, "--sample-fixtures", help="Run bundled FastAPI/Next.js/mixed-repo fixture evals from a source checkout."),
    release_gate: bool = typer.Option(False, "--release-gate", help="Run the public real-repo release gate."),
    public_suite: bool = typer.Option(False, "--public-suite", help="Alias for the reproducible public benchmark suite."),
    reproduce: str = typer.Option("", "--reproduce", help="Reproduce a published benchmark version, e.g. v0.3.20."),
    public_repos: bool = typer.Option(False, "--public-repos", help="Run real public-repo commit cases from benchmarks/public-repos.toml."),
    public_repos_file: str = typer.Option("", "--public-repos-file", help="Path to public repo benchmark manifest."),
    public_repos_cache: str = typer.Option("", "--public-repos-cache", help="Directory for cached public repo clones."),
    public_repo_filter: str = typer.Option("", "--public-repo-filter", help="Comma-separated public repo names to run, e.g. gin,vite."),
    public_task_type_filter: str = typer.Option("", "--public-task-type-filter", help="Comma-separated public task types to run, e.g. go-service,typescript."),
    refresh_public_repos: bool = typer.Option(False, "--refresh-public-repos", help="Delete and reclone public repo benchmark cache before running."),
    benchmark_jsonl: str = typer.Option("", "--benchmark-jsonl", help="Write benchmark case metrics to this JSONL path."),
    public_table: bool = typer.Option(False, "--public-table", help="Write a publishable Markdown benchmark table under benchmarks/results/."),
    no_public_table: bool = typer.Option(False, "--no-public-table", help="Do not write a benchmark results markdown table."),
    misses: bool = typer.Option(False, "--misses", help="Show diagnostics for expected files that were not selected."),
    prove_targets: bool = typer.Option(False, "--prove-targets", help="Exit non-zero unless recall/token precision targets pass."),
    min_recall: float = typer.Option(0.60, "--min-recall", help="Recall target for --prove-targets."),
    min_token_precision: float = typer.Option(0.50, "--min-token-precision", help="Token precision target for --prove-targets."),
) -> None:
    """Benchmark file selection quality and token efficiency across tasks."""
    if ctx.invoked_subcommand is not None:
        return
    if not is_requested_mode(mode):
        console.print(f"[red]{invalid_mode_message(mode)}[/]")
        raise typer.Exit(1)
    mode = normalize_mode(mode)
    root = _root()
    if reproduce:
        normalized_reproduce = reproduce.strip().lstrip("v")
        if normalized_reproduce != "0.3.20":
            console.print(f"[yellow]No reproducible public suite registered for {reproduce}. Available: v0.3.20[/]")
            raise typer.Exit(1)
        public_suite = True
    if public_suite:
        public_repos = True
        prove_targets = True
        misses = True
        public_table = not no_public_table
        console.print(f"[bold]Public suite:[/] reproducible v{reproduce.strip().lstrip('v') or '0.3.20'} benchmark.")
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
                for fixture_mode in ("lite", "balanced", "deep"):
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
            _print_precision_diagnostics(results)
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
        specs = _filter_public_repo_specs(
            specs,
            repo_filter=public_repo_filter,
            task_type_filter=public_task_type_filter,
        )
        case_count = sum(len(spec.cases) + int(getattr(spec, "sample_history", 0) or 0) for spec in specs)
        if not specs or case_count == 0:
            console.print(f"[yellow]No public repo cases found in {manifest}[/]")
            raise typer.Exit(1)

        console.print(f"\n[bold]Running {case_count} public real-repo benchmark case(s)...[/]")
        console.print(f"[dim]Manifest:[/] {manifest}")
        if public_repo_filter:
            console.print(f"[dim]Repo filter:[/] {public_repo_filter}")
        if public_task_type_filter:
            console.print(f"[dim]Task-type filter:[/] {public_task_type_filter}")
        console.print("[dim]Each case checks out the parent of a real public commit and scores files changed by that commit.[/]\n")
        cache = Path(public_repos_cache) if public_repos_cache else None
        with console.status("[dim]Cloning/checking out public repo cases...[/]"):
            results = _run_public_repo_suite(root, specs, cache_dir=cache, refresh=refresh_public_repos)

        if not results:
            raise typer.Exit(1)

        console.print("\n[bold]Summary[/]")
        _print_summary_table(results)
        _print_task_type_summary(results)
        _print_precision_diagnostics(results)
        if misses:
            _print_miss_details(results)
        _print_quality_status(results, min_recall=min_recall, min_token_precision=min_token_precision)
        if benchmark_jsonl:
            out = _write_results_jsonl(Path(benchmark_jsonl), results)
            console.print(f"[green]✓[/] Wrote benchmark JSONL: [bold]{out}[/]")
        if public_table:
            from agentpack import __version__
            repo_names = ", ".join(spec.name for spec in specs)
            out = _write_public_benchmark_table(
                root,
                results,
                suite=f"public real-repo commits ({repo_names})",
                version=__version__,
                command=(
                    f"agentpack benchmark --public-suite --reproduce {reproduce}"
                    if public_suite and reproduce
                    else "agentpack benchmark --release-gate"
                ),
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
            for m in ("lite", "balanced", "deep"):
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
        _print_precision_diagnostics(results)
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
