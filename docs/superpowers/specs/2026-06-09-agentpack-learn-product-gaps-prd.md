# AgentPack Learn Product Gaps PRD

## Problem Statement

AgentPack Learn has a local-first MVP that turns task context and git changes into learning notes, daily summaries, skill progress, feedback logs, and compact future-agent lessons. The remaining product gap is that it still behaves mostly like a deterministic artifact generator, not a durable learning layer for the developer and the AI coding agent.

Developers using AI coding agents can finish work without understanding the concepts, repo patterns, tradeoffs, and tests behind that work. Agents can also repeat avoidable mistakes because prior task lessons are not ranked by relevance, feedback, or confidence. AgentPack Learn should close both loops: help the developer learn from the task and help the next agent use accepted repo-specific lessons.

## Solution

AgentPack Learn should evolve around five pillars:

1. Higher-quality task understanding through grounded summaries, optional provider-ready payloads, and deterministic local fallback.
2. Durable developer skill memory with evidence, confidence, recency, weak areas, and next drills.
3. Feedback-driven improvement through helpful/not-helpful signals, skill rename/merge/suppress actions, and lesson suppression.
4. Workflow-native surfaces for PR comments, CI quality checks, provider previews, skill views, and practice drills.
5. Team learning without surveillance by keeping personal skill history local and making shared lessons opt-in.

## User Stories

1. As a developer, I want a post-task explanation of what changed, so that I understand the implementation instead of only accepting generated code.
2. As a developer, I want each learning card to cite changed files and tests, so that I can verify the explanation is grounded.
3. As a developer, I want Learn to separate "what the agent did" from "what I should learn", so that the output is not just a PR summary.
4. As a developer, I want a skill-memory view, so that I can inspect what I have practiced across tasks.
5. As a developer, I want stale or weak skills surfaced as drills, so that learning turns into action.
6. As a developer, I want to mark output helpful or not helpful, so that future output adapts.
7. As a developer, I want to rename, merge, or suppress skills, so that my learning history uses useful language.
8. As a developer, I want to preview the provider payload, so that optional LLM refinement remains explicit and private.
9. As a reviewer, I want a PR learning comment, so that I can see concepts, risks, and next practice without productivity scoring.
10. As an AI coding agent, I want compact accepted lessons ranked by relevance, so that future context stays useful.
11. As a maintainer, I want a CI quality mode, so that generic or ungrounded learning output fails loudly.
12. As a team lead, I want optional shared lessons without personal telemetry, so that team learning does not become surveillance.

## Implementation Decisions

- Keep local deterministic generation as the default behavior.
- Add provider-preview output before any provider-backed generation is added.
- Treat feedback as local JSONL and apply it during future report generation.
- Evolve `skills-progress.json` into a skill memory with confidence, first/last seen timestamps, source paths, related tests, aliases, corrections, and suppression.
- Rank future-agent lessons using status, evidence, current-task relevance, and feedback.
- Add CLI views instead of a separate package: skill summary, drills, provider preview, and CI quality report.
- Keep personal skill history gitignored by default.
- Keep team-sharing out of automatic behavior; only explicit exports or selected committed lesson files should be shared.

## Testing Decisions

- Test behavior and state, not exact prose.
- Verify feedback can suppress skills, mark lessons accepted, and rename concepts.
- Verify skill memory accumulates evidence, confidence, source paths, and practice drills.
- Verify CLI view modes do not write default learning output unless intended.
- Verify CI quality mode reports score and can fail on low quality.
- Verify provider preview makes no network call and prints bounded changed-file evidence.

## Out of Scope

- Hosted dashboard.
- Mandatory LLM-backed generation.
- Developer productivity scoring.
- Ranking developers.
- Automatic upload of personal learning history.
- Full native IDE plugins.
- Broad codebase wiki generation unrelated to current task evidence.

## Success Metrics

- Most learning cards and agent lessons cite changed-file evidence.
- Feedback changes future output without requiring repeated correction.
- Skill views show confidence, task count, and evidence paths.
- Practice drills are generated from real skill memory.
- Provider preview is available before any network-backed learning mode.
- CI quality mode catches generic output.

## Further Notes

The product category should be local learning memory for AI-assisted development. The differentiator is the dual loop: the developer learns from the task, and future coding agents inherit compact, accepted, repo-specific lessons.
