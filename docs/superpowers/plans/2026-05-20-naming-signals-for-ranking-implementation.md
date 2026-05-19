# Naming Signals For Ranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add naming-aware summary and ranking signals so AgentPack benefits from domain-revealing public names on files, exported symbols, tests, and config/env identifiers without enforcing naming rules on local implementation details.

**Architecture:** Introduce a small deterministic naming-signal helper in analysis, feed its output into offline summaries and `FileSummary`, then add modest ranking bonuses and penalties with explicit receipts. Keep the feature public-surface-only and subordinate to stronger ranking signals like changed files, dependencies, and task matches. Add focused tests around classification, summary population, and ranking behavior, plus one lightweight README guidance note.

**Tech Stack:** Python, Pydantic, pytest, Markdown

---

### Task 1: Add deterministic public-name classification helpers

**Files:**
- Create: `src/agentpack/analysis/naming_signals.py`
- Modify: `src/agentpack/analysis/symbols.py`
- Test: `tests/test_symbols.py`

- [ ] **Step 1: Add failing tests for public-name classification**

Append tests to `tests/test_symbols.py` that exercise the classifier directly through the new helper functions:

```python
from agentpack.analysis.naming_signals import (
    classify_public_name,
    collect_public_name_candidates,
)


def test_classify_public_name_domain_revealing():
    result = classify_public_name("verify_otp")
    assert result.label == "domain_revealing"
    assert "verify" in result.keywords
    assert "otp" in result.keywords


def test_classify_public_name_generic_unqualified():
    result = classify_public_name("handle")
    assert result.label == "generic"


def test_classify_public_name_qualified_generic_stem_not_generic():
    result = classify_public_name("WebhookHandler")
    assert result.label != "generic"


def test_collect_public_name_candidates_python_public_only(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text(
        "class SessionManager:\n"
        "    def issue_token(self):\n"
        "        pass\n"
        "    def _helper(self):\n"
        "        pass\n"
        "def verify_otp(code):\n"
        "    return code\n"
    )
    candidates = collect_public_name_candidates(f, "python")
    assert "SessionManager" in candidates
    assert "SessionManager.issue_token" in candidates
    assert "verify_otp" in candidates
    assert "SessionManager._helper" not in candidates
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_symbols.py -q`
Expected: FAIL with import errors or missing helper functions

- [ ] **Step 3: Create `src/agentpack/analysis/naming_signals.py`**

Add a focused helper module with:

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


_GENERIC_PUBLIC_STEMS = {
    "base", "common", "data", "handle", "handler", "helper", "manager",
    "misc", "process", "processor", "run", "service", "thing", "tool",
    "util", "utils",
}


@dataclass
class PublicNameSignal:
    name: str
    label: str
    keywords: list[str]
    reasons: list[str]


def name_tokens(name: str) -> list[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\\1 \\2", name)
    raw = re.split(r"[^a-zA-Z0-9]+", spaced.lower())
    return [tok for tok in raw if tok]


def classify_public_name(name: str) -> PublicNameSignal:
    tokens = name_tokens(name)
    lowered = name.lower()

    if len(tokens) == 1 and tokens[0] in _GENERIC_PUBLIC_STEMS:
        return PublicNameSignal(name=name, label="generic", keywords=tokens, reasons=["generic public stem"])

    if len(tokens) >= 2:
        meaningful = [tok for tok in tokens if len(tok) >= 3]
        if len(meaningful) >= 2:
            return PublicNameSignal(name=name, label="domain_revealing", keywords=meaningful, reasons=["multi-part public name"])

    return PublicNameSignal(name=name, label="neutral", keywords=[tok for tok in tokens if len(tok) >= 3], reasons=[])


def filename_signal(path: str) -> PublicNameSignal:
    return classify_public_name(Path(path).stem)
```

Also add `collect_public_name_candidates(...)` using the existing symbol extraction layer and only returning public/exported names.

- [ ] **Step 4: Update symbol extraction helpers to support public candidate collection**

Modify `src/agentpack/analysis/symbols.py` to add small public-name collection helpers without changing existing `Symbol` extraction semantics:

```python
def collect_public_name_candidates(path: Path, language: str | None) -> list[str]:
    symbols = extract_symbols(path, language)
    names: list[str] = []
    for sym in symbols:
        tail = sym.name.split(".")[-1]
        if tail.startswith("_"):
            continue
        names.append(sym.name)
    return names
```

- [ ] **Step 5: Run tests to verify Task 1 passes**

Run: `pytest tests/test_symbols.py -q`
Expected: PASS

- [ ] **Step 6: Commit Task 1**

```bash
git add src/agentpack/analysis/naming_signals.py src/agentpack/analysis/symbols.py tests/test_symbols.py
git commit -m "feat: add public naming signal analysis"
```

### Task 2: Surface naming signals in `FileSummary` and offline summaries

**Files:**
- Modify: `src/agentpack/core/models.py`
- Modify: `src/agentpack/summaries/offline.py`
- Test: `tests/test_offline_intelligence.py`

- [ ] **Step 1: Add failing tests for summary naming fields**

Append tests to `tests/test_offline_intelligence.py`:

```python
def test_summary_includes_naming_signals_and_keywords(tmp_path: Path) -> None:
    src = _write(
        tmp_path,
        "auth/otp.py",
        "def verify_otp(code):\n"
        "    return code\n"
        "\n"
        "def handle():\n"
        "    return None\n",
    )

    summary = summarize("auth/otp.py", src, "python", "h1")

    assert any("verify_otp" in item for item in summary.naming_signals)
    assert any("handle" in item for item in summary.naming_signals)
    assert "verify" in summary.naming_keywords
    assert "otp" in summary.naming_keywords
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_offline_intelligence.py -q`
Expected: FAIL because `FileSummary` lacks naming fields

- [ ] **Step 3: Extend `FileSummary` with compact naming fields**

Modify `src/agentpack/core/models.py`:

```python
class FileSummary(BaseModel):
    ...
    public_api: list[str] = Field(default_factory=list)
    naming_signals: list[str] = Field(default_factory=list)
    naming_keywords: list[str] = Field(default_factory=list)
    error_paths: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Compute naming signals in `src/agentpack/summaries/offline.py`**

Import the new helper and add a small summarizer:

```python
from agentpack.analysis.naming_signals import classify_public_name, filename_signal


def _summarize_naming(path: str, public_names: list[str]) -> tuple[list[str], list[str]]:
    signals: list[str] = []
    keywords: list[str] = []

    for signal in [filename_signal(path), *[classify_public_name(name.split(".")[-1]) for name in public_names]]:
        if signal.label == "domain_revealing":
            signals.append(f"strong public name: {signal.name}")
        elif signal.label == "generic":
            signals.append(f"generic public name: {signal.name}")
        keywords.extend(signal.keywords)

    return _dedupe(signals)[:12], _dedupe(keywords)[:12]
```

Then thread the results into the Python and JS summary constructors.

- [ ] **Step 5: Run tests to verify Task 2 passes**

Run: `pytest tests/test_offline_intelligence.py tests/test_symbols.py -q`
Expected: PASS

- [ ] **Step 6: Commit Task 2**

```bash
git add src/agentpack/core/models.py src/agentpack/summaries/offline.py tests/test_offline_intelligence.py
git commit -m "feat: add naming signals to offline summaries"
```

### Task 3: Integrate naming bonus and penalty into ranking receipts

**Files:**
- Modify: `src/agentpack/analysis/ranking.py`
- Test: `tests/test_ranking.py`

- [ ] **Step 1: Add failing ranking tests**

Append tests to `tests/test_ranking.py`:

```python
def test_strong_public_name_gets_bonus():
    fi = _fi("src/auth/otp.py")
    summaries = {
        fi.path: {
            "symbols": [],
            "naming_signals": ["strong public name: verify_otp"],
            "naming_keywords": ["verify", "otp"],
        }
    }
    scored = score_files(
        [fi],
        changed_paths=set(),
        staged_paths=set(),
        recently_modified=[],
        dep_graph={},
        keywords=extract_keyword_weights("fix otp verify issue"),
        summaries=summaries,
    )
    assert any("matched naming keyword: otp" in reason or "matched strong public name" in reason for reason in scored[0][2])


def test_generic_public_name_gets_small_penalty_when_otherwise_weak():
    good = _fi("src/auth/otp.py")
    weak = _fi("src/auth/handler.py")
    summaries = {
        good.path: {
            "symbols": [],
            "naming_signals": ["strong public name: verify_otp"],
            "naming_keywords": ["verify", "otp"],
        },
        weak.path: {
            "symbols": [],
            "naming_signals": ["generic public name: handle"],
            "naming_keywords": [],
        },
    }
    scored = score_files(
        [good, weak],
        changed_paths=set(),
        staged_paths=set(),
        recently_modified=[],
        dep_graph={},
        keywords=extract_keyword_weights("fix otp verify issue"),
        summaries=summaries,
    )
    scores = {item[0].path: item[1] for item in scored}
    assert scores["src/auth/otp.py"] > scores["src/auth/handler.py"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ranking.py -q`
Expected: FAIL because ranking does not yet use naming fields

- [ ] **Step 3: Add naming-aware ranking logic**

Modify `src/agentpack/analysis/ranking.py` inside `score_files(...)` after summary-field boosts:

```python
        naming_keywords = _summary_values(summary_data, "naming_keywords")
        naming_signals = _summary_values(summary_data, "naming_signals")

        naming_weight = _symbol_matches_keywords(naming_keywords, keywords)
        if naming_weight > 0:
            score += min(20.0, naming_weight * 18.0)
            match = _best_summary_match(naming_keywords, keywords)
            if match:
                reasons.append(f"matched naming keyword: {match[0]}")

        generic_public_names = [
            value.split(": ", 1)[1]
            for value in naming_signals
            if value.startswith("generic public name: ")
        ]
        if generic_public_names and filename_weight == 0 and symbol_weight == 0 and content_hits == 0:
            score -= 6.0
            reasons.append(f"generic public API penalty: {generic_public_names[0]}")
```

Keep the penalty intentionally small.

- [ ] **Step 4: Run ranking tests**

Run: `pytest tests/test_ranking.py tests/test_offline_intelligence.py tests/test_symbols.py -q`
Expected: PASS

- [ ] **Step 5: Commit Task 3**

```bash
git add src/agentpack/analysis/ranking.py tests/test_ranking.py
git commit -m "feat: use public naming signals in ranking"
```

### Task 4: Add soft public-naming guidance docs

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a small guidance section in README**

Add a short subsection near development / quality guidance:

```md
## Public Naming And Ranking

AgentPack works better when public surfaces carry domain context. Prefer domain-revealing names for files, exported functions/classes, CLI commands, tests, and config/env identifiers.

- `verify_otp` is better than `handle`
- `StripeWebhookHandler` is better than `Processor`
- `session_token_expiry_test` is better than `test_flow`

This is guidance, not a lint rule. Local variable names are out of scope for AgentPack ranking.
```

- [ ] **Step 2: Verify README change**

Run: `rg -n "Public Naming And Ranking|verify_otp|StripeWebhookHandler" README.md`
Expected: section and examples found

- [ ] **Step 3: Commit Task 4**

```bash
git add README.md
git commit -m "docs: add public naming guidance for ranking"
```

### Task 5: Final verification

**Files:**
- Modify: none

- [ ] **Step 1: Run focused verification suite**

Run: `pytest tests/test_symbols.py tests/test_offline_intelligence.py tests/test_ranking.py -q`
Expected: PASS

- [ ] **Step 2: Spot-check summary output**

Run:

```bash
python3 - <<'PY'
from pathlib import Path
from agentpack.summaries.offline import summarize

path = Path("tmp_naming_sample.py")
path.write_text("def verify_otp(code):\n    return code\n\ndef handle():\n    return None\n", encoding="utf-8")
summary = summarize("auth/otp.py", path, "python", "h1")
print(summary.naming_signals)
print(summary.naming_keywords)
path.unlink()
PY
```

Expected: output includes strong signal for `verify_otp`, generic signal for `handle`, and naming keywords such as `verify` and `otp`

- [ ] **Step 3: Review final diff**

Run: `git diff --stat HEAD~4..HEAD`
Expected: only naming-signal analysis, summary/ranking, tests, and README guidance changes
