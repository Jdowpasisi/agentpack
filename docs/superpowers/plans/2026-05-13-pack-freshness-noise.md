# Pack Freshness And Noise Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AgentPack context packs more trustworthy by surfacing freshness metadata, reducing generic-term noise, improving missed-file diagnostics, and reporting usefulness metrics by task type.

**Architecture:** Keep changes inside the existing pack pipeline: git/task provenance is collected in `pack_service.py`, rendered in `context_pack.py`, ranking heuristics stay in `ranking.py`, benchmark diagnostics stay in `benchmark.py`, and tests cover each behavior at the command/unit layer. Use conservative scoring changes that only downweight broad task terms when the task lacks concrete repo/domain signals.

**Tech Stack:** Python 3.10+, Typer, pytest, existing AgentPack ranking and benchmark modules.

---

### Task 1: Release Branch State

**Files:**
- No source files.

- [x] **Step 1: Confirm local release state**

Run: `git status -sb`
Expected: no tracked modified files.

- [x] **Step 2: Fast-forward local main**

Run: `git branch -f main origin/main`
Expected: local `main` points at the same commit as `origin/main`.

- [x] **Step 3: Create implementation branch**

Run: `git switch -c codex/pack-freshness-noise origin/main`
Expected: branch starts from release `0.1.23`.

### Task 2: Freshness Metadata

**Files:**
- Modify: `src/agentpack/application/pack_service.py`
- Modify: `src/agentpack/core/context_pack.py`
- Test: `tests/test_context_pack.py`

- [x] **Step 1: Add failing tests**

Assert rendered context contains generated time, branch, git SHA, task source, changed-file source, and warnings when metadata is stale.

- [x] **Step 2: Implement metadata collection and rendering**

Extend pack metadata with explicit provenance and render a top-level freshness block before token stats.

- [x] **Step 3: Run focused tests**

Run: `pytest tests/test_context_pack.py -q`
Expected: pass.

### Task 3: Generic-Term Noise Control

**Files:**
- Modify: `src/agentpack/analysis/ranking.py`
- Modify: `src/agentpack/application/pack_service.py`
- Test: `tests/test_ranking.py`
- Test: `tests/test_context_pack.py`

- [x] **Step 1: Add failing ranking tests**

Assert broad task terms are downweighted and concrete terms still rank relevant files.

- [x] **Step 2: Implement generic task-term detection**

Add a small generic-term set, compute generic ratio, reduce broad keyword contribution, and tighten weak summary caps when the task is broad.

- [x] **Step 3: Run focused tests**

Run: `pytest tests/test_ranking.py tests/test_context_pack.py -q`
Expected: pass.

### Task 4: Miss Diagnostics And Typed Evals

**Files:**
- Modify: `src/agentpack/commands/benchmark.py`
- Modify: `src/agentpack/analysis/ranking.py`
- Test: `tests/test_benchmark.py`
- Test: `tests/test_ranking_evals.py`

- [x] **Step 1: Add failing benchmark tests**

Assert missed files explain ignored, below-floor, summary-cap, budget, stale-basis, and low-score cases where available.

- [x] **Step 2: Add task type metrics**

Allow benchmark fixtures to carry `task_type` and report recall/precision/F1 grouped by that type.

- [x] **Step 3: Run focused tests**

Run: `pytest tests/test_benchmark.py tests/test_ranking_evals.py -q`
Expected: pass.

### Task 5: Verification

**Files:**
- All changed files.

- [x] **Step 1: Run lint**

Run: `python -m ruff check src tests`
Expected: pass.

- [x] **Step 2: Run full tests**

Run: `pytest`
Expected: pass.

- [x] **Step 3: Check final diff**

Run: `git diff --check`
Expected: no whitespace errors.
