"""
Draft short promotional captions for YouTube's Community-post tab.

YouTube's Community tab has no public API — there is no way to publish a
post there programmatically. This module only drafts the caption text (in
the video's own language) from the latest video/Short's title+description;
a human copies it into YouTube Studio or the mobile app themselves.
"""
from pipeline.locales import Locale, get_locale
from pipeline.script_generator import _generate_via_chain


def _build_system_prompt(locale: Locale) -> str:
    return f"""You are a social-media caption writer for a YouTube news channel.
Write ENTIRELY in {locale.language_name} — no other language mixed in except
proper nouns/brand names that don't translate.

Return ONLY valid JSON, nothing else:
{{"text": "...", "hashtags": ["...", "..."]}}

Rules:
- "text": a punchy, curiosity-driven caption under 220 characters (YouTube
  Community posts are short — this is not a video description).
- End "text" with a soft question that invites viewers to comment
  (e.g. equivalent to "What do you think?" / "Did you see this coming?").
- Include exactly 1-2 relevant emoji, placed naturally, not spammy.
- "hashtags": 3-5 short hashtags (no spaces, no # symbol in the strings),
  channel-relevant, in {locale.language_name} where natural or the channel's
  brand tag "bitnomad1" as one of them.
- No markdown, no quotes-within-quotes, no line breaks inside "text"."""


def generate_community_post(title: str, description: str, locale: Locale | None = None) -> dict:
    """
    Draft one Community-post caption from a video/Short's title+description.
    Returns {"text": str, "hashtags": [str, ...]}.
    Raises if every free provider fails (caller should catch and skip this round).
    """
    locale = locale or get_locale(None)
    system_prompt = _build_system_prompt(locale)
    user_content = (
        f'Video title: "{title}"\n'
        f'Video description: "{(description or "")[:400]}"\n\n'
        "Write one Community-post caption promoting this video to existing subscribers."
    )
    return _generate_via_chain(
        user_content,
        topic=f"community-post:{title[:40]}",
        system_prompt=system_prompt,
        required_key="text",
    )
