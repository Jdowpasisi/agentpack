# Changelog

All notable changes to agentpack-cli are documented here.

Format: `## [version] — YYYY-MM-DD` followed by categorised entries.

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
