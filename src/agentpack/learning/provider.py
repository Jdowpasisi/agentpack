from __future__ import annotations

import json
import shlex
import subprocess

from pydantic import ValidationError

from agentpack.learning.models import LearningReport


class LearningProviderError(RuntimeError):
    pass


def run_provider_command(command: str, report: LearningReport, *, timeout_seconds: int = 60) -> LearningReport:
    """Enrich a report through a user-supplied local command.

    The command receives the current LearningReport JSON on stdin and must return
    a JSON object with LearningReport-compatible fields on stdout.
    """
    parts = shlex.split(command)
    if not parts:
        raise LearningProviderError("Provider command is empty")
    try:
        result = subprocess.run(
            parts,
            input=json.dumps(report.model_dump(mode="json"), sort_keys=True),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LearningProviderError(str(exc)) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise LearningProviderError(detail or f"Provider command exited {result.returncode}")
    try:
        override = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise LearningProviderError(f"Provider command returned invalid JSON: {exc}") from exc
    if not isinstance(override, dict):
        raise LearningProviderError("Provider command must return a JSON object")
    merged = report.model_dump(mode="json")
    for key, value in override.items():
        if key in merged:
            merged[key] = value
    try:
        return LearningReport.model_validate(merged)
    except ValidationError as exc:
        raise LearningProviderError(f"Provider response did not match LearningReport schema: {exc}") from exc
