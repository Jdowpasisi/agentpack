"""Tests for Go, Rust, and Java/Kotlin import extractors."""

import warnings

from agentpack.analysis.go_imports import extract_imports as go_extract
from agentpack.analysis.rust_imports import extract_imports as rust_extract
from agentpack.analysis.java_imports import extract_imports as java_extract
from agentpack.analysis.python_imports import extract_imports as py_extract
from agentpack.analysis.dependency_graph import build
from agentpack.core.models import FileInfo


def test_go_single_import(tmp_path):
    f = tmp_path / "main.go"
    f.write_text('package main\nimport "fmt"\n')
    assert "fmt" in go_extract(f)


def test_go_block_import(tmp_path):
    f = tmp_path / "main.go"
    f.write_text('package main\nimport (\n\t"fmt"\n\t"os"\n)\n')
    imports = go_extract(f)
    assert "fmt" in imports
    assert "os" in imports


def test_go_aliased_import(tmp_path):
    f = tmp_path / "main.go"
    f.write_text('package main\nimport (\n\tlog "github.com/sirupsen/logrus"\n)\n')
    imports = go_extract(f)
    assert "github.com/sirupsen/logrus" in imports


def test_rust_use(tmp_path):
    f = tmp_path / "lib.rs"
    f.write_text("use std::collections::HashMap;\nuse tokio::runtime;\n")
    imports = rust_extract(f)
    assert "std" in imports
    assert "tokio" in imports


def test_rust_mod(tmp_path):
    f = tmp_path / "main.rs"
    f.write_text("mod auth;\npub mod config;\n")
    imports = rust_extract(f)
    assert "auth" in imports
    assert "config" in imports


def test_rust_extern_crate(tmp_path):
    f = tmp_path / "lib.rs"
    f.write_text("extern crate serde;\n")
    assert "serde" in rust_extract(f)


def test_java_imports(tmp_path):
    f = tmp_path / "Auth.java"
    f.write_text("import java.util.List;\nimport org.springframework.stereotype.Service;\n")
    imports = java_extract(f)
    assert "java.util.List" in imports
    assert "org.springframework.stereotype.Service" in imports


def test_kotlin_imports(tmp_path):
    f = tmp_path / "Auth.kt"
    f.write_text("import kotlinx.coroutines.launch\nimport androidx.compose.runtime.*\n")
    imports = java_extract(f)
    assert "kotlinx.coroutines.launch" in imports


def test_go_missing_file(tmp_path):
    assert go_extract(tmp_path / "nonexistent.go") == []


def test_python_invalid_escape_import_extraction_does_not_warn(tmp_path):
    f = tmp_path / "regex.py"
    f.write_text('import re\nPATTERN = "' + "\\(" + '"\n', encoding="utf-8")

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always", SyntaxWarning)
        imports = py_extract(f)

    assert imports == ["re"]
    assert not [warning for warning in captured if issubclass(warning.category, SyntaxWarning)]


def test_rust_missing_file(tmp_path):
    assert rust_extract(tmp_path / "nonexistent.rs") == []


def test_dependency_graph_resolves_cached_relative_python_imports(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    auth = src / "auth.py"
    session = src / "session.py"
    auth.write_text("from .session import session_age\n", encoding="utf-8")
    session.write_text("def session_age():\n    return 0\n", encoding="utf-8")
    files = [
        FileInfo(path="src/auth.py", abs_path=auth, language="python", size_bytes=20, estimated_tokens=10),
        FileInfo(path="src/session.py", abs_path=session, language="python", size_bytes=30, estimated_tokens=10),
    ]
    summaries = {"src/auth.py": {"imports": [".session"]}}

    graph = build(files, tmp_path, summaries=summaries)

    assert graph.get("src/auth.py").imports == ["src/session.py"]
    assert graph.get("src/session.py").imported_by == ["src/auth.py"]
