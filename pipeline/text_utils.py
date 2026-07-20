"""Small shared text helpers."""


def safe_truncate(text: str, max_len: int, suffix: str = "") -> str:
    """
    Truncate text to at most max_len characters (including suffix) without
    cutting a word in half. Falls back to a hard cut only if a single word
    is itself longer than max_len.
    """
    text = (text or "").strip()
    budget = max_len - len(suffix)
    if len(text) <= budget:
        return text + suffix

    cut = text[:budget]
    last_space = cut.rfind(" ")
    if last_space > 0:
        cut = cut[:last_space]
    return cut.rstrip() + suffix
