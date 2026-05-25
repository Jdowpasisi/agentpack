# Native Windows Support Design

## Goal

Add first-class native Windows support for AgentPack on `PowerShell + Git for Windows`, including:

- Python CLI workflows
- npm wrapper bootstrap
- repo-local git hooks
- global git template hooks
- Claude integration
- Codex, Cursor, Windsurf, and Antigravity integrations

The result should let a Windows user install AgentPack, initialize a repo, get prompt-time refresh hooks, and use the same documented workflows without being told to switch to WSL.

## Non-Goals

- Supporting `cmd.exe` as a first-class shell workflow
- Supporting bare Git without Git for Windows hook execution
- Rewriting core ranking, packing, or MCP behavior
- Introducing separate Windows-only product behavior for AgentPack features

## Current Gaps

The repo already identifies the key blockers:

1. The npm wrapper exits early on `win32` in `npm/bin/agentpack.js`.
2. Repo-local git hooks in `src/agentpack/integrations/git_hooks.py` write POSIX shell snippets with `>/dev/null 2>&1 &`.
3. Global git template hooks in `src/agentpack/integrations/global_install.py` are also POSIX shell snippets.
4. Global shell automation only knows how to patch zsh/bash rc files.
5. Documentation still marks Windows unsupported because hooks and Claude session behavior assume POSIX commands such as `python3` and `rm -f`.

The good news is that the higher-level integration flow is already mostly platform-neutral:

- Claude and Codex both invoke `agentpack hook ...`, not inline shell scripts
- MCP registration is command-based JSON
- Most installer code only writes files and JSON

That means the real work is in runtime/platform shims and generated automation, not in the main domain logic.

## User Experience Target

On Windows, a user should be able to:

1. Install `agentpack-cli` directly with Python or through the npm wrapper.
2. Run `agentpack init --agent claude|codex|cursor|windsurf|antigravity`.
3. Get working Git-driven auto-refresh hooks in `.git/hooks/`.
4. Run `agentpack global-install` and receive:
   - Git template hooks that work in Git for Windows
   - A PowerShell profile hook instead of a zsh/bash hook
5. Use Claude prompt/session hooks without any hardcoded `python3`, POSIX shell, or `rm -f` assumptions.

## Recommended Architecture

Use a compatibility-shim architecture:

- keep existing product behavior and installer entrypoints
- introduce platform-aware helpers for command construction and automation generation
- replace shell-body hook scripts with Python-based hook launchers that Git for Windows can execute consistently
- extend global shell integration to PowerShell rather than forking the whole feature set

This keeps Windows behavior aligned with macOS/Linux while containing platform variance to a small surface area.

## Design

### 1. Add a runtime/platform helper layer

Introduce a small helper module under `src/agentpack/integrations/` or `src/agentpack/core/` for platform-sensitive behavior.

Responsibilities:

- detect whether runtime is Windows
- return the correct Python executable name or `sys.executable`
- return background-process launch strategy
- generate platform-safe hook bodies
- choose the correct profile file for global shell automation

This module should not contain business logic about ranking or packing; it only normalizes platform differences for integrations.

### 2. Replace POSIX git hook bodies with Python entrypoints

Current local hook generation writes shell scripts such as:

- `#!/bin/sh`
- `agentpack pack ... >/dev/null 2>&1 &`

That is the main cross-platform problem.

New design:

- generated hook files should still be plain Git hook files in `.git/hooks/`
- hook contents should execute a tiny Python snippet or `python -m agentpack ...` launcher using the current interpreter path
- the script should detach/background the pack refresh using Python subprocess behavior instead of shell `&`
- the same logical hook body should be generated for all platforms

Why this is best:

- Git for Windows can execute hook files, but shell quoting/background behavior is where portability breaks
- Python is already a hard dependency for AgentPack itself
- a Python launcher gives consistent stdout/stderr suppression and process detachment rules

This should apply to:

- repo-local hooks in `src/agentpack/integrations/git_hooks.py`
- global template hooks in `src/agentpack/integrations/global_install.py`

### 3. Make global shell automation PowerShell-aware

Current `global-install` patches zsh/bash rc files only.

Windows design:

- detect PowerShell on Windows
- patch the user PowerShell profile instead of `.zshrc` / `.bashrc`
- add an `agentpack` chpwd-equivalent using a PowerShell prompt/profile hook
- preserve current opt-in safety: only act inside repos with `.agentpack/config.toml`

Important constraint:

- Windows support should not require shell-hook parity with every POSIX detail
- it should preserve the same intent: lightweight repo entry refresh in opted-in repos

### 4. Remove npm wrapper Windows refusal

`npm/bin/agentpack.js` already handles Windows venv layout correctly:

- `Scripts/`
- `python.exe`
- `agentpack.exe`

The current blocker is the explicit `ensureSupportedPlatform()` refusal.

Change:

- remove the hard failure on `win32`
- keep the Windows-specific venv path logic
- verify bootstrap, version reporting, and dry-run behavior under Windows tests

### 5. Keep Claude/Codex integration command-based

Claude and Codex integrations are already close to portable because they use command JSON:

- `agentpack hook --event SessionStart`
- `agentpack hook --event UserPromptSubmit`

Design rule:

- do not add Windows-specific alternate command formats unless required by the target app
- if path/command resolution becomes an issue, centralize it behind one helper that emits a stable executable command string

Because the current Claude stale-hook cleanup logic searches for old `rm -f` / `python3`-based commands, doctor/install code should be broadened to recognize both old POSIX hooks and new cross-platform hooks.

### 6. Update docs to mark Windows supported with scope

README and npm docs should move from:

- “Windows is not supported”

to:

- “Windows is supported with PowerShell + Git for Windows”

Docs should also explain:

- the supported shell/environment
- any remaining caveats
- how `global-install` behaves on Windows

## File-Level Plan

Likely code surfaces:

- `src/agentpack/integrations/git_hooks.py`
  - replace shell snippets with Python-based hook launcher generation
- `src/agentpack/integrations/global_install.py`
  - replace POSIX-only template hook bodies
  - add PowerShell profile patching and removal
- `src/agentpack/installers/claude.py`
  - keep command-based hooks and update stale-hook detection to recognize the new cross-platform command patterns
- `src/agentpack/commands/doctor.py`
  - treat Windows hook/profile installs as healthy states
- `npm/bin/agentpack.js`
  - remove hard Windows refusal
- `README.md`
- `npm/README.md`

Likely test surfaces:

- `tests/test_init.py`
- `tests/test_install.py`
- `tests/test_global_install.py`
- `tests/test_hook_cmd.py`
- `tests/test_npm_package.py`
- add new focused tests for generated Windows hook/profile content if current tests are too POSIX-specific

## Testing Strategy

Testing should be mostly deterministic and string-based, not dependent on a real Windows runner for every case.

Required coverage:

1. Hook generation tests
   - local git hooks render portable launcher content
   - Windows-safe content does not depend on `#!/bin/sh`, `rm -f`, or POSIX redirection

2. Global install tests
   - PowerShell profile selection and patching
   - idempotent install/update/remove behavior
   - git template hooks remain opt-in via `.agentpack/config.toml`

3. npm wrapper tests
   - win32 path layout expectations
   - no hard unsupported-platform exit

4. Integration tests
   - `init --agent ...` still writes expected files
   - health checks and doctor output accept the new cross-platform hook patterns

5. Regression checks
   - existing macOS/Linux behavior still passes unchanged tests wherever possible

## Risks

### Risk: Git hook execution portability

Git hook execution can vary across environments.

Mitigation:

- keep hooks as simple launcher files
- avoid heavy shell syntax
- prefer Python invocation over shell composition

### Risk: PowerShell profile patching is fragile

Profile locations and conventions differ.

Mitigation:

- support the common user profile path first
- patch idempotently with explicit markers
- keep removal logic symmetrical

### Risk: hidden command-resolution issues in Claude/Codex

Some integrations may not resolve `agentpack` the same way on Windows.

Mitigation:

- centralize command construction
- add tests around generated command strings
- prefer directly invocable commands already used by the CLI install path

## Recommendation

Ship Windows support in one focused slice:

1. platform helper
2. local + global git hook portability
3. PowerShell profile support
4. npm wrapper unblocking
5. docs/tests

That achieves real end-to-end native support without splitting the codebase into separate POSIX and Windows implementations.
