# Runtime Loop

AgentPack remains a local repo context router. The runtime loop adds bounded
features around that router without becoming a provider proxy.

| Need | AgentPack surface |
|---|---|
| Retrieve selected, symbol, or omitted context after a pack | `agentpack retrieve` and MCP `retrieve_context` |
| Generate local lessons from task diffs | `agentpack learn` |
| Record learning feedback | `agentpack learn feedback helpful|not-helpful` |
| Track local token and retrieval activity | `agentpack perf --history N` and `agentpack stats` |
| Launch an agent after context refresh | `agentpack wrap` |
| Summarize noisy logs without losing failures | `agentpack compress-output --kind pytest|git-diff|rg|ls` |
| Inspect recent local task memory | `agentpack memory` |

## Compress, Cache, Retrieve

The runtime loop keeps the first context pack small and reversible:

- **Compress** repo files into budget-aware pack views and compress noisy command output into failure-focused summaries.
- **Cache** snapshots, summaries, pack metadata, registry records, session events, and learning feedback locally under `.agentpack/`.
- **Retrieve** precise file or symbol context from the latest pack registry through `agentpack retrieve` or MCP `retrieve_context`.

Rendered packs are prompt-cache friendly by default. Every markdown and compact
context artifact starts with the same stable instructions and mode legend before
task text, timestamps, git state, freshness JSON, selected files, or command
output. Providers with automatic prompt-prefix caching can reuse that prefix
across refreshes without users selecting a separate render mode.

## Compressor Types

| Compressor | What it compresses | User-facing surface |
|---|---|---|
| Context mode compression | Repo files into `full`, `diff`, `symbols`, `skeleton`, or `summary` views | `agentpack pack` |
| Diff hunk compression | Large changed-file diffs into task-relevant hunks | `agentpack pack` |
| Rendered-budget compression | Receipts, repo map, delta, runtime detail, conflicts, omitted files, then selected files | `agentpack pack` |
| Test log compression | Failures, assertions, and test summaries from noisy test output | `agentpack compress-output --kind pytest|test|npm|vitest|jest` |
| Diff output compression | Diff headers and hunks from patch output | `agentpack compress-output --kind git-diff|diff|patch` |
| Search output compression | File/line matches from grep-style output | `agentpack compress-output --kind rg|grep|search` |
| Listing compression | Head/tail samples from long listing or tree output | `agentpack compress-output --kind ls|find|tree` |
| Generic output compression | Failure lines, paths, diffs, repeated lines, or edge samples for unknown output | `agentpack compress-output --kind auto` |

## Boundaries

AgentPack does not proxy LLM traffic, rewrite provider requests, or replace raw
logs as source of truth. Retrieval uses the latest local pack registry, supports
symbol-level block IDs when the latest pack contains symbols, and refuses stale
full-file reads unless explicitly allowed.
