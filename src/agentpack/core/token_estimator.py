def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def estimate_tokens_bytes(size_bytes: int) -> int:
    return max(1, size_bytes // 4)
