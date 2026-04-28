from __future__ import annotations

from pathlib import Path

import pathspec


DEFAULT_AGENTIGNORE = """\
# dependencies
node_modules/
.venv/
venv/
__pycache__/

# builds
dist/
build/
.next/
coverage/

# caches
.pytest_cache/
.mypy_cache/
.ruff_cache/

# generated/noisy
generated/
*.generated.*
*.min.js
*.map
*.lock
*.log

# secrets
.env
.env.*
*.pem
*.key

# lock files
package-lock.json
yarn.lock
pnpm-lock.yaml
Pipfile.lock
poetry.lock
Cargo.lock
composer.lock
Gemfile.lock

# large data
*.csv
*.jsonl
*.parquet
"""


def load_spec(ignore_path: Path) -> pathspec.PathSpec:
    if ignore_path.exists():
        lines = ignore_path.read_text().splitlines()
    else:
        lines = DEFAULT_AGENTIGNORE.splitlines()
    return pathspec.PathSpec.from_lines("gitignore", lines)


def is_ignored(spec: pathspec.PathSpec, path: str) -> bool:
    return spec.match_file(path)
