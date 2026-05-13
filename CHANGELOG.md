# Changelog

All notable changes to agentpack-cli are documented here.

Format: `## [version] — YYYY-MM-DD` followed by categorised entries.

---

## [Unreleased]

---

## [0.1.24] — 2026-05-13

### Added
- Context packs now render freshness metadata, including generated time, git branch/SHA, task source, changed-file source, snapshot hash, and dirty-file count.
- Benchmark cases can declare `task_type`, and benchmark summaries now report precision/recall/F1 grouped by task type.
- Miss diagnostics now include the changed-file basis used when expected files were missed.

### Changed
- Broad generic task terms are downweighted so words like "fix", "release", "task", and "implementation" no longer dominate concrete domain/file terms.
- Broad tasks tighten weak summary inclusion by raising the summary floor and reducing summary caps.

### Fixed
- MCP `get_context` now marks context stale when `.agentpack/task.md` differs from the packed task or git HEAD changed after the pack.

---

## [0.1.23] — 2026-05-12

### Added
- npm wrapper package scaffold under `npm/`, publishing `@vishal2612200/agentpack` as a Node launcher for the Python `agentpack-cli`.
- npm CI checks for launcher behavior, package contents, and version sync with the Python package.
- npm publish workflow for tagged releases, using `NPM_TOKEN` and provenance metadata.

---

## [0.1.22] — 2026-05-12

### Added
- `agentpack benchmark --misses` now reports expected files that were not selected, including status, rank, score, and scoring reasons.
- Sample fixture benchmark output can be paired with `--misses` for repeatable smoke checks across bundled FastAPI, Next.js, and mixed Python/TypeScript fixtures.
- README now documents AgentPack as an open-source library with clearer expectations, limitations, eval workflow, development commands, and contribution targets.

### Changed
- Ranking now expands Kundali/astrology/chart compatibility terms to catch product-domain files whose names differ from task text.
- Ranking now boosts matching implementation roles such as services, controllers, schemas, handlers, repositories, and clients.
- Full-stack tasks now get a cross-layer relatedness boost so matching backend implementation files can surface when UI pages, routes, or controllers match the same domain.
- Default scoring config includes `implementation_role` and `cross_layer_related` weights.

### Fixed
- Low-recall benchmark runs are easier to diagnose: misses now distinguish ignored files, summary-floor exclusions, budget cuts, missing files, and low-score selections.
- Added Kundali-style regression coverage for backend astrology services, schemas, and Python handlers so similar full-stack recall gaps are less likely to regress.

---

## [0.1.21] — 2026-05-12

### Added
- Pack diagnostics: `agentpack pack` now warns when a pack looks noisy, such as broad filename matching, no changed files, mostly-summary output, or many weak summaries excluded.
- Token-weighted selection accuracy: metrics now store selected token counts and `agentpack stats` reports token precision overall and by inclusion mode (`full`, `symbols`, `summary`).
- Mode-aware summary caps: `minimal` and `balanced` modes now cap unchanged summaries by default to keep packs focused and predictable.
- `agentpack doctor` warns when running from a source checkout but the `agentpack` binary imports an installed package instead of local `src/`.

### Changed
- Keyword ranking now weights literal task terms higher than variants and concept expansions, reducing broad synonym noise while keeping useful concept matches.
- Keyword matching now uses whole identifier/path tokens instead of substring matching, so broad fragments no longer match unrelated names.
- `agentpack stats` now compares packed context against raw full contents for the top included files instead of a misleading arbitrary "manual 20 files" estimate.
- `agentpack stats` reads the last pack metadata path for the top-included table, so it reflects the actual latest pack.

### Fixed
- Weak unchanged summaries no longer fill the token budget just because they had any positive score.
- Selection accuracy metrics now distinguish file-level precision from token-level precision, making summary noise visible instead of over-penalizing useful full/symbol context.

---

## [0.1.20] — 2026-05-11

### Added
- `git.staged_files()` — reads git index only (`--cached`), strongest live signal.
- `git.infer_task_with_source()` — returns `(task, source_label)` with 9-level priority chain: `task.md` → `branch+staged` → `staged` → `branch+unstaged` → `branch+commit` → `branch` → `unstaged` → `commits` → `recently_modified` → `fallback`.
- Source label logged on auto-inference: `Auto task (branch+staged): feat add-rate-limiting: payments`.

### Fixed
- `--task auto` previously used recently-modified files (noisy git log history) as primary signal. Now uses staged files first — "what you're about to commit" is the strongest same-session signal.
- Hook `_resolve_task`: slash commands (`/caveman`, `/agentpack`) and non-coding prompts no longer pollute pack task keywords. Fall back to `"auto"` → git priority chain instead.
- Hook display task was read from stale `pack_metadata.json` — showed previous session's task. Now uses live `infer_task_with_source()` so displayed task reflects current branch/staged state.

---

## [0.1.19] — 2026-05-10

### Fixed
- Hook hint showed stale last-commit message as task. Now reads `task.md` first (if user has written a real task), falls back to pack_metadata task. Prompt text used only for repack keyword — not displayed.
- `excluded_paths` showed irrelevant low-score files (LICENSE, __init__.py). Now only surfaces files excluded due to budget exhaustion — files that scored well but didn't fit. Actual blind-spot signal.
- `SessionStart` hook was raw shell (`rm -f ... && agentpack pack`). Now delegates to `agentpack hook --event SessionStart` — consistent with UserPromptSubmit, versioned, testable.

### Added
- `selected_hints` in `metrics.jsonl`: top-8 files with their first scoring reason (modified / keyword match / dependency / etc). Hook hint now shows `src/auth.py — modified` instead of bare path.
- `agentpack hook --event SessionStart` handler: clears `.mcp_reminded` and `.context_injected` sentinels so first prompt gets fresh context.
- `agentpack doctor` detects stale hooks: warns when old inline-Python injection hooks or old md5-based MCP reminder hooks are present, with upgrade command.
- Background repack passes `--since HEAD~1` when repo has changed — focuses changed-file scoring on recent diff rather than full git history.
- `_resolve_task()` in hook: merges `task.md` + prompt — `task.md` wins if user has written a real task, otherwise prompt text drives repack keywords.

### Changed
- `installers/claude.py` SessionStart template simplified to `agentpack hook --event SessionStart`. Stale-hook cleanup extended to remove old shell-based session hooks.

---

## [0.1.18] — 2026-05-10

### Added
- `agentpack hook --event UserPromptSubmit` CLI subcommand — replaces the fragile inline Python one-liner in `settings.json`. Hook logic is now versioned, tested, and updatable without touching settings files.
- **Option B hint** (MCP mode): hook emits `~50–150 token` message with last task + top-5 files list instead of "MCP ready" string. Gives Claude routing signal without injecting any file content.
- **Capped fallback** (no MCP): hook emits top-8 files with hard 3000-char cap and nudge to install MCP. Prevents silent no-op for users without MCP configured.
- 14 new tests covering MCP detection, metrics loading, repack trigger, cap enforcement, and output format.

### Changed
- `installers/claude.py` hook template simplified to `agentpack hook --event UserPromptSubmit` (one line). Stale-hook cleanup updated to remove all old inline Python hooks.
- Global `~/.claude/settings.json` and project `.claude/settings.json` updated to use new hook command.

---

## [0.1.17] — 2026-05-10

### Fixed
- `UserPromptSubmit` hook used `md5(entire snapshot.json bytes)` to detect repo changes — `created_at` field updated on every pack caused false "repo changed" signal every prompt. Now reads `root_hash` field (content-addressed, stable when files unchanged).
- `installers/claude.py` hook template had same `md5` bug — `agentpack init` on new repos would install the broken hook. Fixed and added stale-hook cleanup: re-running `agentpack init` now removes old `md5`-based hooks.

### Changed
- `UserPromptSubmit` hook reads `prompt` from stdin (Claude Code passes it as JSON) and passes first 200 chars as `--task` to background repack. Pack keyword scoring now matches the current conversation instead of always inferring from git log.

### Added
- `excluded_files` and `excluded_paths` (top 10 score-too-low) recorded in `metrics.jsonl` after each pack.
- `get_stats` MCP tool surfaces `excluded_files: N (score too low)` and a `### Below-threshold files` section — agents can see what was ranked out of context.

---

## [0.1.15] — 2026-05-09

### Fixed
- `install --agent codex --global` no longer installs per-repo git hooks (matches cursor/windsurf behavior).
- `install --agent codex` hint message now includes `--agent codex` flag.

### Changed
- Agent instructions (AGENTS.md, CLAUDE.md, .cursorrules, .windsurfrules, .cursor/rules/agentpack.mdc) strengthened: agents now write `task.md` at task start so pack targets the right files. Removed stale `agentpack session refresh` references (command removed in v0.1.12).

### Added
- Knowledge/architecture doc surfacing: DECISIONS.md, ADR-*.md, ARCHITECTURE.md, and .md files under `docs/adr/`, `docs/decisions/`, `docs/rfcs/` always score higher (weight: 30) so agents see design rationale and known tradeoffs.
- Test file pairing: test files whose source scores above the median are now boosted even when the source isn't in the changed set — agents see relevant tests alongside relevant source.
- Git churn scoring: files in the top 10% by commit frequency get a churn bonus (weight: 15), surfacing historically risky/hot files. Uses a single `git log` call — no per-file subprocess overhead.

---

## [0.1.14] — 2026-05-09

### Added
- Selection accuracy metrics in `metrics.jsonl`: after each pack, recall/precision/F1 are computed by comparing the previous pack's selected files against files actually changed since then.
- `agentpack stats` surfaces avg recall, precision, F1 over the last 10 runs.

---

## [0.1.13] — 2026-05-08

### Fixed
- Watch refresh loop on Linux: watchdog uses inotify which fires on file reads (IN_ACCESS), not just writes. Replaced `on_any_event` with explicit `on_created`/`on_modified`/`on_deleted`/`on_moved` handlers — read-only events no longer trigger refresh.
- Ignore `*.tsbuildinfo` files (TypeScript incremental build artifacts written on every compile).

---

## [0.1.12] — 2026-05-08

### Fixed
- Watch refresh loop for VSCode users: `.vscode/` was not in `_IGNORE_DIRS` — VSCode writes workspace state every few seconds, triggering endless refreshes. Added `.vscode/`, `.idea/`, `.fleet/` to ignore list.
- Watch refresh loop for Antigravity users: adapter writes `.agent/skills/agentpack/SKILL.md` outside `.agentpack/` — now tracked via `_WRITTEN_PATHS` set populated from `run_refresh()` return value.

### Changed
- Removed `agentpack session` subcommands (`start`, `stop`, `status`, `refresh`) — `agentpack init` already bootstraps the session. Shared logic (`run_refresh`, `_file_hash`, `_now_iso`, `_atomic_write`) moved to `commands/_shared.py`.
- README updated: session commands removed from all examples; primary flow is `init` → edit `task.md` → `watch`.

---

## [0.1.11] — 2026-05-08

### Fixed
- Watch refresh loop: ignore all `.agentpack/` generated files (metrics.jsonl, pack_metadata.json, cache/, snapshots/, .context_injected) — previously only 3 specific paths were blocked.

### Changed
- CI: lint now hard-fails (removed `|| true` from ruff).
- CI: coverage gate added — `core/` + `analysis/` must reach 80% (currently 84%).
- Release process: tags must originate from `release/*` branch; CHANGELOG entry required before publish.

### Added
- `CHANGELOG.md` — all versions back to 0.1.0.
- `.github/PULL_REQUEST_TEMPLATE.md` — checklist: tests, coverage, lint, CHANGELOG, version bump.

---

## [0.1.10] — 2026-05-08

### Fixed
- Watch refresh loop: ignore all `.agentpack/` generated files (metrics.jsonl, pack_metadata.json, cache/, snapshots/, .context_injected) — previously only 3 specific paths were blocked, causing every refresh to trigger another refresh.

---

## [0.1.9] — 2026-04-28

### Changed
- Removed LLM cost path.
- Parallel summarise.
- MCP server improvements.

---

## [0.1.8] — 2026-04-28

### Fixed
- Stale context injection after session resume.
- MCP server stability.

### Changed
- README cleanup.

---

## [0.1.7] — 2026-04-28

### Added
- Security hardening.
- Config explainability output.
- Symbol scoring improvements.

### Fixed
- Watch reliability.

---

## [0.1.6] — 2026-04-28

### Changed
- Version bump.

---

## [0.1.5] — 2026-04-28

### Fixed
- `__version__` in `__init__.py` was stuck at 0.1.0.

---

## [0.1.4] — 2026-04-28

### Fixed
- Trusted publisher mismatch in CI.
- Added tomli to dev dependencies.

---

## [0.1.3] — 2026-04-28

### Fixed
- Python 3.10 support: `tomllib` not in stdlib until 3.11, added `tomli` fallback.

---

## [0.1.2] — 2026-04-28

### Fixed
- Root causes of git hook timeouts.

---

## [0.1.1] — 2026-04-28

### Changed
- Version bump.

---

## [0.1.0] — 2026-04-28

### Added
- Initial release.
- PyPI publish workflow.
