from __future__ import annotations

import ast
import warnings
from pathlib import Path


def parse_python_source(source: str, path: Path | str) -> ast.Module:
    """Parse scanned Python source without surfacing user-code SyntaxWarnings."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        return ast.parse(source, filename=str(path))
