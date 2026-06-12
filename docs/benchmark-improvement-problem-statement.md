# Benchmark Improvement Problem Statement

## Problem

AgentPack needs to improve expanded public-suite recall without spending the
token-precision gains that made the current release credible.

The current system usually finds useful files somewhere in the candidate set,
but too much plausible, non-actionable context still competes for the final
selected slots. The failure mode is not simply "missing recall." It is evidence
density: expected files are often ranked low, capped out, or included with too
much surrounding noise while plausible files consume the same budget.

## Current State

The trusted public baseline from the 0.3.21 release cycle is:

| Suite | Recall | Token precision | Notes |
|---|---:|---:|---|
| Expanded 109-case precision baseline | 57.0% | 50.6% | Verified after parent-checkout expected-file filtering |
| Full 128-case release gate run | 59.9% | 50.0% | Just under the configured 60% recall gate |

The next target remains:

| Metric | Target |
|---|---:|
| Expanded public-suite recall | 65%+ |
| Expanded public-suite token precision | 50%+ |
| `EXPECTED_NOT_FOUND` sampled-public misses | 0 |
| Major language/task-slice recall regression | <= 2 points |

## Why This Is Hard

Recall and precision are now tightly coupled. Broad boosts, broad caps, and
static repo-shaped rules can raise one slice while lowering trust in the full
suite. The main risk is overfitting benchmark cases with rules that look good
in aggregate but do not generalize to real repositories.

The strongest observed pattern is slot waste:

- files with filename or family plausibility but weak task evidence
- wrong-package monorepo files
- tests selected for source tasks, or source selected for test/config tasks
- config/source imbalance in Vite-style tasks
- expected files found in candidates but lost to summary caps or ranking floors
- selected expected files packed with too many low-value tokens

## Improvement Goal

Move AgentPack from recall-heavy retrieval toward evidence-dense selection.

In practical terms, the next improvement should make the selected pack answer:

1. Which files have direct task evidence?
2. Which selected files add new useful coverage?
3. Which selected files are plausible but not actionable?
4. Which expected files were found but lost during ranking, selection, or packing?

The goal is not to add another mode or a broader static list. Keep `balanced`
as the default benchmark mode and improve its dynamic decision policy.

## Constraints

- Do not add a new benchmark mode for the main target.
- Do not optimize for Python only; Python is no longer the main bottleneck.
- Do not use repo-specific static path rules as a shortcut.
- Keep token precision at or above 50%.
- Prefer dynamic evidence: task literals, symbol definitions, imports/calls,
  same-package locality, dependency edges, task intent, and measured
  reason-family precision.
- Validate with affected slices first, then one full public-suite run.

## Active Bottlenecks

| Area | Problem |
|---|---|
| TypeScript/Vite | Expected config/source files are found but often lose to plausible playground, test, or nearby source noise. |
| Go/Gin | Source/test pairing improved, but root source, helper, and test selection is still imprecise. |
| Java/Spring | Build metadata improved, but broad source recovery can admit non-expected Java files. |
| NestJS monorepo | Wrong-package locality and integration/core package confusion still waste slots. |
| Packing | Some expected files are selected but token precision drops because too much low-value context is included. |

## First Diagnostic Questions

For every proposed change, answer these before changing ranking weights:

1. Was the expected file generated as a candidate?
2. If yes, what was its rank and reason family?
3. Was it blocked by summary score floor, family cap, compressed-context cap, or budget?
4. Which selected file displaced it?
5. Did the displaced file add direct task evidence, new useful family coverage, or only plausibility?
6. Would a narrower packing unit improve token precision without changing selected-file recall?

## Candidate Workstreams

1. **Last-slot evidence gate**
   Include the final selected file only when it adds direct task evidence, new
   useful family coverage, strong locality evidence, or task-intent coverage.

2. **Monorepo locality model**
   Detect package/workspace intent dynamically so same-domain but wrong-package
   files do not consume scarce selected slots.

3. **Config/source balance**
   Distinguish config-only, source-only, and config-plus-source tasks using task
   literals, symbols, file families, and reason-family precision.

4. **Source/test pairing**
   Improve source-to-test and test-to-source mapping without broad test cap
   increases.

5. **Snippet/block packing**
   When the right file is selected, pack the relevant function, class, config
   section, or diff-like block instead of spending tokens on the whole summary
   or surrounding context.

## Decision Gate

Keep a change only if:

- full-suite recall moves toward 65%
- full-suite token precision stays at or above 50%
- no major language/task slice loses more than 2 recall points
- the gain is explained by diagnostics, not just aggregate movement

Make a change conditional if:

- it helps one slice but is neutral or mixed on the full suite
- diagnostics show a clear subtype boundary, such as explicit test tasks,
  package-local tests, root Go source, or Vite playground tasks

Revert a change if:

- token precision falls below 50%
- recall gain comes from one narrow benchmark case
- wrong-package, test, docs, generated, or example files start bypassing caps
  without direct evidence

## Success Statement

The next improvement cycle succeeds when AgentPack can publish a full-suite
benchmark showing 65%+ recall and 50%+ token precision, with slice-level
evidence explaining where recall was recovered and why precision remained
credible.
