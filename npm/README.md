# AgentPack npm wrapper

Task-aware context packing for AI coding agents.

This npm package is a thin wrapper around the Python package
[`agentpack-cli`](https://pypi.org/project/agentpack-cli/). On first run it:

1. Finds Python 3.10+.
2. Creates a per-version virtual environment under your user cache directory.
3. Installs the matching PyPI package version.
4. Proxies all arguments to the real `agentpack` CLI.

```bash
npm install -g @vishal2612200/agentpack
agentpack quickstart --task "fix auth token expiry"
```

## Requirements

- Node.js 18+
- Python 3.10+
- macOS or Linux

Windows is not supported by AgentPack yet. Use WSL or install the Python package
directly inside a Linux environment.

## Python selection

By default, the wrapper tries `python3` and then `python`. To force a specific
interpreter:

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

Override with:

```bash
AGENTPACK_NPM_CACHE_DIR=/tmp/agentpack-cache agentpack --version
```

## Upstream

Full docs: <https://github.com/vishal2612200/agentpack>
