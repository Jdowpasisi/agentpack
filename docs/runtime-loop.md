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

## Boundaries

AgentPack does not proxy LLM traffic, rewrite provider requests, or replace raw
logs as source of truth. Retrieval uses the latest local pack registry, supports
symbol-level block IDs when the latest pack contains symbols, and refuses stale
full-file reads unless explicitly allowed.
