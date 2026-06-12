# Benchmark Learnings

This page records the engineering lessons from the public-suite precision push.
It is a decision log, not a marketing table.

## Current Verified State

The latest verified precision gate was run against the expanded public suite:

```bash
PYTHONPATH=src python -m agentpack.cli benchmark \
  --public-repos \
  --public-repos-file benchmarks/public-repos.toml \
  --public-repos-cache /tmp/agentpack-public-cache-full \
  --misses \
  --prove-targets \
  --min-token-precision 0.50 \
  --min-recall 0.0
```

Result:

| Metric | Result |
|---|---:|
| Scored cases | 109 |
| Avg recall | 57.0% |
| Avg token precision | 50.6% |
| Precision target | Passed, 50.0% |

Recall was intentionally not used as a pass/fail gate for this run because the
active target was token precision. Recall remains below the longer-term 65%+
quality bar.

## What Improved

The precision target improved because the work separated the problem into
ranking, selection, and packing failures instead of tuning one global score.

The most useful improvements were:

| Change | Why it helped |
|---|---|
| Literal definition matching | Quoted API names such as `parseAst` should prefer the defining/exporting file over call-site noise. |
| Multi-term path ranking | Tasks with several concrete path terms should reward files whose paths contain those terms, especially config files. |
| Conditional two-config cap | Low-budget strict packs can include two strongly matched config files without opening the door to generic config noise. |
| Package-root source detection | Monorepos often keep source under `packages/<name>/...` without a `src/` segment. Those files need direct-source priority when evidence is strong. |
| Narrow root-Go strict support | Root Go source files with conventional-scope source evidence recovered Gin recall without expanding the summary cap. |
| Same-package paired-test overflow | Balanced no-live packs may include one extra `packages/<name>/...` test only when it directly tests an already selected source file and has direct content evidence. This recovered a NestJS expected test without a broad cap increase. |
| Same-playground test overflow | Balanced no-live packs may include one extra `playground/<name>/...` test only when the same playground already has selected context plus scope and phrase/content evidence. This recovered one Vite playground test with near-neutral token precision. |
| JVM build metadata signal | Java build/dependency tasks often expect root `pom.xml` or Gradle metadata. Root JVM build files now get a scoped boost. |
| Reason/family diagnostics | `reason_family_precision`, selected family waste, failure type counts, and low-budget last-file waste made tuning evidence-backed. |
| Parent-checkout expected-file filtering | Public history samples now exclude paths that do not exist in the parent checkout, so added files are not counted as selectable recall misses. |

## What Failed

These experiments were rejected because they helped one slice while hurting the
full suite:

| Rejected change | Failure mode |
|---|---|
| Broad content-only concrete boost | It over-selected noisy files with generic content hits and regressed TypeScript precision. |
| Treating `.go` files as release metadata | It pulled `version.go` into unrelated Gin tasks and hurt Go precision. |
| Broad explicit-test cap increase | It improved some recall but admitted too much test noise. |
| Specific-config pack suppression | It cleaned one Tailwind config case, but regressed CSS/config tasks that still needed source files. |
| Broad build metadata boost for `pyproject.toml` and package files | It fixed Spring-like tasks but hurt Python dependency/update cases, especially MarkupSafe. |
| Broad source strict-support exception | It recovered a few Go source files but admitted non-expected Java source and spent precision margin. Narrowing to the measured root-Go pattern kept the gain and removed the Java regression. |
| Compact-cost selection priority for JS/TS skeletons | It fixed one NestJS ordering issue, but reduced Vite precision by promoting plausible package tests over expected playground/config files. The safer retained rule is paired-test overflow only. |
| Weak package-test overflow | A Vite `worker.spec.ts` test looked locally related but had only 3 content hits and no task phrase for an `import glob` task. Package test overflow now requires stronger task evidence to avoid this slot waste. |

The rule from these failures: keep boosts scoped to the evidence family that
proved the gain. Do not generalize from one benchmark case until the repo slice
and full suite confirm it.

## Benchmark Validity Guardrail

Public history cases run AgentPack against the parent of a real commit. A file
added by that commit does not exist in the parent checkout, so AgentPack cannot
select it. Sampled expected files must therefore be filtered to paths that exist
in the parent commit.

This is a methodology correction, not a ranking improvement. It removes
impossible `EXPECTED_NOT_FOUND` misses from sampled public cases while preserving
modified/deleted files that are selectable from the parent checkout.

## Static-List Guardrail

Static lists are acceptable only when they encode portable ecosystem
conventions, not benchmark-case outcomes.

Acceptable examples:

| Convention | Why it is acceptable |
|---|---|
| Test filename forms such as `_test.go`, `.spec.ts`, and `tests/` | These are language and framework conventions used outside the benchmark suite. |
| Root build metadata such as `pom.xml`, Gradle files, and package manifests | These are standard project files for dependency/build tasks. |
| File extensions and generated/example/test directory names | These describe broad file families, not one repo's expected answer. |

Risky examples:

| Shortcut | Why it is risky |
|---|---|
| Boosting a specific filename because one public case expected it | It can inflate one slice while hurting unrelated tasks. |
| Adding repo-shaped path rules such as a known package or fixture directory | It makes benchmark numbers less trustworthy and does not generalize. |
| Treating a language extension as task metadata without stronger evidence | It admits plausible-but-not-actionable files and wastes selection slots. |

New ranking rules should prefer dynamic evidence: task literals, symbol
definitions, imports/calls, same-package locality, dependency edges, changed-file
history, and measured reason-family precision. If a static convention is added,
it needs a non-benchmark rationale plus negative tests that prove it does not
revive known noisy families.

## Slice Readout

The latest useful slice picture:

| Slice | Status |
|---|---|
| Python CLI/library | No longer the main precision bottleneck. Click and itsdangerous are healthy; MarkupSafe recovered after narrowing build metadata. |
| TypeScript/Vite | Same-playground test overflow moved the current Vite slice from 44.5% to 45.7% recall with token precision essentially neutral at 45.5% to 45.4%. Config/source ranking and ranked-low expected files remain the main blockers. |
| Go/Gin | Improved after root Go source and test-path handling. Latest targeted slice moved from 48.1% to 55.6% recall while token precision rose slightly from 46.5% to 47.3%. |
| Java/Spring | Strong gain from scoped JVM build metadata. |
| TypeScript monorepo/NestJS | Same-package paired-test overflow improved the current scored NestJS slice from 62.5% to 70.8% recall and from 40.5% to 44.0% token precision, but the slice remains below the 50% precision target. |

## Benchmark Loop Guardrail

Full public-suite runs are expensive enough that experiments should not use them
as the first diagnostic. Use this loop instead:

1. Establish one full-suite baseline JSONL.
2. Inspect case-level misses and choose the affected repo or task-type slices.
3. Run only those slices with `--public-repo-filter` or
   `--public-task-type-filter` and write `--benchmark-jsonl`.
4. Compare case-level recall, token precision, selected paths, and miss status.
5. Run the full public suite once only after the slice result has a credible
   chance of improving the aggregate gate.

Example:

```bash
agentpack benchmark \
  --public-repos \
  --public-repo-filter gin,spring-petclinic \
  --public-repos-cache /tmp/agentpack-public-cache-full \
  --benchmark-jsonl /tmp/agentpack-go-java.jsonl \
  --misses
```

## Current Mental Model

Do not ask only whether recall went up. Ask where the expected file was lost:

1. Candidate generation: was the expected file found at all?
2. Ranking: did it reach the top candidates?
3. Selection: did the pack choose it under budget and family caps?
4. Packing: did selected tokens include useful expected-file content or mostly noise?

Useful recall is not just "the file appeared somewhere." It means the expected
file appeared early, survived selection, and contributed enough useful tokens.

## Metrics To Keep Watching

These metrics were the most useful during tuning:

| Metric | Use |
|---|---|
| `candidate_recall_at_50` | Separates discovery failures from ranking/selection failures. |
| `candidate_precision_at_3` | Shows whether noisy files dominate the top of the ranked list. |
| `token_precision` | Main measure for packed-token usefulness. |
| `expected_token_coverage` | Approximates valuable recall for selected expected files. |
| `selected_family_waste_tokens` | Shows whether source, test, docs, config, fixtures, or generated files leak noise. |
| `reason_family_precision` | Shows which ranking reasons are trustworthy. |
| `failure_type_counts` | Splits misses into not found, ranked low, skipped, or noise selected above expected. |
| `precision_delta_if_drop_last_summary` | Identifies low-budget extra-file waste. |

## Next Optimization Areas

The next benchmark release target is:

| Metric | Target |
|---|---:|
| Expanded public-suite recall | 65%+ |
| Expanded public-suite token precision | 50%+ |
| Major language/task-slice recall regression | <= 2 points |
| `EXPECTED_NOT_FOUND` sampled-public misses | 0 |

The current verified baseline is 57.0% recall / 50.6% token precision across
109 scored public cases, so the next release should be treated as a recall
recovery release with a hard precision floor. Do not claim the target from
slice-only improvements; publish the full-suite run before using the number in
release notes.

The next precision/recall work should focus on these areas:

1. NestJS wrong-package locality.
   Monorepo tasks need better package/workspace intent detection so `packages/core`
   and `integration/*` do not steal from each other unless the task evidence says
   so.

2. Vite config/source balance.
   Some config tasks need only config files, while CSS/build tasks need both source
   and config. Selection needs conditional inclusion, not global suppression.

3. Gin source/test pairing.
   Go test naming is now recognized, but tasks still confuse root source, helpers,
   and tests. More precise source-to-test mapping is needed.

4. Snippet/block packing.
   Several cases select the expected file but include too much surrounding noise.
   Function, class, config-section, and diff-hunk packing should improve token
   precision without sacrificing selected-file recall.

5. Publish decision gates.
   Keep changes only when full-suite recall moves toward 65%, token precision
   stays at or above 50%, and no major language/task slice regresses by more
   than 2 recall points.
