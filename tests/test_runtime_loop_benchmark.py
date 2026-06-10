from agentpack.core.token_estimator import estimate_tokens
from agentpack.learning.collector import LearningInputs
from agentpack.learning.extractor import build_learning_report
from agentpack.output_compression import compress_output


def test_runtime_loop_output_compression_saves_tokens_and_preserves_failure():
    raw = "\n".join(["cache warmup ok"] * 300 + ["FAILED tests/test_auth.py::test_retry - AssertionError"])

    compressed = compress_output(raw, kind="pytest", max_items=20)

    assert estimate_tokens(compressed) < estimate_tokens(raw)
    assert "FAILED tests/test_auth.py::test_retry" in compressed


def test_runtime_loop_learning_tracks_selection_hit_rate_inputs():
    report = build_learning_report(
        LearningInputs(
            task="add pack registry retrieval",
            changed_files={
                "src/agentpack/core/pack_registry.py": "added",
                "tests/test_pack_registry.py": "added",
            },
            selected_files=["src/agentpack/core/pack_registry.py"],
        )
    )

    assert report.selected_hits == ["src/agentpack/core/pack_registry.py"]
    assert report.selected_misses == ["tests/test_pack_registry.py"]
