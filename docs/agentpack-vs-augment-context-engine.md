# AgentPack vs Augment Context Engine

AgentPack and Augment Context Engine both address coding-agent context, but they make different product tradeoffs.

## Main difference

| Need | Better fit |
|---|---|
| Local open-source CLI for one repo | AgentPack |
| MCP task routing without cloud indexing | AgentPack |
| No embeddings or vector database required | AgentPack |
| Multi-repo and external documentation indexing | Augment Context Engine |
| Hosted/team product workflow | Augment Context Engine |
| Benchmark expected-file recall from local tasks | AgentPack |

## AgentPack focus

AgentPack prepares task-specific context packs from local repo signals. It is meant for developers who want explainable file ranking, read-only task routing, markdown fallback artifacts, and benchmark tooling without sending repo data to a hosted indexer.

```bash
agentpack route --task "fix billing webhook retry handling"
```

## Augment focus

Augment Context Engine is a commercial context engine with MCP support, semantic code search, and broader indexing workflows. It may be a better fit when a team wants shared indexing across repositories, docs, and internal sources.

Choose based on workflow: local task router and benchmarkable context packs, or a broader indexed context platform.
