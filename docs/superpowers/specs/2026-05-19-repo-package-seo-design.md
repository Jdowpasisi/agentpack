# Repo And Package SEO Design

Date: 2026-05-19
Project: AgentPack
Scope: GitHub repo presentation, PyPI metadata, npm metadata, README discovery copy

## Goal

Improve discoverability for AgentPack across GitHub, Google, PyPI, and npm without changing package names, repository slug, or product positioning. The optimization should target both problem-oriented searches and tool-oriented searches while keeping the copy technically accurate.

Primary search intent clusters:

- AI coding agent context
- local context engine
- repo analysis for LLMs
- task-focused context packing
- MCP tools and workflows
- CI context generation
- Claude Code, Codex, Cursor, Windsurf, Antigravity integrations

## Non-Goals

- Renaming the repository or published packages
- Rewriting the full documentation architecture
- Changing command behavior or product scope
- Adding marketing claims that are not already supported by the product

## Current State

AgentPack already has strong technical documentation, but the top metadata surfaces are still somewhat generic:

- Package descriptions emphasize "task-aware context packing" but underuse high-intent search terms such as `repo analysis`, `MCP`, `CI`, and `local context engine`.
- Keyword arrays are short and skewed toward tool names more than user problems and outcomes.
- README openings explain the product well, but the first-screen copy can be more tightly aligned with common search phrasing.
- GitHub topics and repository description are not stored in-repo, so they need explicit recommended values.

## Audience

Primary audiences:

- Developers using AI coding agents on medium or large repositories
- Teams evaluating tooling for Claude Code, Codex, Cursor, Windsurf, or Antigravity
- Users searching for MCP-compatible context tools
- CI and automation users who want generated context per task or per PR

Secondary audiences:

- JavaScript-heavy teams looking for an npm-installable wrapper
- Python users browsing PyPI for local AI developer tools

## Recommended Approach

Use a full-alignment SEO pass across metadata and top-of-funnel documentation.

This means:

- Align repository description, Python package description, npm package description, and README hero copy around the same core phrase set.
- Cover both benefit keywords and integration keywords in the first screen of the root README and npm README.
- Expand metadata keywords to include user-intent phrases, not only product/integration names.
- Keep wording specific and measurable: rank relevant files, build compact context packs, local/offline repo analysis, MCP and CI support.

## Messaging Strategy

### Primary positioning

AgentPack is a local context engine for AI coding agents that ranks relevant repository files and builds compact task-focused context packs.

### Supporting proof points

- Local and deterministic
- Task-aware ranking
- Budget-aware compression
- MCP-compatible workflow
- CI-friendly output
- Multi-agent integration support

### Search term balance

Every top-level surface should balance:

- Problem terms: `AI coding agents`, `repo analysis`, `context engine`, `context packs`, `MCP`, `CI`, `developer tools`
- Brand/tool terms: `Claude Code`, `Codex`, `Cursor`, `Windsurf`, `Antigravity`

## Files And Surfaces To Update

In-repo files:

- `README.md`
- `npm/README.md`
- `pyproject.toml`
- `npm/package.json`
- `CHANGELOG.md`
- `src/agentpack/data/agentpack.md` if install/discovery wording should stay aligned

Out-of-repo surfaces to recommend manually:

- GitHub repository description
- GitHub topics
- PyPI project summary consistency check after publish
- npm package sidebar consistency check after publish

## Planned Copy Changes

### Metadata

Update Python and npm descriptions so they clearly say:

- local context engine
- AI coding agents
- ranks relevant files
- builds compact context packs
- supports MCP and CI

Expand keyword arrays with terms such as:

- `ai-coding-agents`
- `developer-tools`
- `repo-analysis`
- `context-engine`
- `prompt-context`
- `mcp`
- `ci`
- `claude-code`
- `codex`
- `cursor`
- `windsurf`

### Root README

Tighten the first 100-150 words so they answer:

1. What is AgentPack?
2. Who is it for?
3. Why is it different from repo dumpers or generic code search?
4. Which ecosystems and agent tools does it support?

Use headings and early copy that contain strong discovery phrases:

- `Local context engine for AI coding agents`
- `MCP-first workflow`
- `CI per-PR context`
- `Repo analysis and ranking`

### npm README

Keep npm-specific framing, but align the opening language with the root README so search snippets and package previews reinforce the same positioning.

## Recommended GitHub Metadata

Repository description:

`Local context engine for AI coding agents. AgentPack ranks relevant files and builds compact task-focused context packs for Claude Code, Codex, Cursor, Windsurf, MCP, and CI workflows.`

Suggested GitHub topics:

- `ai-coding-agent`
- `ai-developer-tools`
- `context-engine`
- `prompt-context`
- `repo-analysis`
- `code-analysis`
- `claude-code`
- `codex`
- `cursor`
- `windsurf`
- `mcp`
- `ci`
- `python`
- `npm`

## Risks And Mitigations

Risk: keyword stuffing makes the copy feel synthetic.
Mitigation: keep the primary sentence human-readable and limit repeated brand-name lists.

Risk: metadata drifts from actual product capability.
Mitigation: only use terms already supported by documented workflows.

Risk: npm and PyPI descriptions diverge again.
Mitigation: align wording in this pass and keep release-time review explicit.

## Validation

The update is successful if:

- Root README first screen is clearer and richer in high-intent keywords.
- `pyproject.toml` and `npm/package.json` descriptions and keyword lists reflect both problem and integration terms.
- npm README and root README openings are directionally aligned.
- CHANGELOG notes the SEO/discovery improvement.
- Manual GitHub description/topics guidance is ready for application.

## Implementation Notes

- Prefer concise, search-friendly wording over broad marketing copy.
- Do not change package names or URLs.
- Preserve technical credibility; avoid unsupported claims like "best" or "industry-leading".
- Keep the project positioned as a context preparation tool, not a coding agent.
