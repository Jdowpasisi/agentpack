def slugify(text: str) -> str:
    return text.lower().replace(" ", "-")


def truncate(text: str, max_len: int = 100) -> str:
    return text[:max_len] + "..." if len(text) > max_len else text
