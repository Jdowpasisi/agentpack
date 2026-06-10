from agentpack.output_compression import compress_output


def test_compress_output_preserves_failures():
    content = "\n".join(["noise"] * 100 + ["FAILED tests/test_app.py::test_auth - AssertionError", "E expected 1 got 2"])

    result = compress_output(content, kind="pytest", max_items=10)

    assert "FAILED tests/test_app.py::test_auth" in result
    assert "expected 1 got 2" in result
    assert "Repeated Lines" in result


def test_compress_output_returns_empty_for_empty_input():
    assert compress_output("") == ""


def test_compress_output_uses_diff_adapter():
    content = "\n".join(["context"] * 100 + ["diff --git a/app.py b/app.py", "@@ -1 +1 @@", "-old", "+new"])

    result = compress_output(content, kind="git-diff", max_items=10)

    assert "Diff Hunks" in result
    assert "diff --git a/app.py b/app.py" in result


def test_compress_output_uses_search_adapter():
    content = "\n".join(["scan"] * 100 + ["src/app.py:12:def run():", "tests/test_app.py:8:assert run()"])

    result = compress_output(content, kind="rg", max_items=10)

    assert "Search Matches" in result
    assert "src/app.py:12:def run()" in result
