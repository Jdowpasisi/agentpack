from agentpack.core.changed_paths import clear_changed_paths, read_changed_paths, record_changed_paths


def test_changed_path_ledger_merges_and_clears(tmp_path):
    record_changed_paths(tmp_path, ["src/a.py", "src\\b.py"], source="test")
    record_changed_paths(tmp_path, ["src/a.py", "src/c.py"], source="test")

    assert read_changed_paths(tmp_path) == {"src/a.py", "src/b.py", "src/c.py"}

    clear_changed_paths(tmp_path)
    assert read_changed_paths(tmp_path) == set()
