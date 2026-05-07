from __future__ import annotations

import os

_encoder = None


def _get_encoder():
    global _encoder
    if _encoder is None:
        try:
            import tiktoken
            # Only load tiktoken if its vocab cache already exists — avoids
            # a blocking network download when running inside git hooks.
            cache_dir = os.environ.get(
                "TIKTOKEN_CACHE_DIR",
                os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub"),
            )
            tiktoken_cache = os.path.join(os.path.expanduser("~"), ".cache", "tiktoken")
            cache_warm = os.path.isdir(tiktoken_cache) and any(
                True for _ in os.scandir(tiktoken_cache)
            ) if os.path.isdir(tiktoken_cache) else False
            if cache_warm or os.environ.get("AGENTPACK_FORCE_TIKTOKEN"):
                _encoder = tiktoken.get_encoding("cl100k_base")
            else:
                _encoder = False
        except ImportError:
            _encoder = False
    return _encoder


def estimate_tokens(text: str) -> int:
    enc = _get_encoder()
    if enc:
        return max(1, len(enc.encode(text, disallowed_special=())))
    return max(1, len(text) // 4)


def estimate_tokens_bytes(size_bytes: int) -> int:
    return max(1, size_bytes // 4)
