from __future__ import annotations

from agentpack.core.models import Receipt


def format_receipts(receipts: list[Receipt]) -> str:
    lines = []
    for r in receipts:
        lines.append(f"- `{r.path}` {r.action}: {r.reason}")
    return "\n".join(lines)
