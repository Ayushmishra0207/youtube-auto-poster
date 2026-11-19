# tests/test_shorts_prompt_rules.py
from pipeline.locales import get_locale
from pipeline.script_generator import _build_shorts_system_prompt

# The prompt is built per-locale now; the SEO rules must hold for the default (Hindi) locale
_SHORTS_SYSTEM_PROMPT = _build_shorts_system_prompt(get_locale(None))


def test_first_line_hook_rule_present():
    assert "first 5 words" in _SHORTS_SYSTEM_PROMPT or "3 seconds" in _SHORTS_SYSTEM_PROMPT


def test_hashtag_count_rule_present():
    assert "3-5" in _SHORTS_SYSTEM_PROMPT


def test_tag_count_rule_present():
    assert "12-15" in _SHORTS_SYSTEM_PROMPT


def test_next_short_tease_rule_present():
    assert "next short" in _SHORTS_SYSTEM_PROMPT.lower()


def test_schema_keys_unchanged():
    for key in ("title", "description", "tags", "items", "headline", "narration", "image_search"):
        assert f'"{key}"' in _SHORTS_SYSTEM_PROMPT


if __name__ == "__main__":
    test_first_line_hook_rule_present()
    test_hashtag_count_rule_present()
    test_tag_count_rule_present()
    test_next_short_tease_rule_present()
    test_schema_keys_unchanged()
    print("All tests passed.")
