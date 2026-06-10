# AgentPack Learn Product Gaps PRD

## Problem Statement

AgentPack Learn exists as a local-first command that turns task context and git changes into learning notes, daily summaries, skill progress, feedback logs, and compact lessons for future agents. The current version proves the direction, but it still behaves like a deterministic artifact generator more than a durable learning product.

Developers using AI coding agents still face the core problem: work gets completed, but the developer does not reliably understand the concepts, repo patterns, tradeoffs, and testing practices behind the work. The AI agent also does not consistently learn from prior tasks in a way that changes future execution. Without a richer product layer, AgentPack Learn can be mistaken for a journal, PR summary, or static documentation generator.

The product gap is to make AgentPack Learn a learning layer for both the developer and the AI coding agent: it should capture what changed, explain why it matters, track skill growth over time, use feedback to improve future output, surface learning in the coding workflow, and preserve AgentPack's local-first privacy posture.

## Solution

AgentPack Learn should evolve into a local learning system with five product pillars:

1. Higher-quality task understanding
   - Add optional provider-backed learning generation while keeping deterministic offline mode as the default fallback.
   - Ground every explanation in task context, changed files, tests, and prior agent lessons.
   - Produce explanations that teach concepts, not just summarize activity.

2. Durable developer skill memory
   - Turn the current skill map into a time-series learning profile.
   - Track concepts, evidence paths, confidence, recency, repeated practice, weak areas, and next drills.
   - Make learning progress queryable through CLI views and exportable artifacts.

3. Feedback-driven improvement
   - Use helpful/not-helpful feedback to tune future summaries.
   - Let developers correct concepts, rename skills, mark generated cards as too generic, and suppress noisy lessons.
   - Feed accepted corrections back into future learning output and future agent context.

4. Workflow-native surfaces
   - Add outputs intended for PR comments, daily standups, IDE panels, agent prompts, and CI checks.
   - Let developers run Learn after a task, across today's work, against a branch, or as a pre-PR learning pass.
   - Make learning available where developers already work instead of only as files under `.agentpack`.

5. Team learning without surveillance
   - Support optional team-shared lesson packs and skill taxonomies.
   - Share patterns and repo lessons without exposing private diffs or measuring individual productivity.
   - Keep personal skill history private unless the user explicitly exports it.

## User Stories

1. As a developer using an AI coding agent, I want a post-task explanation of what changed, so that I understand the implementation instead of only accepting generated code.
2. As a developer, I want Learn to explain the core concepts used in a task, so that I can recognize those concepts in future work.
3. As a developer, I want each learning card to cite changed files and tests, so that I can verify the explanation is grounded.
4. As a developer, I want Learn to separate "what the agent did" from "what I should learn", so that the output is not just a PR summary.
5. As a developer, I want a daily summary of learning themes, so that I can see what I practiced today.
6. As a developer, I want a weekly view of repeated concepts, so that I can see which skills are becoming stronger.
7. As a developer, I want Learn to identify weak spots and missing tests, so that I know what to practice next.
8. As a developer, I want short quiz questions from my own code changes, so that I can test whether I understood the task.
9. As a developer, I want practice prompts based on the exact repo patterns I touched, so that follow-up learning is relevant.
10. As a developer, I want to mark a learning card helpful, so that similar future cards can be prioritized.
11. As a developer, I want to mark a learning card not helpful, so that generic or wrong explanations stop repeating.
12. As a developer, I want to edit a generated concept name, so that my skill map uses language I understand.
13. As a developer, I want to merge duplicate skills, so that my progress view does not fragment one concept into many names.
14. As a developer, I want to hide noisy skills, so that generated output stays focused.
15. As a developer, I want Learn to remember accepted feedback, so that future reports improve without repeated correction.
16. As a developer, I want a CLI command to show my top skills by evidence, so that I can inspect progress quickly.
17. As a developer, I want a CLI command to show stale skills, so that I know what I have not practiced recently.
18. As a developer, I want a CLI command to show next recommended drills, so that learning turns into action.
19. As a developer, I want Learn to work offline, so that I can use it in private repos without provider dependency.
20. As a developer, I want optional LLM-backed explanations, so that I can get richer teaching when I allow it.
21. As a developer, I want bounded diffs and redaction in LLM-backed mode, so that private data is protected.
22. As a team lead, I want repo-specific agent lessons to accumulate, so that future agent sessions follow team patterns.
23. As a team lead, I want shared repo lessons without personal skill telemetry, so that team learning does not become surveillance.
24. As a team lead, I want Learn to identify recurring onboarding concepts, so that docs and mentoring can target real work.
25. As a reviewer, I want a PR learning comment, so that I can see what the author practiced and what patterns the agent learned.
26. As a reviewer, I want PR learning comments to avoid productivity scoring, so that the tool supports growth rather than evaluation.
27. As an AI coding agent, I want compact accepted lessons from previous tasks, so that I avoid repeating repo-specific mistakes.
28. As an AI coding agent, I want negative lessons from rejected outputs, so that I do not keep applying bad patterns.
29. As an AI coding agent, I want lessons ranked by relevance to the current task, so that context stays small.
30. As an AI coding agent, I want stale or low-confidence lessons excluded, so that old guidance does not pollute current work.
31. As a security-conscious user, I want Learn to show what content would be sent to a provider, so that I can approve or deny it.
32. As a security-conscious user, I want local-only mode to be the default, so that adoption is safe for private repositories.
33. As a documentation owner, I want generated learning themes to reveal missing docs, so that docs improve from real developer tasks.
34. As a CLI user, I want machine-readable JSON exports, so that external tools can build dashboards or reports.
35. As a CLI user, I want Markdown output to remain stable, so that generated files are easy to review and diff.
36. As a new contributor, I want Learn to explain repo conventions after my first task, so that I learn local architecture faster.
37. As a maintainer, I want quality gates for generic output, so that Learn fails loudly when it cannot teach anything useful.
38. As a maintainer, I want tests around learning extraction and feedback behavior, so that improvements do not regress groundedness.
39. As a maintainer, I want provider-backed mode isolated behind an interface, so that offline mode remains reliable.
40. As a maintainer, I want all learning artifacts ignored by default unless explicitly exported, so that private notes do not leak into git.

## Implementation Decisions

- Build around a two-engine model:
  - deterministic offline extractor remains the default and baseline
  - optional provider-backed teaching engine improves explanations when configured

- Introduce a learning engine interface with a stable input and output contract:
  - input: task, bounded changed files, redacted snippets, tests touched, pack-selected files, prior accepted lessons, feedback signals, and config
  - output: learning cards, skill evidence, quiz questions, practice prompts, agent lessons, quality findings, and provenance

- Keep provider-specific logic behind adapters:
  - local deterministic adapter
  - future OpenAI or compatible LLM adapter
  - no provider code should leak into CLI command orchestration or renderers

- Evolve the skill map from "latest evidence by skill" into a skill memory:
  - skill id
  - display name
  - aliases
  - confidence
  - first seen
  - last seen
  - evidence count
  - task evidence
  - source paths
  - related tests
  - accepted corrections
  - suppressed status

- Add feedback as a first-class domain concept:
  - feedback targets learning cards, skills, quiz questions, and agent lessons
  - feedback can be binary, corrective, suppressive, or rename/merge oriented
  - feedback is stored locally and applied during future generation

- Add a lesson ranking layer for future context packs:
  - accepted lessons outrank generated-only lessons
  - task-relevant lessons outrank generic lessons
  - stale lessons decay unless reinforced
  - suppressed lessons are never injected

- Add learning views as CLI surfaces:
  - current task report
  - today summary
  - skill map summary
  - weak areas
  - next drills
  - agent lessons
  - export JSON

- Add workflow-native outputs:
  - PR learning comment
  - daily standup summary
  - agent prompt snippet
  - CI quality report
  - dashboard-ready JSON

- Preserve privacy and local-first behavior:
  - no network call unless explicitly configured
  - bounded snippets by default
  - redaction before provider calls
  - dry-run/provider-preview before sending content
  - generated artifacts ignored unless user opts into committing exports

- Keep team mode opt-in:
  - shared repo lessons and shared skill taxonomy can be committed
  - personal skill history stays local by default
  - team reports should avoid individual productivity metrics

- Prefer deep modules that are independently testable:
  - learning input collection
  - learning generation engine
  - feedback application
  - skill memory update
  - lesson ranking
  - privacy/provenance validation
  - renderers/exporters

## Testing Decisions

- Test external behavior, not internal phrasing. Assertions should focus on groundedness, provenance, privacy boundaries, ranking behavior, and persisted state.

- Learning engine tests:
  - deterministic engine returns bounded cards, quiz questions, skill evidence, and agent lessons
  - provider-backed engine can be tested with a fake provider response
  - provider failure falls back cleanly or reports an actionable error

- Feedback tests:
  - helpful feedback raises similar evidence priority
  - not-helpful feedback suppresses repeated generic output
  - rename feedback updates future skill display names
  - merge feedback consolidates duplicate skills
  - suppressed lessons are not injected into context packs

- Skill memory tests:
  - repeated evidence increases confidence
  - stale skills decay or appear in practice recommendations
  - evidence remains linked to task and source paths
  - local personal data is not included in shared exports by default

- Lesson ranking tests:
  - current task relevance affects injected lessons
  - accepted lessons outrank generated-only lessons
  - stale and suppressed lessons are excluded
  - context injection remains bounded

- Privacy tests:
  - provider preview shows bounded outgoing payload
  - redaction happens before provider calls
  - local-only mode performs no network calls
  - generated learning files remain ignored by default

- CLI tests:
  - task report writes expected Markdown and JSON
  - today summary aggregates calendar-day work
  - skill views display useful summaries
  - PR comment output is concise and grounded
  - CI quality mode fails on generic or ungrounded learning output

- Regression tests:
  - existing pack behavior still includes only bounded accepted lessons
  - existing `agentpack init` ignore behavior remains stable
  - existing release checks include learning tests without requiring provider credentials

## Out of Scope

- Replacing code review tools.
- Measuring developer productivity.
- Ranking developers.
- Uploading personal learning history by default.
- Building a hosted SaaS backend in this phase.
- Building a full web dashboard in the first implementation pass.
- Making LLM-backed generation mandatory.
- Generating broad codebase documentation unrelated to the current task.
- Supporting every IDE through native plugins immediately.

## Success Metrics

- At least 80 percent of generated learning cards cite changed files or tests.
- At least 70 percent of developer feedback on learning cards is helpful after the first correction loop.
- Future context packs include fewer than the configured maximum agent lessons while preserving relevance.
- Local-only mode remains fully functional.
- Provider-backed mode never sends unredacted or unbounded diffs.
- Developers can answer generated quiz questions using only the linked changed files and summary.
- A developer can inspect top skills, stale skills, and next drills from the CLI.

## Further Notes

The competitive edge is not "summarize my day." The product should own a sharper category: local learning memory for AI-assisted development. The developer learns from the task, and the next AI agent receives compact, accepted, repo-specific lessons. That dual learning loop is the moat.

The next implementation plan should sequence this as:

1. skill memory schema and views
2. feedback application
3. lesson ranking
4. provider-backed learning engine
5. PR/CI workflow outputs
6. optional team-shared lessons
