# Native Windows Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add native Windows support for AgentPack on PowerShell plus Git for Windows across the CLI, npm wrapper, git hooks, global install flow, Claude/Codex integrations, docs, and regression tests.

**Architecture:** Introduce a small platform-aware integration helper layer, replace POSIX-only git hook bodies with cross-platform Python launchers, extend global shell automation to PowerShell profiles, and remove the npm wrapper’s hard Windows refusal. Keep the product behavior the same across platforms by localizing platform differences to integration/runtime helpers and generated automation.

**Tech Stack:** Python 3.10+, Typer, pathlib, subprocess, pytest, Node.js test runner, npm wrapper launcher.

---

### Task 1: Add cross-platform integration/runtime helpers

**Files:**
- Create: `src/agentpack/integrations/platform.py`
- Modify: `src/agentpack/integrations/git_hooks.py`
- Test: `tests/test_git_hooks.py`

- [ ] Add a focused helper module for Windows detection, Python command rendering, and background subprocess launcher generation.
- [ ] Refactor repo-local git hook generation to build cross-platform Python launcher hook bodies instead of POSIX shell snippets.
- [ ] Preserve idempotent install/remove behavior and existing hook markers so upgrade paths keep working.
- [ ] Add/update tests that assert hook content is cross-platform and no longer depends on POSIX-only shell features.

### Task 2: Add Windows-aware global install automation

**Files:**
- Modify: `src/agentpack/integrations/global_install.py`
- Modify: `src/agentpack/commands/install.py`
- Test: `tests/test_global_install.py`
- Test: `tests/test_install.py`

- [ ] Replace POSIX-only global git template hook bodies with the same cross-platform Python launcher strategy used for repo-local hooks.
- [ ] Add PowerShell profile detection, install, update, and removal logic with explicit AgentPack markers.
- [ ] Keep existing zsh/bash behavior unchanged for non-Windows platforms.
- [ ] Extend install/global-install output and tests to cover Windows-compatible shell/profile integration behavior.

### Task 3: Keep agent integrations healthy on Windows

**Files:**
- Modify: `src/agentpack/installers/claude.py`
- Modify: `src/agentpack/installers/codex.py`
- Modify: `src/agentpack/commands/doctor.py`
- Modify: `src/agentpack/commands/init.py`
- Test: `tests/test_init.py`
- Test: `tests/test_claude_adapter.py`
- Test: `tests/test_codex_adapter.py`
- Test: `tests/test_doctor.py`

- [ ] Make installer and doctor logic recognize new cross-platform hook command patterns as healthy/current.
- [ ] Update stale-hook detection so old POSIX-only hook variants are migrated cleanly.
- [ ] Ensure `init` and `install` still emit the same agent files while using the new hook generation underneath.
- [ ] Add targeted tests where current assertions are too POSIX-specific.

### Task 4: Enable Windows npm wrapper support

**Files:**
- Modify: `npm/bin/agentpack.js`
- Test: `npm/test/launcher.test.js`
- Test: `npm/test/version-sync.test.js`
- Test: `tests/test_npm_package.py`

- [ ] Remove the hard Windows refusal from the npm wrapper.
- [ ] Keep the existing Windows-specific venv path handling and verify it through tests.
- [ ] Add regression coverage proving dry-run/version behavior works on Windows path assumptions without requiring a Windows runner.

### Task 5: Update docs and release notes

**Files:**
- Modify: `README.md`
- Modify: `npm/README.md`
- Modify: `CHANGELOG.md`

- [ ] Replace “Windows unsupported” messaging with the supported scope: PowerShell plus Git for Windows.
- [ ] Update install/global-install/hook documentation to explain Windows behavior and any remaining caveats.
- [ ] Record the feature in the changelog.

### Task 6: Verify end-to-end behavior

**Files:**
- Verify only

- [ ] Run the focused Python tests covering hooks, install flows, init flows, and doctor behavior.
- [ ] Run npm wrapper tests and `npm pack --dry-run`.
- [ ] Run `python3 -m build` to ensure packaging still works.
- [ ] Check `git diff --check` and review final diff scope for unrelated churn.
