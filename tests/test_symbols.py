from agentpack.analysis.naming_signals import (
    classify_public_name,
    collect_public_name_candidates,
)
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


def test_js_arrow_function_detected(tmp_path):
    f = tmp_path / "mod.js"
    f.write_text("const handleClick = (e) => { console.log(e); }\n")
    syms = extract_js_symbols(f)
    names = [s.name for s in syms]
    assert "handleClick" in names


def test_js_arrow_function_no_params(tmp_path):
    f = tmp_path / "mod.js"
    f.write_text("const init = () => { return 42; }\n")
    syms = extract_js_symbols(f)
    names = [s.name for s in syms]
    assert "init" in names


def test_js_non_arrow_assignment_not_extracted(tmp_path):
    # This is NOT an arrow function — should not be extracted as a function symbol
    f = tmp_path / "mod.js"
    f.write_text("const result = (a + b) * c;\n")
    syms = extract_js_symbols(f)
    names = [s.name for s in syms]
    assert "result" not in names


def test_js_async_arrow_function(tmp_path):
    f = tmp_path / "mod.ts"
    f.write_text("export const fetchUser = async (id: string) => {\n  return db.find(id);\n};\n")
    syms = extract_js_symbols(f)
    names = [s.name for s in syms]
    assert "fetchUser" in names


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


def test_collect_public_name_candidates_js_exports_only(tmp_path):
    f = tmp_path / "mod.ts"
    f.write_text(
        "export function verifyOtp() { return true; }\n"
        "const hiddenHelper = () => false;\n"
        "export class StripeWebhookHandler {}\n"
    )
    candidates = collect_public_name_candidates(f, "typescript")
    assert "verifyOtp" in candidates
    assert "StripeWebhookHandler" in candidates
    assert "hiddenHelper" not in candidates
