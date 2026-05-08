"""Tests for Go, Rust, and Java/Kotlin import extractors."""

from agentpack.analysis.go_imports import extract_imports as go_extract
from agentpack.analysis.rust_imports import extract_imports as rust_extract
from agentpack.analysis.java_imports import extract_imports as java_extract


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


def test_rust_missing_file(tmp_path):
    assert rust_extract(tmp_path / "nonexistent.rs") == []
