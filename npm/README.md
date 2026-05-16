# AgentPack

Task-aware context packing for AI coding agents.

AgentPack scans a repository locally, ranks the files that matter for the current task, and writes a compact markdown context pack for tools such as Claude Code, Cursor, Windsurf, Codex, Antigravity, CI jobs, and generic LLM workflows.

Use it when the repo is too large to paste, but a blank agent session keeps wasting time rediscovering routes, services, tests, configs, and recent changes.

## What this npm package is

`@vishal2612200/agentpack` is a Node launcher for the Python package [`agentpack-cli`](https://pypi.org/project/agentpack-cli/).

On first run it:

1. Finds Python 3.10+.
2. Creates a per-version virtual environment in your user cache directory.
3. Installs the matching `agentpack-cli` version from PyPI.
4. Proxies every command to the real `agentpack` CLI.

The Python CLI remains the source of truth. The npm package exists so JavaScript-heavy teams can install AgentPack with the toolchain they already use. This wrapper installs the core CLI; optional Python extras such as `watch` and `mcp` are documented below.

## Install

```bash
npm install -g @vishal2612200/agentpack
agentpack --version
```

Requirements:

- Node.js 18+
- Python 3.10+
- macOS or Linux

Windows is not supported directly yet. Use WSL, or install `agentpack-cli` inside a Linux environment.

## First project

```bash
cd your-project
agentpack init --agent codex
printf '%s\n' "fix auth token expiry" > .agentpack/task.md
agentpack pack
```

Use the agent that matches your editor or CLI:

```bash
agentpack init --agent claude
agentpack init --agent cursor
agentpack init --agent windsurf
agentpack init --agent codex
agentpack init --agent antigravity
```

`agentpack init` creates local `.agentpack/` state and installs the selected integration when supported. `agentpack pack` reads `.agentpack/task.md`, ranks relevant files, and writes the adapter-specific context output.

For a guided setup:

```bash
agentpack quickstart --task "fix auth token expiry"
```

## Daily workflow

```bash
printf '%s\n' "describe the task you are about to work on" > .agentpack/task.md
agentpack pack
agentpack stats
```

## Useful commands

```bash
agentpack status
agentpack doctor --agent all
agentpack explain --file path/to/file.py
agentpack benchmark --sample-fixtures --misses
agentpack repair --agent all
```

## Optional watch and MCP workflows

The `watch` and `mcp` commands use optional Python dependencies. If you need those workflows today, install the Python package with extras:

```bash
python -m pip install "agentpack-cli[all]"
agentpack watch
agentpack mcp
```

The npm wrapper still works well for the core setup, pack, status, doctor, explain, repair, and benchmark commands.

## Python selection

By default, the wrapper tries `python3` and then `python`. To force a specific interpreter:

```bash
AGENTPACK_PYTHON=/opt/homebrew/bin/python3 agentpack --version
```

## Cache location

The wrapper installs the Python CLI under:

```text
$XDG_CACHE_HOME/agentpack-npm/<version>/
```

or, if `XDG_CACHE_HOME` is unset:

```text
~/.cache/agentpack-npm/<version>/
```

Override the cache path with:

```bash
AGENTPACK_NPM_CACHE_DIR=/tmp/agentpack-cache agentpack --version
```

To force a clean reinstall of the Python CLI for this npm package version, remove the matching cache directory and run `agentpack --version` again.

## Troubleshooting

`agentpack npm wrapper: Python >=3.10 is required.`

Install Python 3.10+ or set `AGENTPACK_PYTHON=/path/to/python3`.

`failed to install agentpack-cli==<version>`

Check that `python -m pip` can reach PyPI. Corporate networks may need standard pip index or proxy configuration.

`agentpack: command not found`

Make sure your global npm bin directory is on `PATH`:

```bash
npm bin -g
```

## Security and privacy

AgentPack scans, summarizes, ranks, and packs locally. It does not call an LLM API for the core pack flow. Context files are written into your repository under `.agentpack/` and integration-specific local files.

## Links

- Full docs: <https://github.com/vishal2612200/agentpack>
- PyPI package: <https://pypi.org/project/agentpack-cli/>
- npm package: <https://www.npmjs.com/package/@vishal2612200/agentpack>
- Issues: <https://github.com/vishal2612200/agentpack/issues>
