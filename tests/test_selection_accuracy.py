from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentpack.application.pack_service import (
    _load_last_record,
    _compute_selection_accuracy,
)


def _write_metrics(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def test_load_last_record_empty(tmp_path):
    assert _load_last_record(tmp_path / "metrics.jsonl") is None


def test_load_last_record_no_selected_paths(tmp_path):
    p = tmp_path / ".agentpack" / "metrics.jsonl"
    _write_metrics(p, [{"task": "x", "packed_tokens": 100}])
    assert _load_last_record(p) is None


def test_load_last_record_returns_latest_with_paths(tmp_path):
    p = tmp_path / ".agentpack" / "metrics.jsonl"
    _write_metrics(p, [
        {"task": "old", "selected_paths": ["a.py"]},
        {"task": "new", "selected_paths": ["b.py", "c.py"]},
    ])
    rec = _load_last_record(p)
    assert rec is not None
    assert rec["task"] == "new"


def test_load_last_record_skips_records_without_paths(tmp_path):
    p = tmp_path / ".agentpack" / "metrics.jsonl"
    _write_metrics(p, [
        {"task": "old", "selected_paths": ["a.py"]},
        {"task": "new_no_paths", "packed_tokens": 999},
    ])
    rec = _load_last_record(p)
    assert rec is not None
    assert rec["task"] == "old"


def test_compute_accuracy_no_previous(tmp_path):
    p = tmp_path / ".agentpack" / "metrics.jsonl"
    result = _compute_selection_accuracy(tmp_path, p, ["a.py"], {"a.py", "b.py"})
    assert result == {}


def test_compute_accuracy_empty_changed(tmp_path):
    p = tmp_path / ".agentpack" / "metrics.jsonl"
    _write_metrics(p, [{"selected_paths": ["a.py"]}])
    result = _compute_selection_accuracy(tmp_path, p, ["a.py"], set())
    assert result == {}


def test_compute_accuracy_perfect_recall(tmp_path):
    p = tmp_path / ".agentpack" / "metrics.jsonl"
    _write_metrics(p, [{"selected_paths": ["a.py", "b.py"]}])
    result = _compute_selection_accuracy(tmp_path, p, [], {"a.py", "b.py"})
    assert result["selection_recall"] == 1.0
    assert result["selection_precision"] == 1.0
    assert result["selection_f1"] == 1.0


def test_compute_accuracy_partial(tmp_path):
    p = tmp_path / ".agentpack" / "metrics.jsonl"
    _write_metrics(p, [{"selected_paths": ["a.py", "b.py", "c.py", "d.py"]}])
    # prev selected 4 files, 2 actually changed
    result = _compute_selection_accuracy(tmp_path, p, [], {"a.py", "b.py"})
    assert result["selection_recall"] == 1.0      # both changed files were selected
    assert result["selection_precision"] == 0.5   # 2 of 4 selected were relevant
    assert result["selection_f1"] == pytest.approx(2 / 3, abs=0.001)


def test_compute_accuracy_zero_hits(tmp_path):
    p = tmp_path / ".agentpack" / "metrics.jsonl"
    _write_metrics(p, [{"selected_paths": ["x.py", "y.py"]}])
    result = _compute_selection_accuracy(tmp_path, p, [], {"a.py", "b.py"})
    assert result["selection_recall"] == 0.0
    assert result["selection_precision"] == 0.0
    assert result["selection_f1"] == 0.0
