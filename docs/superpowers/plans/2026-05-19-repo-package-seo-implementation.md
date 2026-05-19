# Repo And Package SEO Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve AgentPack discoverability across GitHub, PyPI, npm, and search results by aligning metadata, keyword lists, and first-screen README copy around the approved SEO positioning.

**Architecture:** Keep `.md`, `pyproject.toml`, and `npm/package.json` as the only edited implementation surfaces. Update metadata first so package indexes get stronger summaries and keywords, then align the root and npm README opening sections so search snippets and page visitors see the same positioning. Finish by recording the SEO work in the changelog and validating that the final copy still matches actual product scope.

**Tech Stack:** Markdown, TOML, JSON, git, ripgrep

---

### Task 1: Tighten package metadata for PyPI and npm

**Files:**
- Modify: `pyproject.toml`
- Modify: `npm/package.json`

- [ ] **Step 1: Update the Python package description and keyword list**

Replace the existing metadata block in `pyproject.toml` with:

```toml
[project]
name = "agentpack-cli"
version = "0.3.0"
description = "Local context engine for AI coding agents that ranks relevant files and builds compact task-focused context packs for Claude Code, Codex, Cursor, Windsurf, MCP, and CI workflows"
readme = "README.md"
requires-python = ">=3.10"
license = {text = "MIT"}
keywords = [
  "ai-coding-agents",
  "developer-tools",
  "repo-analysis",
  "context-engine",
  "context-packing",
  "prompt-context",
  "mcp",
  "ci",
  "claude-code",
  "codex",
  "cursor",
  "windsurf",
  "antigravity",
]
```

- [ ] **Step 2: Verify the Python metadata diff looks correct**

Run: `git diff -- pyproject.toml`
Expected: one description update and one expanded keyword list; no unrelated metadata changes

- [ ] **Step 3: Update the npm package description and keywords**

Replace the existing metadata block in `npm/package.json` with:

```json
{
  "name": "@vishal2612200/agentpack",
  "version": "0.3.0",
  "description": "Local context engine for AI coding agents. Ranks relevant files and builds compact task-focused context packs for Claude Code, Codex, Cursor, Windsurf, MCP, and CI workflows.",
  "license": "MIT",
  "homepage": "https://github.com/vishal2612200/agentpack#readme",
  "repository": {
    "type": "git",
    "url": "git+https://github.com/vishal2612200/agentpack.git",
    "directory": "npm"
  },
  "bugs": {
    "url": "https://github.com/vishal2612200/agentpack/issues"
  },
  "bin": {
    "agentpack": "bin/agentpack.js"
  },
  "files": [
    "bin/",
    "LICENSE",
    "README.md"
  ],
  "scripts": {
    "test": "node --test test/*.test.js",
    "prepack": "node test/version-sync.test.js"
  },
  "engines": {
    "node": ">=18"
  },
  "keywords": [
    "ai-coding-agents",
    "developer-tools",
    "repo-analysis",
    "context-engine",
    "context-packing",
    "prompt-context",
    "mcp",
    "ci",
    "claude-code",
    "codex",
    "cursor",
    "windsurf",
    "antigravity",
    "npm",
    "cli"
  ]
}
```

- [ ] **Step 4: Verify the npm metadata still parses**

Run: `node -e 'JSON.parse(require("fs").readFileSync("npm/package.json","utf8")); console.log("ok")'`
Expected: `ok`

- [ ] **Step 5: Commit metadata changes**

```bash
git add pyproject.toml npm/package.json
git commit -m "docs: improve package metadata for seo"
```

### Task 2: Align root README opening copy with target search terms

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Rewrite the hero sentence and opening paragraph**

Update the top of `README.md` so the opening copy explicitly says AgentPack is a local context engine for AI coding agents, names the supported agent ecosystems, and explains the benefit in terms of ranking relevant files and building compact task-focused context packs.

Use wording in this shape:

```md
**Local context engine for AI coding agents.**

AgentPack ranks relevant repository files and builds compact task-focused context packs for Claude Code, Codex, Cursor, Windsurf, Antigravity, MCP tools, CI jobs, and markdown-based LLM workflows. It scans your repo locally, compresses the result into a token budget, and keeps context fresh through CLI commands, hooks, and agent integrations.
```

- [ ] **Step 2: Add stronger discovery phrasing near the top**

Ensure the first screen of `README.md` includes these search concepts in natural prose or headings:

```text
repo analysis
MCP-first workflow
CI jobs
local/offline
relevant files
compact context packs
```

- [ ] **Step 3: Keep product boundaries explicit**

Keep or tighten the product-boundary sentence so it remains close to:

```md
AgentPack is a context preparation tool, not a coding agent.
```

- [ ] **Step 4: Verify the new opening section**

Run: `sed -n '1,40p' README.md`
Expected: first screen contains both problem terms (`AI coding agents`, `repo analysis`, `context packs`) and tool terms (`Claude Code`, `Codex`, `Cursor`, `Windsurf`, `MCP`, `CI`)

- [ ] **Step 5: Commit the root README update**

```bash
git add README.md
git commit -m "docs: align root readme for discovery"
```

### Task 3: Align npm README and supporting docs with the same positioning

**Files:**
- Modify: `npm/README.md`
- Modify: `src/agentpack/data/agentpack.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Rewrite the npm README opening to match the root README positioning**

Update the first 20-30 lines of `npm/README.md` so it uses the same positioning as the root README, while keeping npm-wrapper-specific wording. The opening should say AgentPack is a local context engine for AI coding agents and mention file ranking, compact context packs, MCP, and CI workflows.

Use wording in this shape:

```md
**Local context engine for AI coding agents.**

AgentPack ranks relevant repository files and builds compact task-focused context packs for Claude Code, Codex, Cursor, Windsurf, Antigravity, MCP tools, CI jobs, and markdown-based LLM workflows.
```

- [ ] **Step 2: Align the embedded install fallback copy**

Update `src/agentpack/data/agentpack.md` so the installation fallback wording still matches the current preferred install story (`pipx install agentpack-cli`) and does not contradict the README positioning.

Target line:

```bash
agentpack --help 2>/dev/null || pipx install agentpack-cli
```

- [ ] **Step 3: Record the SEO/discovery pass in the changelog**

Add or expand the `Unreleased` notes in `CHANGELOG.md` with an entry in this shape:

```md
### Changed
- Improved GitHub, PyPI, and npm discovery copy by aligning repo/package descriptions, keywords, and README openings around AgentPack's local context engine positioning.
```

- [ ] **Step 4: Validate docs and metadata together**

Run: `rg -n "Local context engine|AI coding agents|MCP|CI workflows|context packs" README.md npm/README.md pyproject.toml npm/package.json CHANGELOG.md`
Expected: aligned phrasing appears across metadata and both README files without obvious contradiction

- [ ] **Step 5: Commit supporting doc changes**

```bash
git add npm/README.md src/agentpack/data/agentpack.md CHANGELOG.md
git commit -m "docs: align npm docs and changelog for seo"
```

### Task 4: Final verification and handoff notes

**Files:**
- Modify: none

- [ ] **Step 1: Review the final diff**

Run: `git diff -- README.md npm/README.md pyproject.toml npm/package.json CHANGELOG.md src/agentpack/data/agentpack.md`
Expected: only SEO/discovery wording, keyword, and install-alignment changes

- [ ] **Step 2: Re-parse package metadata**

Run: `python - <<'PY'\nimport tomllib\nfrom pathlib import Path\nwith Path('pyproject.toml').open('rb') as fh:\n    data = tomllib.load(fh)\nprint(data['project']['description'])\nprint(','.join(data['project']['keywords'][:4]))\nPY`
Expected: prints the new Python package description and the first keyword values without parse errors

- [ ] **Step 3: Note manual GitHub follow-up**

Record the manual GitHub UI values to apply after merge:

```text
Description: Local context engine for AI coding agents. AgentPack ranks relevant files and builds compact task-focused context packs for Claude Code, Codex, Cursor, Windsurf, MCP, and CI workflows.

Topics: ai-coding-agent, ai-developer-tools, context-engine, prompt-context, repo-analysis, code-analysis, claude-code, codex, cursor, windsurf, mcp, ci, python, npm
```

- [ ] **Step 4: Final commit if verification required changes**

```bash
git add README.md npm/README.md pyproject.toml npm/package.json CHANGELOG.md src/agentpack/data/agentpack.md
git commit -m "docs: finalize seo alignment verification"
```
