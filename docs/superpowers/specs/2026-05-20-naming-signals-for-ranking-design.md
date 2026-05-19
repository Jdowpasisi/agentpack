# Naming Signals For Ranking Design

Date: 2026-05-20
Project: AgentPack
Scope: Ranking, offline summaries, public-symbol naming guidance

## Goal

Improve AgentPack's ranking precision and explainability by using domain-revealing public names as an additional signal during summary generation and file scoring.

The feature should help AgentPack benefit from well-named files, exported symbols, CLI commands, tests, and config/env identifiers without turning the project into a global naming-enforcement system.

## Non-Goals

- Enforcing naming quality for local variables, parameters, or private implementation details
- Adding a hard lint rule or CI failure for naming style
- Renaming the existing codebase as part of this change
- Making naming quality dominate core ranking signals such as changed files, dependency relationships, or task-keyword matches

## Problem

AgentPack already extracts symbols, inferred roles/domains, entrypoints, and ranking keywords. That helps a lot, but it still treats many public names mostly as raw tokens. This leaves value on the table:

- Domain-revealing public names like `verify_otp`, `SessionTokenManager`, or `StripeWebhookHandler` should be more useful than generic names like `handle`, `run`, or `process`.
- Generic public names can make multiple files look artificially similar when a task is broad.
- Ranking explanations do not currently tell the user whether a file benefited from strong public naming or suffered from vague public names.

The aim is not to "force better names everywhere", but to let AgentPack exploit high-signal names when they exist and gently discount low-signal names when they are the main thing a file has going for it.

## Product Decision

Use a hybrid approach:

- Add a lightweight naming-aware ranking signal in code
- Add a soft public-naming guideline in docs for agents/contributors

The signal applies only to public-ish surfaces:

- filenames
- top-level public Python functions and classes
- public class methods
- exported JS/TS functions/classes/components
- CLI command names
- test names
- env/config identifiers

It does not apply to:

- local variables
- parameters
- temporary helper names inside function bodies

## User Value

Expected improvements:

- Better precision when several files share generic role/domain keywords
- Better recall for semantically named APIs, handlers, tests, and config files
- Better `explain` output and ranking receipts
- Better alignment between "write domain-revealing public names" and "AgentPack finds the right file faster"

## High-Level Approach

### 1. Add deterministic naming classification

Create a small naming-signal classifier that evaluates public names as:

- `domain_revealing`
- `generic`
- `neutral`

The classifier should be deterministic and string-based, not model-based.

Signals for `domain_revealing`:

- name contains task/domain tokens such as `otp`, `token`, `stripe`, `session`, `cache`, `rank`
- multi-part names that combine action + domain or entity + domain
- public test names that describe behavior instead of generic setup
- config/env identifiers with specific domain context

Signals for `generic`:

- public names such as `handle`, `run`, `data`, `utils`, `helper`, `process`, `manager`, `service` when unqualified
- weak filenames like `common.py`, `helpers.ts`, `misc.js`, `utils.py` when not paired with domain tokens

Guardrail:

- Generic names are only a small negative signal
- Qualified generic stems like `TokenService`, `WebhookHandler`, `SessionManager` should not be treated as generic

### 2. Surface naming signals in summaries

Extend offline summaries with structured naming data so later ranking and explain steps can use it.

Likely fields:

- `public_api` (already exists; keep using it)
- `naming_signals`
- `naming_keywords`

`naming_signals` should carry compact, structured output such as:

- strong public names
- generic public names
- public name quality summary

The summary layer is the right place because it centralizes language-specific extraction and already stores ranking-oriented structured fields.

### 3. Use naming signals in ranking

In ranking:

- add a bonus for strong public naming
- add a small penalty for vague public naming
- let this affect tie-breaking and precision, not core recall guarantees

Constraints:

- changed files remain dominant
- staged files remain dominant
- direct dependency/reverse dependency signals remain dominant
- naming penalty should never bury an obviously relevant changed file

### 4. Expose reasons clearly

Ranking receipts and `explain` output should say why naming mattered.

Examples:

- `matched public API name: verify_otp`
- `matched naming keyword: stripe`
- `generic public API penalty: handle`

This keeps the feature explainable instead of feeling like a hidden style score.

### 5. Add soft policy docs

Add a short contributor/agent guideline that says:

- prefer domain-revealing public names
- qualify generic stems with domain context
- optimize public names for comprehension and retrieval, not verbosity

Examples:

- `verify_otp` > `handle`
- `StripeWebhookHandler` > `Processor`
- `session_token_expiry_test` > `test_flow`

This should be guidance, not enforcement.

## Architecture

### Naming classifier location

Best fit: `src/agentpack/analysis/symbols.py` or a nearby analysis helper dedicated to public-name tokenization/classification.

Reason:

- symbol extraction already lives there
- public/exported status is closest to extraction
- this avoids duplicating naming heuristics across summary and ranking layers

If the classifier becomes large, split it into a small dedicated helper module such as `analysis/naming_signals.py`.

### Summary integration

Best fit: `src/agentpack/summaries/offline.py`

Responsibilities:

- compute naming-signal fields from extracted public names
- store them in `FileSummary`
- optionally render compact naming hints in summary text

### Ranking integration

Best fit: `src/agentpack/analysis/ranking.py`

Responsibilities:

- match task keywords against naming keywords / public API names
- add small bonus and penalty amounts
- emit receipts with exact reasons

## Data Shape

Likely `FileSummary` additions:

- `naming_signals: list[str]`
- `naming_keywords: list[str]`

Possible values:

- `strong public name: verify_otp`
- `strong public name: StripeWebhookHandler`
- `generic public name: handle`

To keep the cache compact:

- dedupe aggressively
- cap each list
- avoid storing all names when only the public/high-signal subset matters

## Heuristic Rules

### Strong-name rules

A public name is strong when one or more apply:

- contains 2+ meaningful tokens
- includes a domain/entity token plus an action/responsibility token
- contains specific product/domain language already useful for ranking
- for tests, describes a concrete behavior or case
- for env/config names, includes system/domain scope

### Generic-name rules

A public name is generic when:

- it is a short unqualified stem like `run`, `handle`, `data`, `utils`, `helper`, `common`, `base`
- it lacks domain/entity context
- it is the main public name signal in the file

### Neutral-name rules

Everything else is neutral.

### Important guardrail

Generic stems should be evaluated in context:

- `handle` is generic
- `handle_webhook` is not generic
- `Service` is generic
- `BillingService` is not generic

## Scoring Policy

Recommended scoring behavior:

- Bonus for strong public names: moderate
- Match against naming keywords: moderate
- Generic-name penalty: small

The penalty should mainly matter when:

- the file otherwise has weak evidence
- two files are close and one has much clearer public naming

The penalty should not materially affect:

- changed files
- staged files
- files selected because of direct dependency or test pairing

## Testing Strategy

Add focused tests for:

- Python public-name classification
- JS/TS exported-name classification
- generic-vs-qualified stem handling
- summary fields populated as expected
- ranking bonus from strong names
- ranking penalty from vague public names
- receipts/explain reasons

Examples:

- `verify_otp` gets positive naming signal
- `handle` gets generic penalty
- `WebhookHandler` is neutral/positive, not generic
- `utils.py` is only weakly relevant unless backed by other signals

## Risks And Mitigations

Risk: false penalties for established generic terms like `controller` or `handler`.
Mitigation: only penalize unqualified stems; do not penalize domain-qualified names.

Risk: too much scoring weight turns this into style enforcement.
Mitigation: keep weight small and subordinate to existing ranking signals.

Risk: cache/schema churn adds noise.
Mitigation: add compact fields only; version schema only if required by current summary loading behavior.

Risk: naming docs drift into prescriptive lint culture.
Mitigation: keep guidance short, public-surface-only, and framed as retrieval/comprehension help.

## Success Criteria

This change is successful if:

- AgentPack ranks semantically named public APIs/tests slightly better on relevant tasks
- generic public names no longer get equal treatment when they are otherwise weak signals
- `explain`/receipts clearly show when naming helped or hurt
- the feature remains deterministic and low-noise
- no hard enforcement is introduced

## Recommended Scope For First Implementation

Ship the smallest useful version:

- classify public names
- store `naming_signals` and `naming_keywords`
- integrate small ranking bonus/penalty
- add tests
- add one short public-naming guidance doc update

Do not add:

- broad repo-wide renames
- CI lint rules
- local-variable analysis
