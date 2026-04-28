from __future__ import annotations

_encoder = None


def _get_encoder():
    global _encoder
    if _encoder is None:
        try:
            import tiktoken
            _encoder = tiktoken.get_encoding("cl100k_base")
        except ImportError:
            _encoder = False
    return _encoder


def estimate_tokens(text: str) -> int:
    enc = _get_encoder()
    if enc:
        return max(1, len(enc.encode(text, disallowed_special=())))
    return max(1, len(text) // 4)


def estimate_tokens_bytes(size_bytes: int) -> int:
    # byte-level fallback when text is unavailable
    return max(1, size_bytes // 4)
