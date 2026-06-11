# How AgentPack Works

AgentPack is a local context router. It does not upload your repo or require embeddings to build a pack. The default path is deterministic and offline: scan the working tree, rank likely-relevant files, compress them into a budget, cache expensive local work, and let agents retrieve more detail when needed.

## Pipeline

1. **Scan**

   AgentPack reads packable files after `.agentignore` and generated-file filters. It records paths, sizes, language hints, imports, symbols, test relationships, git state, and lightweight repo-map signals.

2. **Rank**

   The ranker scores files against the active task using filename/path matches, symbols, imports, related tests, changed files, repo history, offline summaries, and configuration signals. This produces a prioritized map, not a claim that the top file is always sufficient.

3. **Compress**

   AgentPack chooses a render mode for each selected file:

   | Mode | Use |
   |---|---|
   | `full` | Small or highly relevant files where the body matters |
   | `diff` | Changed files where the current patch is the useful context |
   | `symbols` | Files where signatures and structure are enough to orient |
   | `skeleton` | Large files where names, classes, functions, and calls are enough |
   | `summary` | Low-priority or very large files that still need a breadcrumb |

   The pack is budget-aware: changed files, tests, docs, and direct dependencies get reserve buckets before lower-confidence context.

4. **Cache**

   AgentPack caches local summaries, repo snapshots, pack metadata, and skill indexes under `.agentpack/`. Cache keys include file hashes, schema or generator versions, and source fingerprints so stale context can be detected and refreshed.

5. **Retrieve**

   Packs include block IDs and receipts. Agents can use the generated context as a compact map, then read exact files or use registry-backed retrieval when a summary or skeleton is not enough.

6. **Route**

   `agentpack route --task "..."` and the MCP router return likely files, scoped rules, installed skills, commands, and safety warnings without writing a full context pack. Skill routing uses explicit metadata first, then local text signals such as BM25-style domain scoring and dynamic keyphrase triggers.

7. **Measure**

   `agentpack benchmark` scores expected-file recall, token precision, pack size, misses, and skill routing metrics. Benchmark cases can include `expected_skills` and `avoid_skills` to catch weak skill keywords or noisy skill recommendations.

## Stable Prefix Caching

Rendered packs keep stable instructions before volatile data such as timestamps, git SHAs, task text, and selected-file tables. This does not create a provider cache by itself, but it makes repeated prompts friendlier to provider prompt-prefix caching because the beginning of the prompt remains byte-stable across refreshes.

The practical rule is:

- stable instructions first
- volatile task and repo state later
- file blocks in deterministic order
- no random IDs or timestamps in the prefix

This can reduce cost on providers that discount cached prefix reads, while keeping AgentPack provider-agnostic.

## Skill Keyword Quality

Skill discovery stores triggers in `.agentpack/skills_index.json`. AgentPack now prefers description-backed keyphrases over generic single words. For example:

| Weak trigger | Better trigger |
|---|---|
| `any` | `manual-pack` |
| `another` | `transferable-skill` |
| `actionable` | `code-quality-check` |
| `building` | `graphql-schema` |

Use benchmark cases to keep this quality from regressing:

```toml
[[cases]]
task = "review this PR for SQL injection, XSS, and code quality"
expected_skills = ["code-reviewer"]
avoid_skills = ["frontend-review"]

[[cases]]
task = "translate my retail operations experience into a software resume"
expected_skills = ["Career Changer Translator"]
avoid_skills = ["generic-writing"]
```

Then run:

```bash
agentpack benchmark --misses
```

The output and `.agentpack/benchmark_results.jsonl` include `skill_recall_at_3`, `skill_precision_at_3`, `skill_mrr`, `skill_noise_rate`, and `selected_skills`.

## Hybrid Search Direction

The default router should stay dependency-free. A good future shape is hybrid retrieval:

- BM25/keyphrase matching for exact terms such as `graphql`, `sql injection`, or `agentpack`
- optional semantic search when an embedding provider or local vector index is configured
- reciprocal-rank or weighted fusion to merge lexical and semantic candidates
- deterministic fallback to the current local BM25/keyphrase path when embeddings are unavailable

That gives better intent matching without bloating normal installs.
