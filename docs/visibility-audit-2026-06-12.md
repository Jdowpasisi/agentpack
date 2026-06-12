# AgentPack Search And AI Visibility Audit

Date: 2026-06-12
Scope: GitHub repository, root README, docs, PyPI metadata, npm metadata, and search/AI-result readiness.

## Executive Summary

AgentPack is discoverable for branded or exact queries, but weak for generic intent queries such as "AI coding agent context engine", "repo context packing", "Claude Code context engine", and "MCP context tool". The main causes are metadata drift, no crawlable documentation site, thin intent pages, and limited external authority signals.

Highest-impact fixes:

1. Publish current PyPI metadata with project URLs and aligned description.
2. Move docs from GitHub-only markdown to a crawlable documentation site with canonical URLs, sitemap, metadata, and JSON-LD.
3. Expand first-party intent pages with real comparisons, examples, screenshots, benchmark evidence, and installation snippets.
4. Align GitHub, PyPI, npm, README, docs, and social launch copy around one phrase set: "local context engine for AI coding agents".
5. Build external links from high-trust developer surfaces: release posts, Hacker News/Reddit discussions, benchmark writeups, comparison posts, and package registry links.

## Evidence Before Remediation

- GitHub API shows repo is public, recently pushed, and has 19 stars. Description is present but still leads with "Local MCP context router", which is narrower than user search language.
- PyPI live metadata is behind the repo: PyPI shows `0.3.20`, no `project_urls`, and summary "Local MCP context router..." while local repo is `0.3.21`.
- npm live metadata is current at `0.3.21`, but description says "npm launcher..." first, so package search relevance is weaker than product positioning.
- Root README first screen was concise, but less keyword-complete than `npm/README.md`; it omitted "compact task-focused context packs" and "local context engine" in the first visible paragraph.
- Docs are plain GitHub markdown. There is no `mkdocs.yml`, sitemap, robots file, canonical URL, title/meta description layer, Open Graph metadata, or structured data.
- Existing search-intent docs exist, but most are short and underdeveloped. They read like notes, not standalone pages that can win search snippets or AI citations.

## Priority Findings

### P0: Publish PyPI Metadata Fix

Current live PyPI record lacks project URLs and still exposes older copy. Add `[project.urls]` to `pyproject.toml`, then publish the current version.

Repo-side status: fixed in `pyproject.toml`. Remaining external step: publish the next PyPI release so live package metadata updates.

Recommended URLs:

```toml
[project.urls]
Homepage = "https://github.com/vishal2612200/agentpack"
Documentation = "https://github.com/vishal2612200/agentpack/tree/main/docs"
Repository = "https://github.com/vishal2612200/agentpack"
Issues = "https://github.com/vishal2612200/agentpack/issues"
Changelog = "https://github.com/vishal2612200/agentpack/blob/main/CHANGELOG.md"
```

Also change summary to:

```text
Local context engine for AI coding agents that ranks relevant repo files and builds compact task-focused context packs for Claude Code, Codex, Cursor, Windsurf, MCP, and CI workflows.
```

### P0: Create Crawlable Docs Site

GitHub markdown can rank, but search engines and AI systems get stronger signals from stable documentation pages with titles, descriptions, canonical URLs, internal navigation, and sitemap coverage.

Recommended path:

- Add MkDocs Material or equivalent static docs.
- Host on GitHub Pages at `https://vishal2612200.github.io/agentpack/` or a custom domain.
- Add `site_url`, page titles, meta descriptions, canonical URLs, sitemap, robots.txt, and Open Graph metadata.
- Link docs site from GitHub repo homepage, PyPI project URLs, npm homepage/readme, and README badges/links.

Repo-side status: fixed with `mkdocs.yml`, docs requirements, robots file, JSON-LD helper, and GitHub Pages workflow. Remaining external step: ensure GitHub Pages is enabled for Actions deployment and submit the sitemap in Search Console.

### P1: Fix Top-Of-Funnel Copy Drift

Current surfaces use mixed labels:

- "Local MCP context router"
- "Local context router"
- "local context engine"
- "context packing tool"

Pick one primary entity phrase and repeat it naturally across top surfaces:

```text
AgentPack is a local context engine for AI coding agents.
```

Use supporting phrases consistently:

- ranks relevant repository files
- compact task-focused context packs
- Claude Code, Codex, Cursor, Windsurf
- MCP tools and CI workflows
- local/offline repo analysis
- no embeddings or hosted indexing

Repo-side status: fixed across package metadata, root README, npm README, docs index, and search-intent pages.

### P1: Rewrite Intent Pages Into Real Search Assets

These pages exist but are too thin:

- `docs/claude-code-context-engine.md`
- `docs/mcp-context-engine.md`
- `docs/cursor-context-packing.md`
- `docs/ai-coding-agent-context.md`
- `docs/reduce-claude-code-token-usage.md`
- `docs/agentpack-vs-repomix.md`
- `docs/agentpack-vs-augment-context-engine.md`

Each should become a 900-1,500 word page with:

- Exact problem statement.
- Short answer paragraph.
- Install command.
- Before/after workflow.
- Screenshot or terminal output.
- Benchmark or evidence block.
- Comparison table where relevant.
- Links to related docs and package pages.
- Clear "what AgentPack is not" boundary.

Repo-side status: first pass complete. Pages now have metadata, stronger search-intent framing, install snippets, workflow examples, evidence blocks, comparisons, and boundaries.

### P1: Add Structured Data Once Site Exists

For docs site pages, add JSON-LD:

- `SoftwareApplication` for homepage/product page.
- `TechArticle` for guides.
- `BreadcrumbList` for navigation.
- `FAQPage` only when visible FAQ content exists.

Use JSON-LD and keep structured data aligned with visible page text.

Repo-side status: fixed with `docs/assets/seo-schema.js`, included by `mkdocs.yml`.

### P2: Add AI-Citation-Friendly Files

Google says AI features do not require special AI files, but other AI retrieval systems may still use concise machine-readable docs. Add these as helper files, not as SEO replacement:

- `/llms.txt`: canonical product summary plus best links.
- `/llms-full.txt`: docs map with short page summaries.
- `docs/agentpack-for-ai-agents.md`: explicit "what to cite" page with factual claims and links.

Keep claims verifiable and short.

Repo-side status: fixed with root and docs-site copies of `llms.txt` and `llms-full.txt`, plus `docs/agentpack-for-ai-agents.md`.

### P2: Improve Repository Authority Signals

Search ranking is likely authority-limited because repo is new and has few external references.

Recommended actions:

- Publish release post for `0.3.21` with benchmark table and methodology.
- Post comparison articles: "AgentPack vs Repomix", "Claude Code context engine", "MCP context engine for coding agents".
- Ask early users to link from blog posts, READMEs, curated lists, and tool directories.
- Add GitHub topics: `ai-coding-agent`, `ai-developer-tools`, `context-engine`, `repo-analysis`, `mcp`, `claude-code`, `codex`, `cursor`, `windsurf`, `python`, `npm`, `cli`.
- Submit package to relevant lists after docs site exists.

## Search Query Targets

Primary:

- local context engine for AI coding agents
- AI coding agent context packing
- Claude Code context engine
- Codex context packing
- Cursor context packing
- MCP context engine
- repo analysis for LLMs

Secondary:

- reduce Claude Code token usage
- task-focused context packs
- local repo context for coding agents
- agent context router
- repo map for AI coding agents

Comparison:

- AgentPack vs Repomix
- AgentPack vs Augment Context Engine
- context packing vs repo dump

## Implementation Plan

1. Patch metadata: `pyproject.toml`, `npm/package.json`, root README opening, npm README opening, changelog.
2. Publish PyPI `0.3.21` or `0.3.22` so live package metadata matches repo.
3. Add docs site scaffold, sitemap, robots, titles, descriptions, and first 7 intent pages.
4. Add `llms.txt` and `llms-full.txt` after docs site URLs are stable.
5. Update GitHub repo homepage to docs site, not PyPI.
6. Use Google Search Console after docs site launch. Submit sitemap and inspect key URLs.
7. Track ranking weekly for the query targets above, plus branded query `agentpack-cli`.

## Source Notes

- Google SEO Starter Guide: https://developers.google.com/search/docs/fundamentals/seo-starter-guide
- Google AI features guidance: https://developers.google.com/search/docs/appearance/ai-features
- Google sitemap guidance: https://developers.google.com/search/docs/crawling-indexing/sitemaps/overview
- Google structured data guidance: https://developers.google.com/search/docs/appearance/structured-data/intro-structured-data
- Google helpful content guidance: https://developers.google.com/search/docs/fundamentals/creating-helpful-content
