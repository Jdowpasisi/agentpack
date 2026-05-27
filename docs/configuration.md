# Configuration

Configuration is intentionally file-based and local. Most projects can start with defaults, then tune ignore rules and scoring weights when ranking needs calibration.

## Configuration

`.agentpack/config.toml`:

```toml
[project]
root = "."
ignore_file = ".agentignore"

[context]
default_budget = 40000
default_mode = "balanced"
max_file_tokens = 4000
min_summary_score = 60
max_summary_files_minimal = 15
max_summary_files_balanced = 40
max_summary_files_deep = 0
include_tests = true
include_configs = true
include_receipts = true

[hooks]
task_switch_detection = true
task_switch_min_terms = 1

[agents.claude]
output = ".agentpack/context.claude.md"
patch_claude_md = true

[agents.generic]
output = ".agentpack/context.md"
```

---

## Configurable scoring weights

```toml
# .agentpack/config.toml
[scoring]
modified                  = 100
staged                    = 90
filename_keyword          = 80
symbol_keyword            = 70
content_keyword_per_hit   = 10
content_keyword_max       = 60
direct_dep                = 50
reverse_dep               = 40
related_test              = 35
knowledge_file            = 30   # DECISIONS.md, ADR-*.md, ARCHITECTURE.md, docs/adr/ etc.
config_file               = 25
recently_modified         = 20
churn_high                = 15   # top 10% by commit frequency
large_unrelated_penalty   = -50
ignored_penalty           = -100
```

---

## .agentignore

Works like `.gitignore`. Default rules exclude:

- `node_modules/`, `.venv/`, `__pycache__/`
- `dist/`, `build/`, `.next/`, `coverage/`
- `*.lock`, `*.log`, `*.min.js`, `*.map`
- `.env`, `.env.*`, `*.pem`, `*.key`
- `*.csv`, `*.jsonl`, `*.parquet`

Use automation before hand-tuning ignore rules:

```bash
agentpack ignore suggest
agentpack ignore apply          # dry-run
agentpack ignore apply --yes    # write reviewed suggestions
agentpack diagnose-selection
```

---

## Git integration

```
.agentignore              ✓ commit
.agentpack/config.toml    ✓ commit
.agentpack/cache/         ✓ commit if --share-cache (recommended for teams)
.agentpack/.gitignore     ✗ gitignored
.agentpack/snapshots/     ✗ gitignored
.agentpack/context.*      ✗ gitignored
.agentpack/task.md        ✗ gitignored (local current task)
.agent/skills/agentpack/  ✗ gitignored (generated Antigravity context)
```

---

## File scoring

| Signal | Points |
|--------|-------:|
| Modified file | +100 |
| Staged file | +90 |
| Filename/path keyword match | +80 |
| Symbol keyword match | +70 |
| Content keyword match | +60 |
| Direct dependency of changed file | +50 |
| Reverse dependency | +40 |
| Has related tests | +35 |
| Knowledge/architecture doc (DECISIONS.md, ADR-*.md, ARCHITECTURE.md, docs/adr/, docs/decisions/, docs/rfcs/) | +30 |
| Config file | +25 |
| Recently modified | +20 |
| High churn (top 10% by commit frequency) | +15 |
| Large unrelated file | −50 |
| Ignored/binary | −100 |

Keyword scoring uses weighted concept synonym expansion — literal task terms are strongest, normalized variants are slightly weaker, and broad concept synonyms are weaker again. "rate limiting" still expands to `throttle`, `leaky`, `bucket`, `quota`, but broad expansions no longer dominate literal task terms. Matching is token-based, so `task` does not accidentally match every `tasks.py`.

---
