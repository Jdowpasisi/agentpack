# Changelog

All notable changes to agentpack-cli are documented here.

Format: `## [version] — YYYY-MM-DD` followed by categorised entries.

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
