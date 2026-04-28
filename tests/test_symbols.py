import pytest
from pathlib import Path
from agentpack.analysis.symbols import extract_python_symbols, extract_js_symbols


def test_python_function(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text("def hello(x, y):\n    '''Greet.'''\n    return x + y\n")
    syms = extract_python_symbols(f)
    names = [s.name for s in syms]
    assert "hello" in names
    fn = next(s for s in syms if s.name == "hello")
    assert fn.kind == "function"
    assert "hello" in fn.signature


def test_python_class_and_method(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text(
        "class Foo:\n"
        "    def bar(self):\n"
        "        pass\n"
    )
    syms = extract_python_symbols(f)
    kinds = {s.kind for s in syms}
    assert "class" in kinds
    assert "method" in kinds


def test_python_invalid_syntax(tmp_path):
    f = tmp_path / "bad.py"
    f.write_text("def (broken:")
    assert extract_python_symbols(f) == []


def test_js_function(tmp_path):
    f = tmp_path / "mod.js"
    f.write_text("export function doThing(x) { return x; }\n")
    syms = extract_js_symbols(f)
    names = [s.name for s in syms]
    assert "doThing" in names


def test_js_class(tmp_path):
    f = tmp_path / "mod.ts"
    f.write_text("export class AuthService {\n  login() {}\n}\n")
    syms = extract_js_symbols(f)
    names = [s.name for s in syms]
    assert "AuthService" in names
