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
| Run an optional guarded proof harness around an external agent | `agentpack work --run` and `agentpack finish` |
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

`agentpack work --run` is optional. It is a guarded proof harness around an
external coding agent, not the main AgentPack workflow and not a fully
autonomous coding agent. AgentPack owns context refresh, phase tracking, diff snapshots,
verification gates, repeated-failure detection, risk review, rollback patches,
acceptance evidence, handoff notes, progress files, and finish blockers. The
configured runner still owns code generation. Runner commands may emit a final
JSON line with `status`, `summary`, `files_changed`, and `blocker`; AgentPack
uses that contract to stop cleanly on `blocked` or `no_change`.

Loop diagnostics live in `.agentpack/loop_diagnosis.md`. Handoffs live in
`.agentpack/loop_handoff.md`, acceptance evidence in
`.agentpack/loop_acceptance.md`, risk notes in `.agentpack/loop_risk_review.md`,
and rollback patches in `.agentpack/loop_rollback/`. Use these files, plus
`.agentpack/loop_events.jsonl` and `.agentpack/loop_failures.jsonl`, to inspect
why a loop stopped before rerunning the agent.

Every loop writes `.agentpack/loop_runner_prompt.md` for provider-safe runner
instructions: read context, keep edits scoped, avoid commits/pushes/destructive
commands, run no hidden approval flow, and emit the final JSON contract.
Historical outcomes are appended to `.agentpack/loop_metrics.jsonl`; inspect
them with `agentpack loop-metrics` or the dashboard.
