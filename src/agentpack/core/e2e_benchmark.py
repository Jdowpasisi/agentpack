from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


Variant = Literal["baseline", "agentpack"]


@dataclass(frozen=True)
class E2ERunMetrics:
    case_id: str
    variant: Variant
    task_success: bool | None = None
    validation_passed: bool | None = None
    token_usage: int | None = None
    estimated_cost_usd: float | None = None
    turns: int | None = None
    tool_calls: int | None = None
    time_to_first_correct_file_seconds: float | None = None
    wall_time_seconds: float | None = None
    final_edited_files: list[str] = field(default_factory=list)
    expected_files: list[str] = field(default_factory=list)
    agentpack_noise: list[str] = field(default_factory=list)

    def to_record(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "variant": self.variant,
            "task_success": self.task_success,
            "validation_passed": self.validation_passed,
            "token_usage": self.token_usage,
            "estimated_cost_usd": self.estimated_cost_usd,
            "turns": self.turns,
            "tool_calls": self.tool_calls,
            "time_to_first_correct_file_seconds": self.time_to_first_correct_file_seconds,
            "wall_time_seconds": self.wall_time_seconds,
            "final_edited_files": self.final_edited_files,
            "expected_files": self.expected_files,
            "edited_expected_overlap": sorted(set(self.final_edited_files) & set(self.expected_files)),
            "unexpected_edited_files": sorted(set(self.final_edited_files) - set(self.expected_files)),
            "missing_expected_files": sorted(set(self.expected_files) - set(self.final_edited_files)),
            "agentpack_noise": self.agentpack_noise,
        }


def append_e2e_result(path: Path, metrics: E2ERunMetrics) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(metrics.to_record(), sort_keys=True) + "\n")


def e2e_scaffold_markdown() -> str:
    return """# AgentPack E2E Benchmark Scaffold

Compare the same real task in two variants:

- baseline: agent runs without AgentPack context/routing.
- agentpack: agent starts with AgentPack route/context guidance.

Required metrics:

- task success
- tests or validation pass
- token usage and estimated cost
- turns and tool calls
- time-to-first-correct-file
- wall time
- final edited files vs expected files
- AgentPack noise or slowdown cases

Keep file-selection benchmarks as scoped ranking evidence. Do not claim cost, turn, or task-success gains until this E2E data exists.
"""
