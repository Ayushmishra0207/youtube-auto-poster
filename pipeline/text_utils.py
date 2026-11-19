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


# ── YouTube metadata limits ─────────────────────────────────────────────────────
# YouTube rejects (HTTP 400) a videos.insert whose metadata breaks these, which
# loses the whole upload — so every upload path should run its fields through here.

YT_TAGS_MAX_CHARS = 500
YT_DESCRIPTION_MAX_BYTES = 5000


def yt_tag_cost(tag: str) -> int:
    """YouTube counts a tag containing a space as if wrapped in quotes (+2 chars)."""
    return len(tag) + (2 if " " in tag else 0)


def fit_youtube_tags(tags, max_chars: int = YT_TAGS_MAX_CHARS) -> list[str]:
    """Keep tags in order until YouTube's 500-char budget (quotes + commas counted) is used."""
    out: list[str] = []
    total = 0
    for raw in tags or []:
        tag = str(raw).replace("<", "").replace(">", "").replace(",", " ").strip()
        if not tag:
            continue
        cost = yt_tag_cost(tag) + (1 if out else 0)   # +1 for the joining comma
        if total + cost > max_chars:
            continue   # a shorter tag later may still fit
        out.append(tag)
        total += cost
    return out


def fit_youtube_text(text: str, max_bytes: int) -> str:
    """Strip < and > (rejected by YouTube) and cut to max_bytes of UTF-8 on a
    whitespace boundary — Devanagari is 3 bytes/char, so a [:5000] char slice
    can be ~15000 bytes and fail with invalidDescription."""
    text = (text or "").replace("<", "‹").replace(">", "›")
    data = text.encode("utf-8")
    if len(data) <= max_bytes:
        return text
    cut = data[:max_bytes].decode("utf-8", errors="ignore")
    space = max(cut.rfind(" "), cut.rfind("\n"))
    if space > len(cut) * 0.8:
        cut = cut[:space]
    return cut.rstrip()
