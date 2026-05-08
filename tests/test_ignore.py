from agentpack.core.ignore import is_ignored, DEFAULT_AGENTIGNORE
import pathspec


def spec_from_text(text: str) -> pathspec.PathSpec:
    return pathspec.PathSpec.from_lines("gitignore", text.splitlines())


def test_node_modules_ignored():
    spec = spec_from_text(DEFAULT_AGENTIGNORE)
    assert is_ignored(spec, "node_modules/lodash/index.js")


def test_venv_ignored():
    spec = spec_from_text(DEFAULT_AGENTIGNORE)
    assert is_ignored(spec, ".venv/lib/python3.11/site.py")


def test_source_file_not_ignored():
    spec = spec_from_text(DEFAULT_AGENTIGNORE)
    assert not is_ignored(spec, "src/main.py")


def test_lock_file_ignored():
    spec = spec_from_text(DEFAULT_AGENTIGNORE)
    assert is_ignored(spec, "package-lock.json")


def test_env_file_ignored():
    spec = spec_from_text(DEFAULT_AGENTIGNORE)
    assert is_ignored(spec, ".env")


def test_dotenv_variant_ignored():
    spec = spec_from_text(DEFAULT_AGENTIGNORE)
    assert is_ignored(spec, ".env.production")


def test_custom_rule():
    spec = spec_from_text("*.secret\n")
    assert is_ignored(spec, "config.secret")
    assert not is_ignored(spec, "config.py")
